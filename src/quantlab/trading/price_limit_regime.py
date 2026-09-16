"""Date-aware A-share daily price-limit regime for research reconstruction.

The table reconstructs exchange price-limit rules by trading session. It is NOT an
official per-session MarketRules receipt: callers must keep official MarketRules as
the higher-precedence source and must never upgrade reconstructed limits to strict
PIT or official-rule coverage.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import math
import re

REGIME_VERSION = 'a-share-price-limit-regime-v1'
SYMBOL = re.compile(r'^(sh|sz|bj)\.\d{6}$')

MAIN, CHINEXT, STAR, BSE, UNKNOWN = 'MAIN', 'CHINEXT', 'STAR', 'BSE', 'UNKNOWN'
NORMAL, NO_LIMIT, UNMODELED = 'NORMAL', 'NO_LIMIT', 'UNMODELED'

MAIN_PREFIXES = ('sh.600', 'sh.601', 'sh.603', 'sh.605', 'sz.000', 'sz.001', 'sz.002', 'sz.003')
CHINEXT_PREFIXES = ('sz.300', 'sz.301', 'sz.302')
STAR_PREFIXES = ('sh.688', 'sh.689')

STAR_OPEN = date(2019, 7, 22)                 # 科创板开市：20%，新股前5个交易日无涨跌幅
CHINEXT_REFORM = date(2020, 8, 24)            # 创业板改革：10%→20%，ST 5%→20%，新股前5日无涨跌幅
BSE_OPEN = date(2021, 11, 15)                 # 北交所开市：30%，上市首日无涨跌幅
MAIN_REGISTRATION = date(2023, 4, 10)         # 主板注册制首批上市：新股前5个交易日无涨跌幅
MAIN_RISK_WARNING_10PCT = date(2026, 7, 6)    # 沪深主板风险警示股票涨跌幅 5%→10%

IPO_NO_LIMIT_SESSIONS = 5
NEAR_DELISTING_SESSIONS = 30
LISTING_WINDOW_MAX_CALENDAR_DAYS = 20

CHANGES = (
    {'date': STAR_OPEN.isoformat(), 'board': STAR, 'change': '科创板开市：普通与风险警示股票20%，新股上市前5个交易日无涨跌幅'},
    {'date': CHINEXT_REFORM.isoformat(), 'board': CHINEXT, 'change': '创业板改革：普通10%→20%，风险警示5%→20%，新股上市前5个交易日无涨跌幅'},
    {'date': BSE_OPEN.isoformat(), 'board': BSE, 'change': '北交所开市：30%，上市首日无涨跌幅'},
    {'date': MAIN_REGISTRATION.isoformat(), 'board': MAIN, 'change': '主板注册制新股：上市前5个交易日无涨跌幅（此前首日为特殊规则，未建模）'},
    {'date': MAIN_RISK_WARNING_10PCT.isoformat(), 'board': MAIN, 'change': '沪深主板风险警示股票涨跌幅5%→10%'},
)


def board_of(symbol):
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
        raise ValueError('symbol 必须为 sh/sz/bj.XXXXXX。')
    if symbol.startswith(MAIN_PREFIXES):
        return MAIN
    if symbol.startswith(CHINEXT_PREFIXES):
        return CHINEXT
    if symbol.startswith(STAR_PREFIXES):
        return STAR
    if symbol.startswith('bj.'):
        return BSE
    return UNKNOWN


def _session(value, name):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError(name + ' 必须为 date。')


def _count(value, name, minimum):
    if value is None:
        return None
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} 必须为不小于 {minimum} 的整数或 None。')
    return value


def _result(board, status, rate, reason, checked):
    return {'regime_version': REGIME_VERSION, 'board': board, 'status': status, 'rate': rate,
            'reason': reason, 'listing_window_checked': checked}


def _rate(board, session, is_st):
    if board == MAIN:
        if is_st:
            return (0.10, 'MAIN_RISK_WARNING_10PCT') if session >= MAIN_RISK_WARNING_10PCT else (0.05, 'MAIN_RISK_WARNING_5PCT')
        return 0.10, 'MAIN_10PCT'
    if board == CHINEXT:
        if session >= CHINEXT_REFORM:
            return 0.20, 'CHINEXT_RISK_WARNING_20PCT' if is_st else 'CHINEXT_20PCT'
        return (0.05, 'CHINEXT_RISK_WARNING_5PCT_PRE_REFORM') if is_st else (0.10, 'CHINEXT_10PCT_PRE_REFORM')
    if board == STAR:
        return 0.20, 'STAR_RISK_WARNING_20PCT' if is_st else 'STAR_20PCT'
    return 0.30, 'BSE_RISK_WARNING_30PCT' if is_st else 'BSE_30PCT'


def _ipo_rule(board, listing_regime_day):
    """Return (no-limit sessions from listing day, first-day special rule unmodeled)."""
    if board == STAR:
        return IPO_NO_LIMIT_SESSIONS, False
    if board == CHINEXT:
        return (IPO_NO_LIMIT_SESSIONS, False) if listing_regime_day >= CHINEXT_REFORM else (0, True)
    if board == MAIN:
        return (IPO_NO_LIMIT_SESSIONS, False) if listing_regime_day >= MAIN_REGISTRATION else (0, True)
    return 1, False


def limit_rule(symbol, session, *, is_st=False, listing_date=None, sessions_since_listing=None,
               sessions_to_delisting=None):
    """Reconstructed daily limit rule for one security session.

    ``sessions_since_listing`` is 1 on the listing day. ``sessions_to_delisting`` counts
    exchange sessions from ``session`` to the delisting date. When listing information is
    omitted the result keeps ``listing_window_checked=False`` so callers can disclose that
    new-listing no-limit windows were not resolved.
    """
    board = board_of(symbol)
    session = _session(session, 'session')
    if type(is_st) is not bool:
        raise ValueError('is_st 必须为布尔值。')
    listing = _session(listing_date, 'listing_date') if listing_date is not None else None
    since = _count(sessions_since_listing, 'sessions_since_listing', 1)
    to_delisting = _count(sessions_to_delisting, 'sessions_to_delisting', 0)
    if board == UNKNOWN:
        return _result(board, UNMODELED, None, 'UNKNOWN_BOARD', False)
    opening = {STAR: STAR_OPEN, BSE: BSE_OPEN}.get(board)
    if opening is not None and session < opening:
        return _result(board, UNMODELED, None, 'BEFORE_BOARD_OPEN', False)
    checked = False
    if listing is not None or since is not None:
        if listing is not None and session < listing:
            return _result(board, UNMODELED, None, 'BEFORE_LISTING', True)
        no_limit, first_day_special = _ipo_rule(board, listing if listing is not None else session)
        if since is not None:
            if since <= no_limit:
                return _result(board, NO_LIMIT, None, 'IPO_NO_LIMIT_WINDOW', True)
            if first_day_special and since == 1:
                return _result(board, UNMODELED, None, 'IPO_FIRST_DAY_SPECIAL_RULE_UNMODELED', True)
            checked = True
        elif (session - listing).days > LISTING_WINDOW_MAX_CALENDAR_DAYS:
            checked = True
        else:
            return _result(board, UNMODELED, None, 'LISTING_WINDOW_UNRESOLVED', False)
    if to_delisting is not None and to_delisting <= NEAR_DELISTING_SESSIONS:
        return _result(board, UNMODELED, None, 'NEAR_DELISTING_UNMODELED', checked)
    rate, reason = _rate(board, session, is_st)
    return _result(board, NORMAL, rate, reason, checked)


def limit_prices(reference, rate):
    """Exchange-style bounds: reference × (1 ± rate), rounded half-up to 0.01 yuan."""
    if type(reference) not in (int, float) or not math.isfinite(reference) or reference <= 0:
        raise ValueError('reference 必须为正有限数。')
    if type(rate) not in (int, float) or not math.isfinite(rate) or not 0 < rate < 1:
        raise ValueError('rate 必须为 (0,1) 的有限数。')
    base = Decimal(str(reference))
    step = Decimal(str(rate))
    up = (base * (Decimal('1') + step)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    down = (base * (Decimal('1') - step)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return float(up), float(down)


__all__ = [
    'REGIME_VERSION', 'MAIN', 'CHINEXT', 'STAR', 'BSE', 'UNKNOWN', 'NORMAL', 'NO_LIMIT', 'UNMODELED',
    'MAIN_PREFIXES', 'CHINEXT_PREFIXES', 'STAR_PREFIXES', 'STAR_OPEN', 'CHINEXT_REFORM', 'BSE_OPEN',
    'MAIN_REGISTRATION', 'MAIN_RISK_WARNING_10PCT', 'IPO_NO_LIMIT_SESSIONS', 'NEAR_DELISTING_SESSIONS',
    'CHANGES', 'board_of', 'limit_rule', 'limit_prices',
]
