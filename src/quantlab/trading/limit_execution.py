"""Conservative daily-bar execution model for limit-board event trades (research_only).

Without Level-2 queue data the model never assumes a fill it cannot justify from daily
prices: opening at the limit-up price blocks buying, a one-word board blocks queue fills,
a sealed board only fills in the explicit optimistic scenario, and exits wait while the
price is pinned at the limit-down. T+1 holds, dated stamp tax and transfer fees apply.
A position that cannot be sold within the holding window is marked to its last close
(``UNRESOLVED_EXIT``) instead of being dropped, so blocked exits stay in the return sample;
only windows cut off by the end of the data are left pending.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math

import polars as pl

EXECUTION_VERSION = 'limit-execution-model-v1'
ENTRY_MODES = ('t1_open', 't1_close', 't0_limit_price', 't1_limit_price')
EXIT_MODES = ('next_open', 'next_close')
SCENARIOS = ('conservative', 'optimistic')
STAMP_TAX_CUT = date(2023, 8, 28)
TRANSFER_FEE_CUT = date(2022, 4, 29)
ENTERED_STATUSES = ('FILLED', 'UNRESOLVED_EXIT')
NO_FILL_STATUSES = ('NO_FILL_NOT_LISTED', 'NO_FILL_SUSPENDED', 'NO_FILL_UNMODELED', 'NO_FILL_OPEN_AT_LIMIT_UP',
                    'NO_FILL_CLOSE_AT_LIMIT_UP', 'NO_FILL_NOT_TOUCHED', 'NO_FILL_ONE_WORD', 'NO_FILL_SEALED_QUEUE_UNKNOWN')
PENDING_STATUSES = ('PENDING_ENTRY_DATA', 'PENDING_EXIT_DATA')
STATUSES = ENTERED_STATUSES + NO_FILL_STATUSES + PENDING_STATUSES
STATE_COLUMNS = ('code', 'date', '_pos', 'tradable', 'open', 'high', 'low', 'close', 'preclose', 'limit_up_price',
                 'limit_down_price', 'limit_rule_status', 'is_one_word_limit_up', 'touched_limit_up', 'is_limit_up_close')
TRADE_SCHEMA = {'date': pl.Date, 'code': pl.String, 'fill_status': pl.String, 'entry_date': pl.Date, 'entry_price': pl.Float64,
                'exit_date': pl.Date, 'exit_price': pl.Float64, 'hold_sessions': pl.Int64, 'exit_delayed': pl.Boolean,
                'gross_return': pl.Float64, 'net_return': pl.Float64}


def stamp_tax_bps(day):
    """Sell-side stamp duty: 0.1% before 2023-08-28, 0.05% from that day."""
    return 10.0 if day < STAMP_TAX_CUT else 5.0


def transfer_fee_bps(day):
    """Both-side transfer fee: 0.002% before 2022-04-29, 0.001% from that day (applied to both exchanges)."""
    return 0.2 if day < TRANSFER_FEE_CUT else 0.1


@dataclass(frozen=True)
class ExecutionSpec:
    entry: str = 't1_open'
    exit: str = 'next_open'
    scenario: str = 'conservative'
    commission_bps: float = 2.5
    slippage_bps: float = 5.0
    max_hold_sessions: int = 10

    def __post_init__(self):
        if self.entry not in ENTRY_MODES or self.exit not in EXIT_MODES or self.scenario not in SCENARIOS:
            raise ValueError('execution entry/exit/scenario 不支持。')
        for name in ('commission_bps', 'slippage_bps'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(name + ' 必须为 0–100 的有限数。')
        if type(self.max_hold_sessions) is not int or not 1 <= self.max_hold_sessions <= 60:
            raise ValueError('max_hold_sessions 必须为 1–60。')

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - set(asdict(cls())):
            raise ValueError('execution 字段无效。')
        return cls(**value)


def _cents(expr):
    return (expr * 100).round(0).cast(pl.Int64)


def _stamp_tax(expr):
    return pl.when(expr < STAMP_TAX_CUT).then(10.0).otherwise(5.0)


def _transfer_fee(expr):
    return pl.when(expr < TRANSFER_FEE_CUT).then(0.2).otherwise(0.1)


def _entry_rule(spec, slip):
    """Return (blocking-status expression or null, entry price expression) on ``e_`` columns."""
    up = _cents(pl.col('e_limit_up_price'))
    if spec.entry == 't1_open':
        return (pl.when(_cents(pl.col('e_open')) >= up).then(pl.lit('NO_FILL_OPEN_AT_LIMIT_UP')).otherwise(pl.lit(None, pl.String)),
                pl.min_horizontal(pl.col('e_open') * (1 + slip), pl.col('e_limit_up_price')))
    if spec.entry == 't1_close':
        return (pl.when(_cents(pl.col('e_close')) >= up).then(pl.lit('NO_FILL_CLOSE_AT_LIMIT_UP')).otherwise(pl.lit(None, pl.String)),
                pl.min_horizontal(pl.col('e_close') * (1 + slip), pl.col('e_limit_up_price')))
    sealed_blocks = spec.scenario == 'conservative'
    blocked = (pl.when(~pl.col('e_touched_limit_up').fill_null(False)).then(pl.lit('NO_FILL_NOT_TOUCHED'))
               .when(pl.col('e_is_one_word_limit_up').fill_null(False)).then(pl.lit('NO_FILL_ONE_WORD'))
               .when(pl.lit(sealed_blocks) & pl.col('e_is_limit_up_close').fill_null(False)).then(pl.lit('NO_FILL_SEALED_QUEUE_UNKNOWN'))
               .otherwise(pl.lit(None, pl.String)))
    return blocked, pl.col('e_limit_up_price')


def simulate_trades(events, states, spec, *, last_pos=None):
    """Return one row per event (input order) with fill status, prices, holding sessions and returns.

    ``states`` must be the annotated panel the events came from (``_pos`` is the trading-calendar
    index); ``last_pos`` is the calendar's final index and defaults to the panel maximum.
    """
    if not isinstance(spec, ExecutionSpec):
        raise ValueError('spec 必须是 ExecutionSpec。')
    if 'date' not in events.columns or 'code' not in events.columns:
        raise ValueError('事件表缺少 date/code。')
    missing = [c for c in STATE_COLUMNS if c not in states.columns]
    if missing:
        raise ValueError('状态面板缺少列：' + ', '.join(missing))
    if events.height == 0:
        return pl.DataFrame(schema=TRADE_SCHEMA)
    panel = states.select(STATE_COLUMNS).with_columns(pl.col('_pos').cast(pl.Int64))
    if panel.select(pl.struct('code', '_pos').is_duplicated().any() | pl.struct('code', 'date').is_duplicated().any()).item():
        raise ValueError('状态面板存在重复证券交易日。')
    last = int(panel['_pos'].max()) if last_pos is None else int(last_pos)
    base = events.select('date', 'code').with_row_index('_event')
    located = base.join(panel.select('code', 'date', '_pos'), on=['code', 'date'], how='left')
    if located['_pos'].null_count():
        raise ValueError('事件在状态面板中不存在：必须使用生成该事件的状态面板。')
    slip = spec.slippage_bps / 10000
    horizon = spec.max_hold_sessions
    offset = 1 if spec.entry.startswith('t1_') else 0
    renamed = panel.rename({c: 'e_' + c.lstrip('_') for c in STATE_COLUMNS if c != 'code'})
    entry = located.with_columns((pl.col('_pos') + offset).alias('e_pos')).join(renamed, on=['code', 'e_pos'], how='left')
    blocked, price = _entry_rule(spec, slip)
    status = (pl.when(pl.col('e_pos') > last).then(pl.lit('PENDING_ENTRY_DATA'))
              .when(pl.col('e_tradable').is_null()).then(pl.lit('NO_FILL_NOT_LISTED'))
              .when(~pl.col('e_tradable')).then(pl.lit('NO_FILL_SUSPENDED'))
              .when((pl.col('e_limit_rule_status') != 'NORMAL') | pl.col('e_limit_up_price').is_null()).then(pl.lit('NO_FILL_UNMODELED'))
              .otherwise(pl.coalesce(blocked, pl.lit('FILLED'))))
    entry = entry.with_columns(status.alias('entry_status')).with_columns(
        pl.when(pl.col('entry_status') == 'FILLED').then(price).alias('entry_price'))
    entered = entry.filter(pl.col('entry_status') == 'FILLED')

    exit_column = 'open' if spec.exit == 'next_open' else 'close'
    window = (entered.select('_event', 'code', 'e_pos', 'e_close')
              .with_columns(pl.int_ranges(pl.col('e_pos') + 1, pl.col('e_pos') + horizon + 1).alias('_p'))
              .explode('_p', empty_as_null=False)
              .join(panel.select('code', pl.col('_pos').alias('_p'), 'date', 'tradable', 'open', 'close', 'preclose',
                                 'limit_down_price'), on=['code', '_p'], how='inner')
              .filter(pl.col('tradable') & pl.col('preclose').is_not_null())
              .sort('_event', '_p'))
    window = window.with_columns(pl.coalesce(pl.col('close').shift(1).over('_event'), pl.col('e_close')).alias('_prev_close'))
    window = window.with_columns(
        (pl.col('_prev_close') / pl.col('preclose')).cum_prod().over('_event').alias('_factor'),
        (pl.col('limit_down_price').is_null() | (_cents(pl.col(exit_column)) > _cents(pl.col('limit_down_price')))).alias('_can_exit'))
    first_exit = window.filter(pl.col('_can_exit')).group_by('_event', maintain_order=True).first().select(
        '_event', pl.col('_p').alias('x_pos'), pl.col('date').alias('x_date'), pl.col(exit_column).alias('x_price'),
        pl.col('limit_down_price').alias('x_down'), pl.col('_factor').alias('x_factor'))
    last_row = window.group_by('_event', maintain_order=True).last().select(
        '_event', pl.col('_p').alias('m_pos'), pl.col('date').alias('m_date'), pl.col('close').alias('m_close'),
        pl.col('limit_down_price').alias('m_down'), pl.col('_factor').alias('m_factor'))
    code_last = panel.group_by('code').agg(pl.col('_pos').max().alias('_code_last'))
    fills = (entered.select('_event', 'code', 'e_pos', 'e_date', 'e_close', 'e_limit_down_price', 'entry_price')
             .join(code_last, on='code', how='left').join(first_exit, on='_event', how='left').join(last_row, on='_event', how='left'))
    resolved = pl.col('x_pos').is_not_null()
    pending = (pl.col('e_pos') + horizon > last) & (pl.col('_code_last') >= last)
    fills = fills.with_columns(pl.when(resolved).then(pl.lit('FILLED')).when(pending).then(pl.lit('PENDING_EXIT_DATA'))
                               .otherwise(pl.lit('UNRESOLVED_EXIT')).alias('fill_status'))
    is_filled, is_marked = pl.col('fill_status') == 'FILLED', pl.col('fill_status') == 'UNRESOLVED_EXIT'
    mark_price = pl.when(pl.col('m_pos').is_not_null()).then(pl.max_horizontal(pl.col('m_close') * (1 - slip), pl.col('m_down'))) \
        .otherwise(pl.max_horizontal(pl.col('e_close') * (1 - slip), pl.col('e_limit_down_price')))
    fills = fills.with_columns(
        pl.when(is_filled).then(pl.max_horizontal(pl.col('x_price') * (1 - slip), pl.col('x_down'))).when(is_marked).then(mark_price)
        .alias('exit_price'),
        pl.when(is_filled).then(pl.col('x_date')).when(is_marked).then(pl.col('m_date')).alias('exit_date'),
        pl.when(is_filled).then(pl.col('x_pos') - pl.col('e_pos')).when(is_marked).then(pl.col('m_pos') - pl.col('e_pos'))
        .alias('hold_sessions'),
        pl.when(is_filled).then(pl.col('x_pos') > pl.col('e_pos') + 1).when(is_marked).then(True).alias('exit_delayed'),
        pl.when(is_filled).then(pl.col('x_factor')).when(is_marked).then(pl.col('m_factor').fill_null(1.0)).alias('_factor'))
    fills = fills.with_columns((pl.col('exit_price') / pl.col('entry_price') * pl.col('_factor') - 1).alias('gross_return'))
    buy_cost = (spec.commission_bps + _transfer_fee(pl.col('e_date'))) / 10000
    sell_day = pl.coalesce(pl.col('exit_date'), pl.col('e_date'))
    sell_cost = (spec.commission_bps + _transfer_fee(sell_day) + _stamp_tax(sell_day)) / 10000
    fills = fills.with_columns(((1 + pl.col('gross_return')) * (1 - sell_cost) / (1 + buy_cost) - 1).alias('net_return'))
    out = entry.select('_event', 'date', 'code', 'entry_status').join(
        fills.select('_event', 'fill_status', pl.col('e_date').alias('entry_date'), 'entry_price', 'exit_date', 'exit_price',
                     'hold_sessions', 'exit_delayed', 'gross_return', 'net_return'), on='_event', how='left')
    out = out.with_columns(pl.coalesce(pl.col('fill_status'), pl.col('entry_status')).alias('fill_status')).sort('_event')
    return out.select([pl.col(name).cast(dtype) for name, dtype in TRADE_SCHEMA.items()])


def fill_summary(trades):
    """Fill statistics; pending rows (data ends before entry or exit window) are excluded from rates."""
    counts = {r['fill_status']: r['len'] for r in trades.group_by('fill_status').len().sort('fill_status').to_dicts()}
    pending = sum(counts.get(s, 0) for s in PENDING_STATUSES)
    resolved = trades.height - pending
    entered = trades.filter(pl.col('fill_status').is_in(ENTERED_STATUSES))
    filled = trades.filter(pl.col('fill_status') == 'FILLED')
    net = entered['net_return'].drop_nulls()
    return {'events': trades.height, 'pending': pending, 'resolved': resolved, 'entered': entered.height,
            'fill_rate': entered.height / resolved if resolved else None, 'status_counts': counts,
            'delayed_exits': int(filled['exit_delayed'].sum()) if filled.height else 0,
            'unresolved_exits': counts.get('UNRESOLVED_EXIT', 0),
            'mean_net_return': float(net.mean()) if net.len() else None,
            'median_net_return': float(net.median()) if net.len() else None,
            'mean_hold_sessions': float(entered['hold_sessions'].drop_nulls().mean()) if entered.height and entered['hold_sessions'].drop_nulls().len() else None}


__all__ = ['EXECUTION_VERSION', 'ENTRY_MODES', 'EXIT_MODES', 'SCENARIOS', 'STATUSES', 'ENTERED_STATUSES', 'NO_FILL_STATUSES',
           'PENDING_STATUSES', 'STATE_COLUMNS', 'TRADE_SCHEMA', 'ExecutionSpec', 'fill_summary', 'simulate_trades',
           'stamp_tax_bps', 'transfer_fee_bps']
