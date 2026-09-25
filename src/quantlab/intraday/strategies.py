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


STRATEGIES = {s.key: s for s in (OpeningBreakout(), VwapReversion(), LateMomentum())}
# 尾盘动量 decides at 14:30 and closes at 14:56, so it needs its own trading window and close time.
STRATEGY_CONFIG = {'late_momentum': {'windows': (('14:30', '14:45'),), 'force_close': '14:56'}}

__all__ = ['Strategy', 'STRATEGIES', 'STRATEGY_CONFIG', 'OpeningBreakout', 'VwapReversion', 'LateMomentum']
