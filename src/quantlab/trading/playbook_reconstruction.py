"""Retrospective helpers for reconstructing playbook candidate universes.

These helpers derive historical facts from saved daily bars. They do not certify
strict PIT availability or official-rule coverage; callers must preserve that distinction.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import math

import polars as pl

from .price_limit_regime import NORMAL, limit_rule

MAIN_PREFIXES = ('sh.600','sh.601','sh.603','sh.605','sz.000','sz.001','sz.002','sz.003')
GROWTH_PREFIXES = ('sz.300','sz.301','sz.302','sh.688','sh.689')


def default_limit_rate(symbol: str) -> float:
    """Current-regime non-ST rate by board; historical/ST sessions must use price_limit_regime.limit_rule."""
    symbol = str(symbol).lower()
    if symbol.startswith(GROWTH_PREFIXES):
        return 0.20
    if symbol.startswith('bj.'):
        return 0.30
    return 0.10


def rounded_limit_price(previous_close: float, rate: float) -> float:
    if type(previous_close) not in (int,float) or not math.isfinite(previous_close) or previous_close <= 0:
        raise ValueError('previous_close 必须为正有限数。')
    if type(rate) not in (int,float) or not math.isfinite(rate) or not 0 < rate <= 1:
        raise ValueError('limit rate 必须为 (0,1] 的有限数。')
    value = Decimal(str(previous_close)) * (Decimal('1') + Decimal(str(rate)))
    return float(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def _validate_bars(bars: pl.DataFrame) -> pl.DataFrame:
    required = {'date','code','close'}
    if not isinstance(bars, pl.DataFrame) or required-set(bars.columns):
        raise ValueError('bars 必须包含 date/code/close。')
    if bars.select(pl.struct('code','date').is_duplicated().any()).item():
        raise ValueError('bars 不能包含重复证券/日期。')
    if bars.filter(pl.col('close').is_null() | ~pl.col('close').is_finite() | (pl.col('close')<=0)).height:
        raise ValueError('close 必须为正有限数。')
    columns=['date','code','close']
    for optional in ('tradable','limit_rate'):
        if optional in bars.columns: columns.append(optional)
    frame=bars.select(columns).sort(['code','date'])
    if 'tradable' not in frame.columns: frame=frame.with_columns(pl.lit(True).alias('tradable'))
    if frame.filter(pl.col('tradable').is_null()).height: raise ValueError('tradable 不能含空值。')
    if 'limit_rate' in frame.columns:
        bad=frame.filter(pl.col('limit_rate').is_not_null() & (~pl.col('limit_rate').is_finite() | (pl.col('limit_rate')<=0) | (pl.col('limit_rate')>1)))
        if bad.height: raise ValueError('limit_rate 必须为 (0,1] 的有限数。')
    return frame


def mark_limit_closes(bars: pl.DataFrame, *, special_rates=None) -> pl.DataFrame:
    """Mark exact close-at-limit sessions using explicit board/special rates."""
    frame = _validate_bars(bars)
    overrides = {str(k).lower():float(v) for k,v in (special_rates or {}).items()}
    records = []
    for key, group in frame.group_by('code', maintain_order=True):
        symbol = key[0] if isinstance(key, tuple) else key
        previous = None
        for row in group.sort('date').iter_rows(named=True):
            day=row['date']; row_rate=row.get('limit_rate')
            if row_rate is not None:rate=float(row_rate)
            elif (symbol,day) in overrides or symbol in overrides:rate=overrides.get((symbol,day),overrides.get(symbol))
            else:
                # Date-aware reconstructed regime (board reform dates, STAR/BSE opening); ST and
                # listing windows are unknown here, so non-NORMAL sessions carry no inferred bound.
                inferred=limit_rule(symbol,day)
                rate=inferred['rate'] if inferred['status']==NORMAL else None
            tradable=bool(row.get('tradable',True)); close=float(row['close'])
            limit_up = rounded_limit_price(previous, rate) if tradable and previous is not None and rate is not None else None
            records.append({
                'date': day, 'code': symbol, 'close': close, 'tradable':tradable,
                'previous_close': previous, 'limit_rate': rate,
                'limit_up_price': limit_up,
                'is_limit_close': bool(limit_up is not None and abs(close-limit_up) < 1e-9),
            })
            if tradable: previous = close
    return pl.DataFrame(records) if records else pl.DataFrame(schema={
        'date':pl.Date,'code':pl.String,'close':pl.Float64,'tradable':pl.Boolean,'previous_close':pl.Float64,
        'limit_rate':pl.Float64,'limit_up_price':pl.Float64,'is_limit_close':pl.Boolean})


def exact_limit_streak_candidates(marked: pl.DataFrame, as_of: date, *, streak=2,
        eligible_prefixes=None) -> list[dict]:
    if not isinstance(as_of, date):
        raise ValueError('as_of 必须为 date。')
    if type(streak) is not int or not 1 <= streak <= 20:
        raise ValueError('streak 必须为 1–20。')
    prefixes = tuple(eligible_prefixes or ())
    result = []
    for key, group in marked.group_by('code', maintain_order=True):
        symbol = key[0] if isinstance(key, tuple) else key
        if prefixes and not symbol.startswith(prefixes):
            continue
        rows = [r for r in group.sort('date').iter_rows(named=True) if r['date'] <= as_of and r.get('tradable',True)]
        if not rows or rows[-1]['date'] != as_of or len(rows) < streak:
            continue
        trailing = 0
        for row in reversed(rows):
            if row['is_limit_close']:
                trailing += 1
            else:
                break
        if trailing != streak:
            continue
        last = rows[-1]
        result.append({
            'symbol': symbol,
            'streak': streak,
            'as_of': as_of.isoformat(),
            'limit_rate': last['limit_rate'],
            'last_close': last['close'],
            'last_limit_up_price': last['limit_up_price'],
        })
    return sorted(result, key=lambda item:item['symbol'])


__all__ = [
    'MAIN_PREFIXES','GROWTH_PREFIXES','default_limit_rate','rounded_limit_price',
    'mark_limit_closes','exact_limit_streak_candidates',
]
