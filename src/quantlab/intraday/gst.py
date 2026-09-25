"""Read-only access to DATA's gst_intraday database (16 stocks, 3-second trades, 1-minute bars).

Contract (data catalog §3.6, dataset `gst_intraday`, READY):
- open DuckDB read-only; read only ticks / quotes / bars_1m / stock_days / stocks /
  trading_days, always filtered by symbol and date; never the *_all tables, never write;
- views and bars_1m already contain usable days only;
- prices are unadjusted yuan (fine for same-day trading), volume in shares, amount in yuan;
- 1-minute bars are labelled by the minute's end; 09:25 is the opening auction, 15:00 holds
  the closing auction; minutes without trades have no row;
- price limits are not stored: prev_close (stock_days) x board rule, ST from
  security_status_baostock_v2.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from quantlab.data.dataset_catalog import DataCatalogError, get_ready_data_source
from quantlab.trading.price_limit_regime import NORMAL, limit_prices, limit_rule

DATASET = 'gst_intraday'
STATUS_DATASET = 'security_status_baostock_v2'
BAR_COLUMNS = ('minute', 'open', 'high', 'low', 'close', 'volume', 'amount', 'vwap', 'ticks',
               'buy_volume', 'sell_volume')

RULE_LABELS = {'MAIN_10PCT': '主板 ±10%', 'CHINEXT_20PCT': '创业板 ±20%',
               'CHINEXT_10PCT_PRE_REFORM': '创业板 ±10%（2020-08-24 改革前）', 'MAIN_RISK_WARNING_5PCT': 'ST ±5%'}


MARKET_MIN_STOCKS = 8


def market_asof(context, minutes, field='ret_pc'):
    """Market value at each of `minutes` as of that minute (last market minute <= it); NaN before 09:30."""
    minutes = np.asarray(minutes).astype(str)
    if context is None or len(context['minutes']) == 0:
        return np.full(len(minutes), np.nan)
    at = np.searchsorted(context['minutes'], minutes, side='right') - 1
    values = np.asarray(context[field], dtype=float)
    return np.where((at >= 0) & (minutes >= '09:30'), values[np.maximum(at, 0)], np.nan)


class IntradayDataError(ValueError):
    pass


def _ready_path(catalog_path, dataset_id) -> Path:
    try:
        source = get_ready_data_source(catalog_path, dataset_id=dataset_id)
    except DataCatalogError as exc:
        raise IntradayDataError(f'{dataset_id} 不可用：{exc}') from None
    paths = source['technical_check']['paths']
    if not paths:
        raise IntradayDataError(f'数据清单没有给出 {dataset_id} 的路径')
    return Path(paths[0]['path'])


@dataclass
class Day:
    """One usable trading day of one stock, as numpy arrays over its 1-minute bars."""
    symbol: str
    name: str
    date: date
    prev_close: float
    limit_up: float | None
    limit_down: float | None
    limit_reason: str
    bars: dict
    # equal-weight average return vs previous close of all gst stocks at each of this day's minutes
    # (last trade so far per stock; NaN where fewer than MARKET_MIN_STOCKS have traded or unknown)
    market: object = None
    # the whole day's market context from GstIntraday.market() (minutes, ret_pc, ret_open, count, gap)
    context: object = None
    # the previous usable day's volume (shares), from stock_days; None for the first usable day
    prev_volume: float | None = None

    @property
    def minutes(self):
        return self.bars['minute']


class GstIntraday:
    """Thread-safe read-only reader. One connection per instance; queries are serialised."""

    def __init__(self, catalog_path=None, *, path=None, status_dir=None):
        """`path` / `status_dir` override the catalog paths (tests and other mounts of the same data)."""
        self.path = Path(path) if path else _ready_path(catalog_path, DATASET)
        if not self.path.is_file():
            raise IntradayDataError(f'找不到日内数据库：{self.path}（数据盘是否连接？）')
        self.catalog_path = catalog_path
        self.status_dir = Path(status_dir) if status_dir else None
        self._lock = threading.Lock()
        self._conn = None
        self._st = {}
        self._market = {}

    def _db(self):
        if self._conn is None:
            import duckdb
            self._conn = duckdb.connect(str(self.path), read_only=True)
        return self._conn

    def _query(self, sql, params=()):
        with self._lock:
            return self._db().execute(sql, list(params))

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------ catalogue tables
    def stocks(self) -> list[dict]:
        cursor = self._query('select symbol, name, tick_days, tick_from, tick_to, quote_days, quote_from, quote_to '
                             'from stocks order by symbol')
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def usable_days(self, symbol: str, start=None, end=None) -> list[date]:
        sql = 'select date from stock_days where symbol = ? and usable_ticks'
        params = [symbol]
        if start:
            sql += ' and date >= ?'
            params.append(start)
        if end:
            sql += ' and date <= ?'
            params.append(end)
        return [row[0] for row in self._query(sql + ' order by date', params).fetchall()]

    def day_facts(self, symbol: str, day) -> dict | None:
        cursor = self._query('select date, prev_close, close, volume, amount, ref_close, usable_ticks, usable_quotes '
                             'from stock_days where symbol = ? and date = ?', [symbol, day])
        row = cursor.fetchone()
        return dict(zip([d[0] for d in cursor.description], row)) if row else None

    # ------------------------------------------------------------ ST and price limits
    def _st_days(self, symbol: str) -> set[str] | None:
        if symbol in self._st:
            return self._st[symbol]
        days = None
        try:
            folder = self.status_dir or _ready_path(self.catalog_path, STATUS_DATASET)
            path = folder / f"{symbol.replace('.', '_')}.parquet"
            if path.is_file():
                import polars as pl
                frame = pl.read_parquet(path, columns=['date', 'isST'])
                days = set(frame.filter(pl.col('isST') == '1')['date'].cast(pl.String).to_list())
        except (IntradayDataError, OSError):
            days = None
        self._st[symbol] = days
        return days

    def limits(self, symbol: str, day: date, prev_close: float) -> tuple[float | None, float | None, str]:
        st_days = self._st_days(symbol)
        is_st = bool(st_days and day.isoformat() in st_days)
        rule = limit_rule(symbol, day, is_st=is_st)
        label = RULE_LABELS.get(rule['reason'], rule['reason'])
        if rule['status'] != NORMAL or not prev_close or prev_close <= 0:
            return None, None, label + '（不设涨跌停检查）'
        up, down = limit_prices(float(prev_close), rule['rate'])
        reason = label + ('' if st_days is not None else '（ST 状态未知，按非 ST）')
        return up, down, reason

    # ------------------------------------------------------------ market context
    def market(self, start=None, end=None) -> dict:
        """Equal-weight context over the gst stocks, per date:
        {date: {'minutes': [...], 'ret_pc': [...], 'ret_open': [...], 'count': [...], 'gap': float}}.

        Computed in DuckDB with a date filter. At each minute every usable stock contributes its last
        trade price so far (its opening price before its first continuous trade), so a value only uses
        prices known at that minute. ret_pc is vs the previous close, ret_open vs the day's first price
        (the 09:25 auction when there is one); gap is the average first price vs the previous close.
        """
        key = (str(start) if start else None, str(end) if end else None)
        if key in self._market:
            return self._market[key]
        where, params = ['usable_ticks'], []
        if start:
            where.append('date >= ?')
            params.append(start)
        if end:
            where.append('date <= ?')
            params.append(end)
        cond = ' and '.join(where)
        sql = f"""
            with s as (select symbol, date, prev_close from stock_days where {cond}
                       and symbol in (select symbol from stocks)),
                 fo as (select b.symbol, b.date, arg_min(b.open, b.minute) as first_open
                        from bars_1m b join s using (symbol, date) group by b.symbol, b.date),
                 g as (select distinct b.date, b.minute from bars_1m b join s using (symbol, date)
                       where b.minute >= '09:30'),
                 x as (select s.date, g.minute, s.symbol, s.prev_close, fo.first_open, b.close
                       from s join fo on fo.symbol = s.symbol and fo.date = s.date
                       join g on g.date = s.date
                       left join bars_1m b on b.symbol = s.symbol and b.date = s.date and b.minute = g.minute),
                 f as (select date, minute, prev_close, first_open,
                              coalesce(last_value(close ignore nulls) over (
                                  partition by symbol, date order by minute
                                  rows between unbounded preceding and current row), first_open) as p
                       from x)
            select date, minute, avg(p / prev_close - 1), avg(p / first_open - 1), count(*),
                   avg(first_open / prev_close - 1)
            from f group by date, minute order by date, minute"""
        if len(self._market) >= 32:
            self._market.clear()
        out = {}
        for day, minute, r_pc, r_open, count, gap in self._query(sql, params).fetchall():
            item = out.setdefault(day, {'minutes': [], 'ret_pc': [], 'ret_open': [], 'count': [], 'gap': gap})
            item['minutes'].append(minute)
            item['ret_pc'].append(r_pc)
            item['ret_open'].append(r_open)
            item['count'].append(count)
        for item in out.values():
            ok = np.array(item['count']) >= MARKET_MIN_STOCKS
            item['minutes'] = np.array(item['minutes'])
            item['ret_pc'] = np.where(ok, np.array(item['ret_pc'], dtype=float), np.nan)
            item['ret_open'] = np.where(ok, np.array(item['ret_open'], dtype=float), np.nan)
            item['count'] = np.array(item['count'])
            if not ok.any():
                item['gap'] = None
        self._market[key] = out
        return out

    def _market_for(self, day, start, end):
        return self.market(start, end).get(day)

    # ------------------------------------------------------------ bars and ticks
    def days(self, symbol: str, start=None, end=None, *, with_market=True):
        """Yield Day objects for usable days in [start, end], one bars query per call
        (plus one cached market-context query per date range)."""
        sql = ('select b.date, b.minute, b.open, b.high, b.low, b.close, b.volume::double as volume, b.amount, '
               'b.vwap, b.ticks::double as ticks, b.buy_volume::double as buy_volume, '
               'b.sell_volume::double as sell_volume, d.prev_close, d.prev_volume '
               'from bars_1m b join (select symbol, date, prev_close, lag(volume::double) over '
               '(partition by symbol order by date) as prev_volume from stock_days '
               'where symbol = ? and usable_ticks) d on d.symbol = b.symbol and d.date = b.date '
               'where b.symbol = ?')
        params = [symbol, symbol]
        if start:
            sql += ' and b.date >= ?'
            params.append(start)
        if end:
            sql += ' and b.date <= ?'
            params.append(end)
        data = self._query(sql + ' order by b.date, b.minute', params).fetchnumpy()
        name = next((s['name'] for s in self.stocks() if s['symbol'] == symbol), symbol)
        dates = data['date']
        if len(dates) == 0:
            return
        dates = np.asarray(dates)
        bounds = np.flatnonzero(np.r_[True, dates[1:] != dates[:-1], True])
        for a, b in zip(bounds[:-1], bounds[1:]):
            day = dates[a]
            day = day.astype('datetime64[D]').astype(object) if isinstance(day, np.datetime64) else day
            prev_close = float(data['prev_close'][a])
            up, down, reason = self.limits(symbol, day, prev_close)
            bars = {'minute': np.asarray(data['minute'][a:b]).astype(str)}
            for key, column in (('open', 'open'), ('high', 'high'), ('low', 'low'), ('close', 'close'),
                                ('volume', 'volume'), ('amount', 'amount'), ('vwap', 'vwap'), ('ticks', 'ticks'),
                                ('buy_volume', 'buy_volume'), ('sell_volume', 'sell_volume')):
                values = data[column][a:b]
                bars[key] = np.asarray(np.ma.filled(values, np.nan) if np.ma.isMaskedArray(values) else values,
                                       dtype=float)
            context = self._market_for(day, start, end) if with_market else None
            prev_volume = data['prev_volume'][a]
            prev_volume = None if np.ma.is_masked(prev_volume) or prev_volume != prev_volume else float(prev_volume)
            yield Day(symbol, name, day, prev_close, up, down, reason, bars,
                      market_asof(context, bars['minute']) if context else None, context, prev_volume)

    def day(self, symbol: str, day) -> Day | None:
        return next(self.days(symbol, day, day), None)

    def ticks(self, symbol: str, day) -> list[dict]:
        cursor = self._query('select time, price, volume, amount, side from ticks where symbol = ? and date = ? '
                             'order by seq', [symbol, day])
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


__all__ = ['GstIntraday', 'Day', 'IntradayDataError', 'DATASET', 'market_asof']
