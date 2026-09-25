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


STRATEGIES = {s.key: s for s in (WeakClose(), CloseScore(), OpeningBreakout(), VwapReversion(), LateMomentum())}
# 尾盘动量 decides at 14:30 and closes at 14:56, so it needs its own trading window and close time.
_AUCTION = {'windows': (('14:00', '14:10'),), 'force_close': '14:11', 'close_in_auction': True}
STRATEGY_CONFIG = {'late_momentum': {'windows': (('14:30', '14:45'),), 'force_close': '14:56'},
                   'weak_close': _AUCTION, 'close_score': _AUCTION}

__all__ = ['Strategy', 'STRATEGIES', 'STRATEGY_CONFIG', 'WeakClose', 'CloseScore', 'OpeningBreakout', 'VwapReversion',
           'LateMomentum']
