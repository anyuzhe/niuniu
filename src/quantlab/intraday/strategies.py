"""Intraday strategies for 底仓做T, from the article 《日内交易策略——当天收盘前必须走人》 (维克, 2026-09-19).

The article trades long and short within the day. A-shares are T+1 and cannot be shorted
freely, so each idea is mapped onto a base position:
- “做多” (buy) becomes 先买后卖: buy extra now, sell the same number of base shares later;
- “做空” (sell) becomes 先卖后买: sell part of the base now, buy it back later.
Every strategy only sees bars up to and including the current one.
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


class Strategy:
    key = ''
    name = ''
    description = ''
    params: dict = {}
    specs: list = []  # (name, label, min, max, step)

    def prepare(self, day, params):
        return {'p': {**self.params, **(params or {})}}

    def entry(self, i, ctx, day) -> int:
        return 0

    def entry_reason(self, i, ctx, day, side) -> str:
        return ''

    def exit(self, i, ctx, day, trip):
        return None


def _vwap(bars):
    volume = np.nan_to_num(bars['volume'])
    amount = np.nan_to_num(bars['amount'])
    cum_v = np.cumsum(volume)
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(cum_v > 0, np.cumsum(amount) / cum_v, np.nan)


def _price_stop(trip, close, pct):
    """Stop out when the trip is `pct` against its entry price (0 disables)."""
    if not pct:
        return False
    entry = trip['entry'].avg()
    side = trip['entry'].side
    return close <= entry * (1 - pct / 100) if side > 0 else close >= entry * (1 + pct / 100)


class OpeningBreakout(Strategy):
    key = 'opening_breakout'
    name = '开盘突破'
    description = ('记下开盘后 30 分钟（09:30–10:00）的最高价和最低价。之后收盘价突破最高价就先买后卖，跌破最低价就先卖后买；'
                   '止损放在区间中点，没止损就拿到收盘前平仓。每天每个方向最多一次。')
    params = {'range_end': '10:00', 'target_x': 0.0}
    specs = [('target_x', '止盈（区间宽度的倍数，0 为不设）', 0.0, 5.0, 0.5)]

    def prepare(self, day, params):
        ctx = super().prepare(day, params)
        minutes = day.bars['minute']
        mask = (minutes > '09:30') & (minutes <= ctx['p']['range_end'])
        ctx['ready'] = bool(mask.any())
        if ctx['ready']:
            ctx['high'] = float(np.nanmax(day.bars['high'][mask]))
            ctx['low'] = float(np.nanmin(day.bars['low'][mask]))
            ctx['mid'] = (ctx['high'] + ctx['low']) / 2
        ctx['used'] = set()
        return ctx

    def entry(self, i, ctx, day):
        if not ctx['ready'] or day.bars['minute'][i] <= ctx['p']['range_end']:
            return 0
        close = day.bars['close'][i]
        if close > ctx['high'] and 1 not in ctx['used']:
            ctx['used'].add(1)
            return 1
        if close < ctx['low'] and -1 not in ctx['used']:
            ctx['used'].add(-1)
            return -1
        return 0

    def entry_reason(self, i, ctx, day, side):
        return f"突破开盘区间{'高点' if side > 0 else '低点'} {ctx['high'] if side > 0 else ctx['low']:.2f}"

    def exit(self, i, ctx, day, trip):
        close = day.bars['close'][i]
        side = trip['entry'].side
        if (side > 0 and close < ctx['mid']) or (side < 0 and close > ctx['mid']):
            return '止损（回到区间中点）'
        target = ctx['p']['target_x']
        if target:
            width = ctx['high'] - ctx['low']
            entry = trip['entry'].avg()
            if (side > 0 and close >= entry + target * width) or (side < 0 and close <= entry - target * width):
                return '止盈'
        return None


class VwapReversion(Strategy):
    key = 'vwap_reversion'
    name = 'VWAP 回归'
    description = ('算当天的成交量加权均价（VWAP）和价格偏离 VWAP 的 60 分钟标准差。价格低于 VWAP 减 2 倍标准差就先买后卖，'
                   '高于 VWAP 加 2 倍标准差就先卖后买；回到 VWAP 平仓。止损用最近 20 分钟高低差的 0.5 倍（文章口诀 2）。')
    params = {'k': 2.0, 'window': 60, 'stop_atr': 0.5}
    specs = [('k', '偏离几倍标准差', 1.0, 4.0, 0.25), ('window', '标准差窗口（分钟）', 20, 120, 10),
             ('stop_atr', '止损（20 分钟高低差的倍数，0 为不设）', 0.0, 2.0, 0.25)]

    def prepare(self, day, params):
        ctx = super().prepare(day, params)
        bars = day.bars
        ctx['vwap'] = _vwap(bars)
        dev = bars['close'] - ctx['vwap']
        w = int(ctx['p']['window'])
        n = len(dev)
        sd = np.full(n, np.nan)
        if n >= w > 1:  # rolling std over the last w bars, like pandas .rolling(w).std()
            sd[w - 1:] = sliding_window_view(dev, w).std(axis=1, ddof=1)  # NaN inside a window stays NaN
        ctx['sd'] = sd
        hi = np.full(n, np.nan)
        lo = np.full(n, np.nan)
        if n >= 20:
            hi[19:] = np.nanmax(sliding_window_view(bars['high'], 20), axis=1)
            lo[19:] = np.nanmin(sliding_window_view(bars['low'], 20), axis=1)
        ctx['range20'] = hi - lo
        return ctx

    def entry(self, i, ctx, day):
        sd = ctx['sd'][i]
        if not np.isfinite(sd) or sd <= 0:
            return 0
        close, vwap, k = day.bars['close'][i], ctx['vwap'][i], ctx['p']['k']
        if close < vwap - k * sd:
            return 1
        if close > vwap + k * sd:
            return -1
        return 0

    def entry_reason(self, i, ctx, day, side):
        return f"偏离 VWAP {day.bars['close'][i] - ctx['vwap'][i]:+.3f} 元（{ctx['p']['k']} 倍标准差 {ctx['sd'][i]:.3f}）"

    def exit(self, i, ctx, day, trip):
        close, vwap = day.bars['close'][i], ctx['vwap'][i]
        side = trip['entry'].side
        if (side > 0 and close >= vwap) or (side < 0 and close <= vwap):
            return '回到 VWAP'
        stop = ctx['p']['stop_atr']
        if stop:
            if 'stop' not in trip:
                width = ctx['range20'][i]
                trip['stop'] = stop * width if np.isfinite(width) else None
            distance = trip['stop']
            entry = trip['entry'].avg()
            if distance and ((side > 0 and close < entry - distance) or (side < 0 and close > entry + distance)):
                return '止损'
        return None


class LateMomentum(Strategy):
    key = 'late_momentum'
    name = '尾盘动量'
    description = ('14:30 看下午的涨跌：比 13:00 后第一笔价格涨超 1% 且 14:00–14:30 成交量比上午平均每半小时放大，就先买后卖；'
                   '跌超 1% 且放量，就先卖后买。收盘前（14:56）平仓，也可以设止损。')
    params = {'at': '14:30', 'move_pct': 1.0, 'volume_ratio': 1.2, 'stop_pct': 0.0, 'close_at': '14:56'}
    specs = [('move_pct', '下午涨跌幅门槛（%）', 0.3, 3.0, 0.1), ('volume_ratio', '放量倍数', 1.0, 3.0, 0.1),
             ('stop_pct', '止损（%，0 为不设）', 0.0, 3.0, 0.25)]

    def prepare(self, day, params):
        ctx = super().prepare(day, params)
        bars, minutes = day.bars, day.bars['minute']
        afternoon = np.flatnonzero(minutes > '13:00')
        ctx['pm_open'] = float(bars['open'][afternoon[0]]) if len(afternoon) else None
        vol = np.nan_to_num(bars['volume'])
        last30 = vol[(minutes > '14:00') & (minutes <= '14:30')].sum()
        morning = vol[(minutes > '09:30') & (minutes <= '11:30')].sum() / 4
        ctx['vol_ratio'] = last30 / morning if morning > 0 else None
        ctx['done'] = False
        return ctx

    def entry(self, i, ctx, day):
        minute = day.bars['minute'][i]
        if ctx['done'] or minute < ctx['p']['at'] or ctx['pm_open'] is None or ctx['vol_ratio'] is None:
            return 0
        ctx['done'] = True  # one decision at 14:30
        move = day.bars['close'][i] / ctx['pm_open'] - 1
        if ctx['vol_ratio'] < ctx['p']['volume_ratio']:
            return 0
        if move > ctx['p']['move_pct'] / 100:
            return 1
        if move < -ctx['p']['move_pct'] / 100:
            return -1
        return 0

    def entry_reason(self, i, ctx, day, side):
        move = day.bars['close'][i] / ctx['pm_open'] - 1
        return f"下午 {move * 100:+.2f}%，14:00–14:30 成交量是上午每半小时的 {ctx['vol_ratio']:.1f} 倍"

    def exit(self, i, ctx, day, trip):
        if day.bars['minute'][i] >= ctx['p']['close_at']:
            return '收盘前平仓'
        if _price_stop(trip, day.bars['close'][i], ctx['p']['stop_pct']):
            return '止损'
        return None


def _session_state(day, i):
    """Intraday facts at bar i using bars from 09:30 on (the 09:25 auction only gives the open)."""
    bars, minutes = day.bars, day.bars['minute']
    live = minutes >= '09:30'
    upto = live & (np.arange(len(minutes)) <= i)
    volume = np.nan_to_num(bars['volume'][upto])
    amount = np.nan_to_num(bars['amount'][upto])
    buy = np.nan_to_num(bars['buy_volume'][upto]).sum()
    sell = np.nan_to_num(bars['sell_volume'][upto]).sum()
    auction = np.flatnonzero(~live)
    first_live = np.flatnonzero(live)
    first_open = float(bars['open'][auction[0]]) if len(auction) else float(bars['open'][first_live[0]])
    high = float(np.nanmax(bars['high'][upto])) if upto.any() else np.nan
    low = float(np.nanmin(bars['low'][upto])) if upto.any() else np.nan
    close = float(bars['close'][i])
    return {'close': close, 'first_open': first_open,
            'vwap': float(amount.sum() / volume.sum()) if volume.sum() > 0 else close,
            'imbalance': float((buy - sell) / (buy + sell)) if buy + sell > 0 else 0.0,
            'range_pos': (close - low) / (high - low) if high > low else 0.5}


def _market_at(day, i):
    market = getattr(day, 'market', None)
    if market is None:
        return None
    value = float(market[i])
    return None if value != value else value


def _can_sell(day, close):
    return day.limit_down is None or close > day.limit_down + 0.011


class WeakClose(Strategy):
    key = 'weak_close'
    name = '尾盘弱势（研究所得）'
    description = ('牛牛在训练期（2019–2022）筛出的规律：下午走弱的股票，在大盘也弱时，尾盘大多继续走弱。14:00 时个股比昨收跌 3% 以上，'
                   '且这 16 只股票平均跌 1% 以上，就先卖一部分底仓，收盘集合竞价买回（集合竞价不用付买卖价差）。只做先卖后买；'
                   '股价低于 8 元不做（1 个价位的成本太高）。大盘用 16 只股票的等权平均代替。')
    params = {'at': '14:00', 'stock_drop_pct': 3.0, 'market_drop_pct': 1.0, 'min_price': 8.0}
    specs = [('stock_drop_pct', '个股比昨收跌幅至少（%）', 1.0, 8.0, 0.5),
             ('market_drop_pct', '16 只平均跌幅至少（%）', 0.0, 4.0, 0.25),
             ('min_price', '最低股价（元）', 0.0, 50.0, 1.0)]

    def prepare(self, day, params):
        ctx = super().prepare(day, params)
        ctx['done'] = False
        return ctx

    def entry(self, i, ctx, day):
        p = ctx['p']
        if ctx['done'] or day.bars['minute'][i] < p['at']:
            return 0
        ctx['done'] = True  # one look, at the first bar from 14:00 on
        close = float(day.bars['close'][i])
        market = _market_at(day, i)
        if day.prev_close < p['min_price'] or market is None or not _can_sell(day, close):
            return 0
        if close / day.prev_close - 1 <= -p['stock_drop_pct'] / 100 and market <= -p['market_drop_pct'] / 100:
            ctx['why'] = (close / day.prev_close - 1, market)
            return -1
        return 0

    def entry_reason(self, i, ctx, day, side):
        stock, market = ctx['why']
        return f'14:00 个股 {stock * 100:+.2f}%，16 只平均 {market * 100:+.2f}%'


class CloseScore(Strategy):
    """Linear score fitted on the training period only (2019-05-29..2022-12-31, 16 stocks, price >= 8,
    ridge with lambda = 0.01 n on standardised features) for the return from 14:00 to the close, in bp."""
    key = 'close_score'
    name = '尾盘打分（研究所得）'
    description = ('14:00 用 7 个指标给“到收盘还会涨跌多少”打分：比昨收涨跌、比开盘涨跌、偏离当天均价、主动买卖差、在当天高低点中的位置、'
                   '16 只股票平均涨跌、开盘跳空。系数只用训练期（2019–2022）拟合、之后固定。预计跌幅超过门槛就先卖后买，收盘集合竞价买回。'
                   '预计上涨的一侧在训练期扣费后没有收益，所以不做先买后卖。')
    params = {'at': '14:00', 'threshold_bp': 20.0, 'min_price': 8.0}
    specs = [('threshold_bp', '预计跌幅门槛（基点）', 5.0, 60.0, 5.0), ('min_price', '最低股价（元）', 0.0, 50.0, 1.0)]
    FEATURES = ('ret_pc', 'ret_open', 'vwap_dev', 'imbalance', 'range_pos', 'market', 'gap')
    MEAN = (-0.00020936154006856377, 0.00047018212283560365, -0.0008987307405341468, -0.035300052200572876,
            0.4551696340545929, 0.0003930853202376636, -0.000644687989003311)
    STD = (0.02545661612631969, 0.023764018402734042, 0.01069242594288529, 0.14084845269383875,
           0.28017536833018497, 0.013864537669053878, 0.012374582173443685)
    WEIGHT = (1.5753797996814225, 3.442199907816161, -12.446773996595415, -4.6388324890047326,
              10.147385390473394, 10.069913712692225, -0.39707383619149506)
    BIAS = -2.3173054595527423

    def score(self, day, i):
        market = _market_at(day, i)
        if market is None:
            return None
        s = _session_state(day, i)
        close = s['close']
        values = (close / day.prev_close - 1, close / s['first_open'] - 1, close / s['vwap'] - 1, s['imbalance'],
                  s['range_pos'], market, s['first_open'] / day.prev_close - 1)
        return self.BIAS + sum(w * (v - m) / d for v, m, d, w in zip(values, self.MEAN, self.STD, self.WEIGHT))

    def prepare(self, day, params):
        ctx = super().prepare(day, params)
        ctx['done'] = False
        return ctx

    def entry(self, i, ctx, day):
        p = ctx['p']
        if ctx['done'] or day.bars['minute'][i] < p['at']:
            return 0
        ctx['done'] = True
        close = float(day.bars['close'][i])
        if day.prev_close < p['min_price'] or not _can_sell(day, close):
            return 0
        score = self.score(day, i)
        if score is not None and score <= -p['threshold_bp']:
            ctx['score'] = score
            return -1
        return 0

    def entry_reason(self, i, ctx, day, side):
        return f"14:00 打分预计到收盘 {ctx['score']:+.0f} 个基点"


SLOTS = tuple([f'{h:02d}:{m:02d}' for h, a, b in ((9, 31, 59), (10, 0, 59), (11, 0, 30), (13, 1, 59), (14, 0, 59))
               for m in range(a, b + 1)] + ['15:00'])
_SLOT_INDEX = {m: i for i, m in enumerate(SLOTS)}


def slot_grid(day):
    """The day's bars on the 240 continuous-session minute slots (09:31..11:30, 13:01..15:00), the way
    the research grid was built: prices carried forward (starting from the day's first price), volumes
    zero in minutes without trades, high/low falling back to the carried price."""
    bars = day.bars
    n = len(SLOTS)
    minutes = np.asarray(bars['minute'])
    index = np.array([_SLOT_INDEX.get(m, -1) for m in minutes], dtype=int)
    keep = index >= 0
    at = index[keep]
    auction = np.flatnonzero(minutes < '09:30')
    live = np.flatnonzero(minutes >= '09:30')
    first = auction[0] if len(auction) else (live[0] if len(live) else None)
    first_open = float(bars['open'][first]) if first is not None else np.nan
    close = np.full(n, np.nan)
    high = np.full(n, np.nan)
    low = np.full(n, np.nan)
    volume, amount, buy, sell = (np.zeros(n) for _ in range(4))
    close[at], high[at], low[at] = bars['close'][keep], bars['high'][keep], bars['low'][keep]
    volume[at] = np.nan_to_num(bars['volume'][keep])
    amount[at] = np.nan_to_num(bars['amount'][keep])
    buy[at] = np.nan_to_num(bars['buy_volume'][keep])
    sell[at] = np.nan_to_num(bars['sell_volume'][keep])
    if np.isnan(close[0]):
        close[0] = first_open
    filled = np.where(np.isnan(close), 0, np.arange(n))  # carry the last traded price forward
    close = close[np.maximum.accumulate(filled)]
    high = np.where(np.isnan(high), close, high)
    low = np.where(np.isnan(low), close, low)
    cum_v, cum_a = np.cumsum(volume), np.cumsum(amount)
    return {'close': close, 'hi': np.maximum.accumulate(high), 'lo': np.minimum.accumulate(low),
            'vwap': np.where(cum_v > 0, cum_a / np.maximum(cum_v, 1), close),
            'cum_buy': np.cumsum(buy), 'cum_sell': np.cumsum(sell), 'first_open': first_open}


class IntradayScore(Strategy):
    """Ridge models, one per decision time, for the return from the next minute's open to the close.
    Fitted on the training period only (2019-05-29..2022-12-31, 16 stocks, price >= 8, lambda = 0.01 n,
    standardised features) and then fixed; scripts/research/gst_intraday_t0/ridge_multi.py reproduces them."""
    key = 'intraday_score'
    name = '全天打分（研究所得）'
    description = ('在 10:00、10:30、13:30、14:00、14:30 各打一次分，预测“从下一分钟到收盘”的涨跌。用 10 个指标：比昨收涨跌、比开盘涨跌、'
                   '近 30 分钟涨跌、偏离当天均价、主动买卖差、在当天高低点中的位置、16 只股票平均比昨收和比开盘的涨跌、个股和 16 只平均的开盘跳空。'
                   '系数只用训练期（2019–2022）拟合后固定。当天第一次预计跌幅超过门槛就先卖一部分底仓，收盘集合竞价买回；每天最多一次。'
                   '预计上涨的一侧在验证中不赚钱，所以不做先买后卖。股价低于 8 元不做。')
    params = {'threshold_bp': 20.0, 'min_price': 8.0}
    specs = [('threshold_bp', '预计跌幅门槛（基点）', 5.0, 80.0, 5.0), ('min_price', '最低股价（元）', 0.0, 50.0, 1.0)]
    FEATURES = ('ret_pc', 'ret_open', 'ret_30', 'vwap_dev', 'imbalance', 'range_pos', 'market', 'market_open', 'gap',
                'market_gap')
    MODELS = {
        '10:00': {'mu': [-0.0002247460698, 0.0004411358254, 0.0004860595249, -0.0002538864243, -0.03317034492, 0.4712439061, -2.979508228e-05, 0.0007096484429, -0.0006368459315, -0.000711085213], 'sd': [0.01948235646, 0.016821736, 0.01460769832, 0.00752101161, 0.1729058808, 0.2938505576, 0.009555530101, 0.007395831872, 0.01242391059, 0.007544671203], 'w': [5.963748257, -1.020338321, 2.894457248, -20.19773628, -4.507582983, 11.31881715, 7.936008364, 11.71123702, -1.79488618, -5.66693303], 'b': 2.500339594},
        '10:30': {'mu': [-0.0003605358826, 0.0003001468589, -0.0001535336202, -0.0005882103625, -0.03557800094, 0.4627124021, -5.537210124e-05, 0.0006757906266, -0.0006319209856, -0.0007039683176], 'sd': [0.02165424371, 0.01932494181, 0.009844158101, 0.008431526142, 0.1582170963, 0.2879190725, 0.01082924426, 0.008987574526, 0.01237439197, 0.007473092927], 'w': [3.944891092, -2.112737606, -1.114566822, -7.03481039, -3.469113315, 6.47736008, 8.353297985, 11.03071474, -0.5740723145, -5.655242761], 'b': 3.818797011},
        '13:30': {'mu': [-0.0002296669455, 0.0004515550079, -0.0002411475243, -0.0008203227023, -0.03513361234, 0.4547184903, 0.0003610067645, 0.00109803067, -0.0006503411971, -0.000706946528], 'sd': [0.02477562436, 0.02286695854, 0.008946708888, 0.01052960873, 0.1449206356, 0.2821609684, 0.01341904703, 0.01199696836, 0.01236591451, 0.007442392105], 'w': [5.86460069, 4.240335928, 2.05204765, -17.96318043, -4.69473736, 7.143923092, 3.958998536, 8.085528933, 0.5160276644, -4.788175839], 'b': -1.230714096},
        '14:00': {'mu': [-0.0002093615401, 0.0004701821228, 5.730927311e-05, -0.0008987307405, -0.0353000522, 0.4551696341, 0.0003930853202, 0.001131886632, -0.000644687989, -0.0007050568286], 'sd': [0.02545661613, 0.0237640184, 0.007008143564, 0.01069242594, 0.1408484527, 0.2801753683, 0.01386453767, 0.01277197318, 0.01237458217, 0.007434096064], 'w': [2.197373015, 2.243535603, 0.4650783047, -12.94194971, -4.553494555, 10.06372379, 4.430246745, 6.718794575, 1.293098462, -0.2117861357], 'b': -2.244624134},
        '14:30': {'mu': [-0.0005005971047, 0.000195261744, -0.000174130216, -0.00108810827, -0.0355990226, 0.4535050655, 0.0002106993813, 0.0009391847524, -0.0006613609903, -0.000696699744], 'sd': [0.02609999038, 0.02453354483, 0.00672098254, 0.01081427007, 0.1377094669, 0.2806439981, 0.01459597697, 0.01355699523, 0.01223396067, 0.007361456525], 'w': [-0.4629788649, -0.1891624916, -2.739047735, -3.733268281, -2.329651241, 4.938778471, 4.689804459, 5.532385799, 0.1953352645, -0.1063695864], 'b': -0.6417086135},
    }

    def features(self, day, grid, at):
        """The 10 features at decision slot `at` (only data up to that minute), or None."""
        context = getattr(day, 'context', None)
        if context is None or context.get('gap') is None:
            return None
        from quantlab.intraday.gst import market_asof
        i = _SLOT_INDEX[at]
        p = grid['close'][i]
        back = grid['close'][max(0, i - 30)]
        buy, sell = grid['cum_buy'][i], grid['cum_sell'][i]
        hi, lo = grid['hi'][i], grid['lo'][i]
        market = float(market_asof(context, [at])[0])
        market_open = float(market_asof(context, [at], 'ret_open')[0])
        if market != market or market_open != market_open:
            return None
        return (p / day.prev_close - 1, p / grid['first_open'] - 1, p / back - 1, p / grid['vwap'][i] - 1,
                (buy - sell) / (buy + sell) if buy + sell > 0 else 0.0,
                (p - lo) / (hi - lo) if hi > lo else 0.5, market, market_open,
                grid['first_open'] / day.prev_close - 1, float(context['gap']))

    def score(self, day, grid, at, models=None):
        models = self.MODELS if models is None else models
        if at not in models:
            return None
        values = self.features(day, grid, at)
        if values is None:
            return None
        m = models[at]
        return m['b'] + sum(w * (v - mu) / sd for v, mu, sd, w in zip(values, m['mu'], m['sd'], m['w']))

    def prepare(self, day, params):
        ctx = super().prepare(day, params)
        ctx['grid'] = slot_grid(day)
        ctx['pending_times'] = sorted(self.MODELS)
        ctx['taken'] = False
        return ctx

    def entry(self, i, ctx, day):
        p = ctx['p']
        minute = day.bars['minute'][i]
        if ctx['taken'] or day.prev_close < p['min_price']:
            return 0
        while ctx['pending_times'] and ctx['pending_times'][0] <= minute:
            at = ctx['pending_times'].pop(0)
            price = ctx['grid']['close'][_SLOT_INDEX[at]]
            if not _can_sell(day, price) or (day.limit_up is not None and price >= day.limit_up - 0.011):
                continue
            score = self.score(day, ctx['grid'], at, ctx.get('models'))
            if score is not None and score <= -p['threshold_bp']:
                ctx['taken'] = True
                ctx['why'] = (at, score)
                return -1
        return 0

    def entry_reason(self, i, ctx, day, side):
        at, score = ctx['why']
        return f'{at} 打分预计到收盘 {score:+.0f} 个基点'


class MorningScore(IntradayScore):
    """The IntradayScore features at 10:00 and 10:30 only, with walk-forward models: each year is traded
    with coefficients fitted only on earlier years (quantlab.intraday.morning_models)."""
    key = 'morning_score'
    name = '上午打分（研究所得，逐年滚动）'
    description = ('10:00 和 10:30 各打一次分，预测“从下一分钟到收盘”的涨跌（10 个指标同“全天打分”）。每年用之前所有年份的数据重新拟合系数，'
                   '当年只用这组固定系数，所以回测里的每一年都相当于没见过的数据；2019–2020 历史不够，不交易。'
                   '预计跌幅超过门槛就先卖一部分底仓，收盘集合竞价买回；每天最多一次；只做先卖后买；股价低于 8 元不做。'
                   '研究中发现下午的打分、止损、止盈都会降低收益，所以没有加入。')

    def models_for(self, day):
        from quantlab.intraday.morning_models import MODELS
        years = sorted(MODELS)
        year = str(day.date.year)
        if year < years[0]:
            return None
        return MODELS[year] if year in MODELS else MODELS[years[-1]]

    def prepare(self, day, params):
        ctx = super().prepare(day, params)
        ctx['models'] = self.models_for(day) or {}
        ctx['pending_times'] = sorted(ctx['models'])
        return ctx


class RangeBreakout(Strategy):
    """Opening-range trend breakout with optional market and volume confirmation (research control)."""
    key = 'range_breakout'
    name = '趋势突破（开盘区间，可调）'
    description = ('记下开盘后 N 分钟的最高价和最低价。之后到 14:00 前，1 分钟收盘价第一次跌破最低价就先卖后买（方向设为 −1 或 0 时），'
                   '第一次突破最高价就先买后卖（方向设为 1 或 0 时）。可要求 16 只股票平均同向涨跌超过一定幅度（大盘确认），以及突破那一分钟的'
                   '成交量是昨天平均每分钟的若干倍（放量确认）。默认在收盘集合竞价平仓，也可设跟踪止损。默认参数是训练期（2019–2022）里'
                   '最好的一组：30 分钟区间向下突破 + 16 只平均跌 ≥1% + 放量 3 倍；训练期每笔扣费后约 +18 bp，但 2023–2024 只有 +10 bp、'
                   't≈0.7，不能算有效。')
    params = {'range_minutes': 30, 'direction': -1, 'market_pct': 1.0, 'volume_x': 3.0, 'trail_pct': 0.0, 'min_price': 8.0}
    specs = [('range_minutes', '开盘区间（分钟）', 5, 60, 5), ('direction', '方向（1 只做突破向上，−1 只做跌破向下，0 都做）', -1, 1, 1),
             ('market_pct', '16 只平均同向涨跌至少（%，0 为不要求）', 0.0, 3.0, 0.25),
             ('volume_x', '突破分钟成交量 ≥ 昨日平均每分钟的倍数（0 为不要求）', 0.0, 10.0, 0.5),
             ('trail_pct', '跟踪止损（%，0 为拿到收盘集合竞价）', 0.0, 5.0, 0.5), ('min_price', '最低股价（元）', 0.0, 50.0, 1.0)]

    def prepare(self, day, params):
        ctx = super().prepare(day, params)
        p = ctx['p']
        grid = slot_grid(day)
        k = int(p['range_minutes'])
        ctx['range_end'] = SLOTS[k - 1]
        ctx['high'] = float(grid['hi'][k - 1])
        ctx['low'] = float(grid['lo'][k - 1])
        ctx['grid'] = grid
        ctx['used'] = set()
        ctx['minute_volume'] = day.prev_volume / len(SLOTS) if getattr(day, 'prev_volume', None) else None
        return ctx

    def entry(self, i, ctx, day):
        p = ctx['p']
        minute = day.bars['minute'][i]
        if minute <= ctx['range_end'] or minute > '14:00' or day.prev_close < p['min_price']:
            return 0
        slot = _SLOT_INDEX.get(minute)
        if slot is None or slot == 0:
            return 0
        close, before = ctx['grid']['close'][slot], ctx['grid']['close'][slot - 1]
        direction = int(p['direction'])
        for side, level in ((1, ctx['high']), (-1, ctx['low'])):
            if side in ctx['used'] or (direction and side != direction):
                continue
            crossed = (before <= level < close) if side > 0 else (before >= level > close)
            if not crossed:
                continue
            ctx['used'].add(side)  # only the first break in each direction counts
            if p['market_pct']:
                market = _market_at(day, i)
                if market is None or side * market <= p['market_pct'] / 100:
                    continue
            if p['volume_x']:
                volume = float(np.nan_to_num(day.bars['volume'][i]))
                if not ctx['minute_volume'] or volume < p['volume_x'] * ctx['minute_volume']:
                    continue
            ctx['why'] = (side, level)
            return side
        return 0

    def entry_reason(self, i, ctx, day, side):
        return f"{'突破' if side > 0 else '跌破'}开盘 {int(ctx['p']['range_minutes'])} 分钟区间 {ctx['why'][1]:.2f}"

    def exit(self, i, ctx, day, trip):
        trail = ctx['p']['trail_pct']
        if not trail:
            return None
        close = float(day.bars['close'][i])
        side = trip['entry'].side
        best = trip.get('best', trip['entry'].avg())
        best = max(best, close) if side > 0 else min(best, close)
        trip['best'] = best
        if (side > 0 and close <= best * (1 - trail / 100)) or (side < 0 and close >= best * (1 + trail / 100)):
            return '跟踪止损'
        return None


class GapRebound(Strategy):
    key = 'gap_rebound'
    name = '低开回补（研究所得）'
    description = ('训练期（2019–2022）里，开盘集合竞价比昨收低 2% 以上的股票，开盘后到收盘平均回升。按 09:25 集合竞价价格判断，'
                   '低开达到门槛就在开盘第一笔（加 1 个价位）先多买一些，收盘集合竞价卖出同样数量的旧股（先买后卖，不违反 T+1）。'
                   '接近涨跌停不做。')
    params = {'gap_pct': 2.0, 'min_price': 0.0}
    specs = [('gap_pct', '低开幅度至少（%）', 0.5, 8.0, 0.5), ('min_price', '最低股价（元）', 0.0, 50.0, 1.0)]

    def prepare(self, day, params):
        ctx = super().prepare(day, params)
        ctx['done'] = False
        return ctx

    def entry(self, i, ctx, day):
        p = ctx['p']
        if ctx['done']:
            return 0
        ctx['done'] = True  # only the opening auction bar decides
        if day.bars['minute'][i] >= '09:30' or day.prev_close < p['min_price']:
            return 0
        price = float(day.bars['open'][i])
        if day.limit_down is not None and price <= day.limit_down + 0.011:
            return 0
        if day.limit_up is not None and price >= day.limit_up - 0.011:
            return 0
        gap = price / day.prev_close - 1
        if gap <= -p['gap_pct'] / 100:
            ctx['gap'] = gap
            return 1
        return 0

    def entry_reason(self, i, ctx, day, side):
        return f"集合竞价低开 {ctx['gap'] * 100:+.2f}%"


STRATEGIES = {s.key: s for s in (MorningScore(), IntradayScore(), RangeBreakout(), GapRebound(), WeakClose(), CloseScore(), OpeningBreakout(), VwapReversion(), LateMomentum())}
# 尾盘动量 decides at 14:30 and closes at 14:56, so it needs its own trading window and close time.
_AUCTION = {'windows': (('14:00', '14:10'),), 'force_close': '14:11', 'close_in_auction': True}
STRATEGY_CONFIG = {'late_momentum': {'windows': (('14:30', '14:45'),), 'force_close': '14:56'},
                   'weak_close': _AUCTION, 'close_score': _AUCTION,
                   'gap_rebound': {'windows': (('09:25', '09:25'),), 'force_close': '09:31', 'close_in_auction': True},
                   'range_breakout': {'windows': (('09:36', '14:00'),), 'force_close': '14:30', 'close_in_auction': True},
                   'morning_score': {'windows': (('10:00', '11:00'),), 'force_close': '11:05', 'close_in_auction': True},
                   'intraday_score': {'windows': (('10:00', '11:30'), ('13:30', '14:35')), 'force_close': '14:40',
                                      'close_in_auction': True}}

__all__ = ['Strategy', 'STRATEGIES', 'STRATEGY_CONFIG', 'MorningScore', 'IntradayScore', 'RangeBreakout', 'GapRebound', 'WeakClose', 'CloseScore', 'slot_grid', 'OpeningBreakout', 'VwapReversion',
           'LateMomentum']
