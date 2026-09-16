"""Vectorized daily limit-state annotation over a normalized A-share daily panel.

Input rows are exchange sessions per security. Prices must be unadjusted and ``preclose``
must be the exchange previous close (already adjusted for ex-rights by the exchange).
Limit prices are reconstructed with ``price_limit_regime``; they are research facts, not
official per-session MarketRules, and never certify strict PIT or official-rule coverage.
"""
from __future__ import annotations

import polars as pl

from .price_limit_regime import (
    BSE, BSE_OPEN, CHINEXT, CHINEXT_PREFIXES, CHINEXT_REFORM, IPO_NO_LIMIT_SESSIONS,
    LISTING_WINDOW_MAX_CALENDAR_DAYS, MAIN, MAIN_PREFIXES, MAIN_REGISTRATION,
    MAIN_RISK_WARNING_10PCT, NEAR_DELISTING_SESSIONS, NO_LIMIT, NORMAL, REGIME_VERSION,
    STAR, STAR_OPEN, STAR_PREFIXES, UNKNOWN, UNMODELED,
)

LIMIT_STATE_VERSION = 'limit-state-v1'
REQUIRED = {'date': pl.Date, 'code': pl.String, 'open': pl.Float64, 'high': pl.Float64,
            'low': pl.Float64, 'close': pl.Float64, 'preclose': pl.Float64,
            'tradable': pl.Boolean, 'is_st': pl.Boolean}
OPTIONAL = {'listing_date': pl.Date, 'sessions_since_listing': pl.Int64, 'sessions_to_delisting': pl.Int64}
STATE_COLUMNS = (
    'board', 'limit_rule_status', 'limit_rule_reason', 'limit_rate', 'listing_window_checked',
    'limit_up_price', 'limit_down_price', 'limit_price_violation',
    'is_limit_up_close', 'touched_limit_up', 'is_broken_board', 'is_one_word_limit_up', 'is_t_board',
    'is_limit_down_close', 'touched_limit_down', 'is_limit_up_to_down', 'is_limit_down_to_up',
    'limit_up_streak', 'limit_ups_5d', 'limit_ups_10d', 'is_first_board',
    'prev_is_limit_up_close', 'prev_limit_up_streak', 'prev_is_broken_board',
)


def _validate(frame):
    if not isinstance(frame, pl.DataFrame):
        raise ValueError('输入必须是 polars DataFrame。')
    missing = sorted(set(REQUIRED) - set(frame.columns))
    if missing:
        raise ValueError('日线面板缺少字段：' + ', '.join(missing))
    casts = []
    for name, dtype in {**REQUIRED, **OPTIONAL}.items():
        if name not in frame.columns:
            casts.append(pl.lit(None, dtype=dtype).alias(name))
            continue
        actual = frame.schema[name]
        if dtype == pl.Float64 and actual.is_numeric():
            casts.append(pl.col(name).cast(pl.Float64))
        elif dtype == pl.Int64 and (actual.is_integer() or actual == pl.Null):
            casts.append(pl.col(name).cast(pl.Int64))
        elif actual == dtype or (actual == pl.Null):
            casts.append(pl.col(name).cast(dtype))
        else:
            raise ValueError(f'字段 {name} 类型应为 {dtype}，实际为 {actual}。')
    panel = frame.with_columns(casts)
    if panel.select(pl.col('date').is_null().any() | pl.col('code').is_null().any() |
                    pl.col('tradable').is_null().any() | pl.col('is_st').is_null().any()).item():
        raise ValueError('date/code/tradable/is_st 不能为空。')
    if panel.select(pl.struct('code', 'date').is_duplicated().any()).item():
        raise ValueError('同一证券同一交易日不能重复。')
    bad_codes = panel.filter(~pl.col('code').str.contains(r'^(sh|sz|bj)\.\d{6}$'))
    if bad_codes.height:
        raise ValueError('证券代码无效：' + str(bad_codes['code'][0]))
    prices = ('open', 'high', 'low', 'close')
    tradable = panel.filter(pl.col('tradable'))
    invalid = tradable.filter(pl.any_horizontal([pl.col(c).is_null() | ~pl.col(c).is_finite() | (pl.col(c) <= 0) for c in prices]))
    if invalid.height:
        raise ValueError('可交易行的开高低收必须为正有限数：' + f"{invalid['code'][0]} {invalid['date'][0]}")
    inconsistent = tradable.filter((pl.col('high') < pl.max_horizontal('open', 'low', 'close') - 1e-9) |
                                   (pl.col('low') > pl.min_horizontal('open', 'high', 'close') + 1e-9))
    if inconsistent.height:
        raise ValueError('可交易行 OHLC 关系无效：' + f"{inconsistent['code'][0]} {inconsistent['date'][0]}")
    if panel.filter(pl.col('sessions_since_listing').is_not_null() & (pl.col('sessions_since_listing') < 1)).height:
        raise ValueError('sessions_since_listing 必须 ≥1。')
    if panel.filter(pl.col('sessions_to_delisting').is_not_null() & (pl.col('sessions_to_delisting') < 0)).height:
        raise ValueError('sessions_to_delisting 必须 ≥0。')
    return panel


