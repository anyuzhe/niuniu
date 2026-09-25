"""底仓做T backtest on 1-minute bars.

The account holds a base position overnight (base_value yuan at the previous close,
rounded down to 100 shares). During the day a strategy either
- sells part of the base first and buys it back later (先卖后买), or
- buys extra shares first and sells the same number of base shares later (先买后卖),
so every round trip closes the same day and the position is back to the base at the
close. Shares bought today are never sold today (T+1): the sell leg always uses base
shares held from the previous day.

Execution model (deliberately simple and conservative):
- a signal is evaluated on a completed 1-minute bar and filled on the NEXT bar at its
  open, moved against us by `slippage`; the 09:25 auction bar is never traded;
- at most `participation` of the fill bar's volume, in 100-share lots; an entry order
  gives up after 3 bars, an exit order keeps trying;
- a buy is impossible in a minute that traded entirely at the limit-up price, a sell in
  a minute that traded entirely at the limit-down price;
- from `force_close` on, open trips are closed; what is still open at the last bar is
  closed in the closing auction at the close (15:00 bar) unless the close is at the limit
  against us; anything left is marked at the close and reported as unfinished;
- fees per order: commission (with minimum), stamp duty on sells (0.1 %, 0.05 % from
  2023-08-28), transfer fee both sides.
Profit is measured against simply holding the base: sell price minus buy price, less fees.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np

STAMP_CHANGE = date(2023, 8, 28)
LOT = 100
ENTRY_PATIENCE = 3


@dataclass
class Costs:
    commission: float = 0.00025
    commission_min: float = 5.0
    stamp_before: float = 0.001
    stamp_after: float = 0.0005
    transfer: float = 0.00001
    slippage: float = 0.001

    def stamp(self, day: date) -> float:
        return self.stamp_after if day >= STAMP_CHANGE else self.stamp_before


@dataclass
class T0Config:
    base_value: float = 100_000.0
    trade_fraction: float = 0.5
    participation: float = 0.2
    max_trips: int = 20
    daily_loss_limit: float = 0.01
    force_close: str = '14:50'
    windows: tuple = (('09:35', '11:00'), ('13:30', '14:50'))
    costs: Costs = field(default_factory=Costs)

    def to_dict(self):
        value = asdict(self)
        value['windows'] = [list(w) for w in self.windows]
        return value

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        costs = Costs(**value.pop('costs', {}))
        if 'windows' in value:
            value['windows'] = tuple(tuple(w) for w in value['windows'])
        return cls(costs=costs, **value)


def _fees(costs: Costs, day: date, side: int, amount: float) -> float:
    if amount <= 0:
        return 0.0
    fee = max(costs.commission_min, costs.commission * amount) + costs.transfer * amount
    if side < 0:
        fee += costs.stamp(day) * amount
    return fee


def _in_windows(minute: str, windows) -> bool:
    return any(a <= minute <= b for a, b in windows)


class _Order:
    __slots__ = ('kind', 'side', 'qty', 'placed', 'fills', 'reason')

    def __init__(self, kind, side, qty, placed, reason):
        self.kind, self.side, self.qty, self.placed, self.reason = kind, side, qty, placed, reason
        self.fills = []

    @property
    def filled(self):
        return sum(f[1] for f in self.fills)

    def avg(self):
        qty = self.filled
        return sum(f[0] * f[1] for f in self.fills) / qty if qty else None

    def raw_avg(self):
        qty = self.filled
        return sum(f[3] * f[1] for f in self.fills) / qty if qty else None


def run_day(day, strategy, params, config: T0Config):
    """Backtest one Day. Returns (day_record, trips)."""
    bars = day.bars
    minutes, opens, highs, lows, closes, volumes = (bars['minute'], bars['open'], bars['high'], bars['low'],
                                                    bars['close'], bars['volume'])
    n = len(minutes)
    base_shares = int(config.base_value / day.prev_close / LOT) * LOT if day.prev_close > 0 else 0
    record = {'symbol': day.symbol, 'date': day.date.isoformat(), 'prev_close': day.prev_close,
              'close': float(closes[-1]) if n else None, 'base_shares': base_shares,
              'base_value': base_shares * day.prev_close, 'trips': 0, 'pnl': 0.0, 'fees': 0.0, 'bps': 0.0,
              'unfinished': 0, 'limit_rule': day.limit_reason}
    if n == 0 or base_shares < LOT:
        record['skipped'] = '底仓不足 100 股' if n else '没有分钟数据'
        return record, []
    trade_qty = max(LOT, int(base_shares * config.trade_fraction / LOT) * LOT)
    ctx = strategy.prepare(day, params)
    up, down = day.limit_up, day.limit_down
    costs = config.costs
    trips, trip, pending = [], None, None
    day_pnl, stopped = 0.0, False
    last = n - 1
    auction_close = minutes[last] == '15:00'

    def blocked(side, i):
        if side > 0 and up is not None and lows[i] >= up - 0.005:
            return True
        if side < 0 and down is not None and highs[i] <= down + 0.005:
            return True
        return False

    def fill(order, i, price=None):
        if blocked(order.side, i):
            return 0
        cap = int(config.participation * volumes[i] / LOT) * LOT
        qty = min(order.qty - order.filled, cap)
        if qty <= 0:
            return 0
        raw = float(price if price is not None else opens[i])
        if price is None:
            price = opens[i] * (1 + costs.slippage * order.side)
            if order.side > 0 and up is not None:
                price = min(price, up)
            if order.side < 0 and down is not None:
                price = max(price, down)
        order.fills.append((float(price), qty, minutes[i], raw))
        return qty

    def finish(trip, reason, exit_price=None, exit_minute=None):
        nonlocal day_pnl
        entry, exit_ = trip['entry'], trip['exit']
        qty = entry.filled
        entry_px = entry.avg()
        done = exit_.filled if exit_ is not None else 0
        if exit_price is None:
            exit_px = exit_.avg()
        else:  # partly or not closed: the rest is valued at `exit_price`
            exit_px = ((exit_.avg() * done if done else 0.0) + exit_price * (qty - done)) / qty
        side = entry.side
        sell_px, buy_px = (entry_px, exit_px) if side < 0 else (exit_px, entry_px)
        fees = _fees(costs, day.date, side, entry_px * qty)
        if exit_ is not None and exit_.filled:
            fees += _fees(costs, day.date, -side, exit_.avg() * exit_.filled)
        gross = (sell_px - buy_px) * qty
        # the same trip at the prices seen, before slippage and fees: what the signal itself earned
        raw_entry = entry.raw_avg()
        raw_exit = exit_.raw_avg() if exit_ is not None and exit_.filled else None
        raw_exit = ((raw_exit * done if done else 0.0) + (exit_price or 0.0) * (qty - done)) / qty \
            if exit_price is not None else raw_exit
        raw = (raw_entry - raw_exit) * qty * (1 if side < 0 else -1)
        pnl = gross - fees
        day_pnl += pnl
        trips.append({'symbol': day.symbol, 'date': day.date.isoformat(),
                      'direction': '先卖后买' if side < 0 else '先买后卖', 'qty': qty,
                      'entry_minute': entry.fills[0][2], 'entry_price': round(entry_px, 4),
                      'exit_minute': exit_minute or (exit_.fills[-1][2] if exit_ is not None and exit_.fills else None),
                      'exit_price': round(exit_px, 4), 'reason': reason, 'gross': round(gross, 2),
                      'raw_bps': round(raw / (raw_entry * qty) * 1e4, 2),
                      'fees': round(fees, 2), 'pnl': round(pnl, 2),
                      'bps': round(pnl / (entry_px * qty) * 1e4, 2)})

    for i in range(n):
        minute = minutes[i]
        if minute < '09:30':
            continue  # opening auction bar: information only
        # 1) execute the order placed on an earlier bar
        if pending is not None and pending.placed < i:
            is_auction = auction_close and i == last
            if is_auction:
                fill(pending, i, price=float(closes[i]))
            else:
                fill(pending, i)
            if pending.kind == 'entry':
                if pending.filled:
                    pending.qty = pending.filled  # the unfilled rest of an entry is cancelled
                    trip = {'entry': pending, 'exit': None, 'reason': None, 'meta': pending.reason}
                    pending = None
                elif i - pending.placed >= ENTRY_PATIENCE:
                    pending = None
            else:
                if pending.filled >= pending.qty:
                    finish(trip, trip['reason'])
                    trip, pending = None, None
                    if day_pnl <= -config.daily_loss_limit * record['base_value']:
                        stopped = True
        if i == last:
            break
        # 2) decide at the close of this bar, for the next bar
        if trip is not None and pending is None:
            reason = None
            if minute >= config.force_close:
                reason = '收盘前平仓'
            else:
                reason = strategy.exit(i, ctx, day, trip)
            if reason:
                trip['reason'] = reason
                pending = _Order('exit', -trip['entry'].side, trip['entry'].filled, i, reason)
                trip['exit'] = pending
        elif trip is None and pending is None and not stopped and len(trips) < config.max_trips \
                and minute < config.force_close and _in_windows(minute, config.windows):
            side = strategy.entry(i, ctx, day)
            if side:
                qty = trade_qty
                if side < 0:
                    qty = min(qty, base_shares)  # sell-first can only use base shares
                pending = _Order('entry', side, qty, i, strategy.entry_reason(i, ctx, day, side))

    if trip is not None:
        exit_ = trip['exit']
        if exit_ is not None and exit_.filled >= trip['entry'].filled:
            finish(trip, trip['reason'])
        else:
            record['unfinished'] += 1
            # mark the unhedged remainder at the close; this is exposure, not a completed trade
            finish(trip, '未能回补（按收盘价估值）', exit_price=float(closes[-1]), exit_minute=minutes[-1])
    record['trips'] = len(trips)
    record['pnl'] = round(day_pnl, 2)
    record['fees'] = round(sum(t['fees'] for t in trips), 2)
    record['bps'] = round(day_pnl / record['base_value'] * 1e4, 3) if record['base_value'] else 0.0
    record['stopped'] = stopped
    return record, trips


# ---------------------------------------------------------------------- statistics

def summarize(days: list[dict], trips: list[dict]) -> dict:
    """Portfolio view: each (stock, day) is one base position; the portfolio is equal weight."""
    active = [d for d in days if not d.get('skipped')]
    n = len(active)
    if not n:
        return {'days': 0}
    bps = np.array([d['bps'] for d in active], dtype=float)
    by_date = {}
    for d in active:
        by_date.setdefault(d['date'], []).append(d['bps'])
    dates = sorted(by_date)
    portfolio = np.array([np.mean(by_date[k]) for k in dates])
    curve = np.cumsum(portfolio)
    drawdown = float(np.max(np.maximum.accumulate(curve) - curve)) if len(curve) else 0.0
    sd = float(portfolio.std(ddof=1)) if len(portfolio) > 1 else 0.0
    t = float(portfolio.mean() / sd * math.sqrt(len(portfolio))) if sd > 0 else None
    pnl = [t['pnl'] for t in trips]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    gross = sum(t['gross'] for t in trips)
    fees = sum(t['fees'] for t in trips)
    return {
        'days': n, 'dates': len(dates), 'from': dates[0], 'to': dates[-1],
        'traded_days': int(sum(1 for d in active if d['trips'])), 'trips': len(trips),
        'pnl': round(sum(d['pnl'] for d in active), 2), 'gross': round(gross, 2), 'fees': round(fees, 2),
        'mean_bps_per_stock_day': round(float(bps.mean()), 3),
        'portfolio_mean_bps': round(float(portfolio.mean()), 3),
        'annual_pct': round(float(portfolio.mean()) * 250 / 100, 2),
        't_stat': None if t is None else round(t, 2),
        'max_drawdown_bps': round(drawdown, 1),
        'win_rate': round(len(wins) / len(pnl), 3) if pnl else None,
        'avg_trip_bps': round(float(np.mean([t['bps'] for t in trips])), 2) if trips else None,
        'avg_raw_bps': round(float(np.mean([t.get('raw_bps', 0.0) for t in trips])), 2) if trips else None,
        'payoff': round(float(np.mean(wins) / -np.mean(losses)), 2) if wins and losses and np.mean(losses) < 0 else None,
        'unfinished': int(sum(d['unfinished'] for d in active)),
        'curve': [{'date': k, 'bps': round(float(v), 2)} for k, v in zip(dates, curve)],
    }


def verdict(stats: dict) -> str:
    if not stats.get('days'):
        return '没有样本。'
    t = stats.get('t_stat')
    mean = stats['portfolio_mean_bps']
    if stats['trips'] < 30:
        head = '交易次数太少（不到 30 笔），不能下结论'
    elif t is not None and t >= 2 and mean > 0:
        head = '扣费后平均为正，统计上较稳定'
    elif t is not None and t <= -2:
        head = '扣费后稳定亏钱'
    else:
        head = '扣费后没有显示出稳定的正收益'
    return (f"{head}：平均每天 {mean:+.2f} 个基点（相当于底仓年化约 {stats['annual_pct']:+.1f}%），"
            f"{stats['trips']} 笔、胜率 {((stats['win_rate'] or 0) * 100):.0f}%，费用占毛利 "
            + (f"{stats['fees'] / stats['gross'] * 100:.0f}%" if stats['gross'] > 0 else '——（毛利为负）')
            + (f"，t={t:.1f}" if t is not None else '') + '。'
            + (f"不计滑点和费用时每笔平均 {stats['avg_raw_bps']:+.1f} 个基点，扣完后 {stats['avg_trip_bps']:+.1f}。"
               if stats.get('avg_raw_bps') is not None else ''))


__all__ = ['Costs', 'T0Config', 'run_day', 'summarize', 'verdict', 'STAMP_CHANGE']