def regime_columns(panel):
    """Vectorized mirror of ``price_limit_regime.limit_rule`` (equivalence is unit-tested)."""
    code, day, st = pl.col('code'), pl.col('date'), pl.col('is_st')
    prefix = code.str.slice(0, 6)
    board = (pl.when(prefix.is_in(list(MAIN_PREFIXES))).then(pl.lit(MAIN))
             .when(prefix.is_in(list(CHINEXT_PREFIXES))).then(pl.lit(CHINEXT))
             .when(prefix.is_in(list(STAR_PREFIXES))).then(pl.lit(STAR))
             .when(code.str.starts_with('bj.')).then(pl.lit(BSE))
             .otherwise(pl.lit(UNKNOWN)))
    frame = panel.with_columns(board.alias('board'))
    b = pl.col('board')
    listing, since, to_delist = pl.col('listing_date'), pl.col('sessions_since_listing'), pl.col('sessions_to_delisting')
    has_listing = listing.is_not_null() | since.is_not_null()
    regime_day = pl.coalesce(listing, day)
    no_limit = (pl.when(b == STAR).then(IPO_NO_LIMIT_SESSIONS)
                .when(b == CHINEXT).then(pl.when(regime_day >= CHINEXT_REFORM).then(IPO_NO_LIMIT_SESSIONS).otherwise(0))
                .when(b == MAIN).then(pl.when(regime_day >= MAIN_REGISTRATION).then(IPO_NO_LIMIT_SESSIONS).otherwise(0))
                .otherwise(1))
    special = ((b == CHINEXT) & (regime_day < CHINEXT_REFORM)) | ((b == MAIN) & (regime_day < MAIN_REGISTRATION))
    before_open = ((b == STAR) & (day < STAR_OPEN)) | ((b == BSE) & (day < BSE_OPEN))
    before_listing = listing.is_not_null() & (day < listing)
    in_ipo_window = since.is_not_null() & (since <= no_limit)
    first_day_special = since.is_not_null() & special & (since == 1)
    unresolved = since.is_null() & listing.is_not_null() & ((day - listing).dt.total_days() <= LISTING_WINDOW_MAX_CALENDAR_DAYS)
    near_delisting = to_delist.is_not_null() & (to_delist <= NEAR_DELISTING_SESSIONS)
    rate = (pl.when(b == MAIN).then(pl.when(st & (day < MAIN_RISK_WARNING_10PCT)).then(0.05).otherwise(0.10))
            .when(b == CHINEXT).then(pl.when(day >= CHINEXT_REFORM).then(0.20).when(st).then(0.05).otherwise(0.10))
            .when(b == STAR).then(0.20).otherwise(0.30))
    normal_reason = (pl.when(b == MAIN).then(pl.when(st & (day < MAIN_RISK_WARNING_10PCT)).then(pl.lit('MAIN_RISK_WARNING_5PCT'))
                                              .when(st).then(pl.lit('MAIN_RISK_WARNING_10PCT')).otherwise(pl.lit('MAIN_10PCT')))
                     .when(b == CHINEXT).then(pl.when(day >= CHINEXT_REFORM).then(pl.when(st).then(pl.lit('CHINEXT_RISK_WARNING_20PCT')).otherwise(pl.lit('CHINEXT_20PCT')))
                                                 .when(st).then(pl.lit('CHINEXT_RISK_WARNING_5PCT_PRE_REFORM')).otherwise(pl.lit('CHINEXT_10PCT_PRE_REFORM')))
                     .when(b == STAR).then(pl.when(st).then(pl.lit('STAR_RISK_WARNING_20PCT')).otherwise(pl.lit('STAR_20PCT')))
                     .otherwise(pl.when(st).then(pl.lit('BSE_RISK_WARNING_30PCT')).otherwise(pl.lit('BSE_30PCT'))))
    unknown, opened = b == UNKNOWN, ~before_open
    status = (pl.when(unknown | before_open).then(pl.lit(UNMODELED))
              .when(has_listing & before_listing).then(pl.lit(UNMODELED))
              .when(has_listing & in_ipo_window).then(pl.lit(NO_LIMIT))
              .when(has_listing & (first_day_special | unresolved)).then(pl.lit(UNMODELED))
              .when(near_delisting).then(pl.lit(UNMODELED))
              .otherwise(pl.lit(NORMAL)))
    reason = (pl.when(unknown).then(pl.lit('UNKNOWN_BOARD'))
              .when(before_open).then(pl.lit('BEFORE_BOARD_OPEN'))
              .when(has_listing & before_listing).then(pl.lit('BEFORE_LISTING'))
              .when(has_listing & in_ipo_window).then(pl.lit('IPO_NO_LIMIT_WINDOW'))
              .when(has_listing & first_day_special).then(pl.lit('IPO_FIRST_DAY_SPECIAL_RULE_UNMODELED'))
              .when(has_listing & unresolved).then(pl.lit('LISTING_WINDOW_UNRESOLVED'))
              .when(near_delisting).then(pl.lit('NEAR_DELISTING_UNMODELED'))
              .otherwise(normal_reason))
    checked = (pl.when(unknown | before_open).then(False)
               .when(has_listing & (before_listing | in_ipo_window | first_day_special)).then(True)
               .when(has_listing & unresolved).then(False)
               .otherwise(has_listing & opened))
    frame = frame.with_columns(status.alias('limit_rule_status'), reason.alias('limit_rule_reason'),
                               checked.alias('listing_window_checked'))
    return frame.with_columns(pl.when(pl.col('limit_rule_status') == NORMAL).then(rate).otherwise(None)
                              .cast(pl.Float64).alias('limit_rate'))


def _cents(expr):
    return (expr * 100).round(0).cast(pl.Int64)


def annotate_limit_states(frame):
    """Return the panel with §6.2 limit-state columns; non-tradable rows keep null states."""
    panel = regime_columns(_validate(frame)).sort('code', 'date')
    rate_bp = (pl.col('limit_rate') * 10000).round(0).cast(pl.Int64)
    pre = _cents(pl.col('preclose'))
    usable = pl.col('tradable') & (pl.col('limit_rule_status') == NORMAL) & pl.col('preclose').is_not_null() & (pl.col('preclose') > 0)
    up_cents = pl.when(usable).then((pre * (10000 + rate_bp) + 5000) // 10000)
    down_cents = pl.when(usable).then((pre * (10000 - rate_bp) + 5000) // 10000)
    panel = panel.with_columns(up_cents.alias('_up'), down_cents.alias('_down'),
                               _cents(pl.col('open')).alias('_o'), _cents(pl.col('high')).alias('_h'),
                               _cents(pl.col('low')).alias('_l'), _cents(pl.col('close')).alias('_c'))
    has = pl.col('_up').is_not_null()
    def flag(expr):
        return pl.when(has).then(expr).otherwise(None)
    touched_up = pl.col('_h') >= pl.col('_up')
    close_up = pl.col('_c') == pl.col('_up')
    touched_down = pl.col('_l') <= pl.col('_down')
    close_down = pl.col('_c') == pl.col('_down')
    panel = panel.with_columns(
        (pl.col('_up') / 100).alias('limit_up_price'), (pl.col('_down') / 100).alias('limit_down_price'),
        flag((pl.col('_h') > pl.col('_up')) | (pl.col('_l') < pl.col('_down'))).alias('limit_price_violation'),
        flag(close_up).alias('is_limit_up_close'), flag(touched_up).alias('touched_limit_up'),
        flag(touched_up & ~close_up).alias('is_broken_board'),
        flag((pl.col('_o') == pl.col('_up')) & (pl.col('_h') == pl.col('_up')) & (pl.col('_l') == pl.col('_up')) & close_up).alias('is_one_word_limit_up'),
        flag((pl.col('_o') == pl.col('_up')) & close_up & (pl.col('_l') < pl.col('_up'))).alias('is_t_board'),
        flag(close_down).alias('is_limit_down_close'), flag(touched_down).alias('touched_limit_down'),
        flag(touched_up & close_down).alias('is_limit_up_to_down'),
        flag(touched_down & close_up).alias('is_limit_down_to_up'),
    )
    # Sequence features run over tradable sessions only: suspension neither increments nor breaks a streak.
    sessions = panel.filter(pl.col('tradable')).select('code', 'date', 'is_limit_up_close', 'is_broken_board')
    up = pl.col('is_limit_up_close').fill_null(False)
    sessions = sessions.with_columns((~up).cast(pl.Int64).cum_sum().over('code').alias('_run'))
    sessions = sessions.with_columns(
        pl.when(up).then(up.cast(pl.Int64).cum_sum().over('code', '_run')).otherwise(0).alias('limit_up_streak'),
        up.cast(pl.Int64).rolling_sum(window_size=5, min_samples=1).over('code').alias('limit_ups_5d'),
        up.cast(pl.Int64).rolling_sum(window_size=10, min_samples=1).over('code').alias('limit_ups_10d'),
    )
    sessions = sessions.with_columns(
        (up & (pl.col('limit_up_streak') == 1)).alias('is_first_board'),
        up.shift(1).over('code').alias('prev_is_limit_up_close'),
        pl.col('limit_up_streak').shift(1).over('code').alias('prev_limit_up_streak'),
        pl.col('is_broken_board').fill_null(False).shift(1).over('code').alias('prev_is_broken_board'),
    ).select('code', 'date', 'limit_up_streak', 'limit_ups_5d', 'limit_ups_10d', 'is_first_board',
             'prev_is_limit_up_close', 'prev_limit_up_streak', 'prev_is_broken_board')
    panel = panel.drop('_up', '_down', '_o', '_h', '_l', '_c').join(sessions, on=['code', 'date'], how='left')
    return panel.sort('date', 'code')


__all__ = ['LIMIT_STATE_VERSION', 'REGIME_VERSION', 'STATE_COLUMNS', 'regime_columns', 'annotate_limit_states']
