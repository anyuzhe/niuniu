"""Statutory A-share trading fees by trade date: stamp duty (seller only) and securities transfer fee (both sides).

Rates are charged as a share of turnover. Stamp duty: 10 bps on the seller from 2008-09-19, halved to 5 bps from 2023-08-28.
Transfer fee for Shanghai and Shenzhen A shares: 0.2 bps on both sides from 2015-08-01 (when both exchanges moved to a
turnover-based fee), halved to 0.1 bps from 2022-04-29. Earlier dates are refused rather than guessed.
"""
from __future__ import annotations

from datetime import date, datetime

FEE_SCHEDULE_VERSION = 'cn-a-statutory-fees-v1'
STAMP_DUTY_BPS = ((date(2008, 9, 19), 10.0), (date(2023, 8, 28), 5.0))
TRANSFER_FEE_BPS = ((date(2015, 8, 1), 0.2), (date(2022, 4, 29), 0.1))


def _rate(schedule, day, name):
    rate = None
    for start, value in schedule:
        if day >= start:
            rate = value
    if rate is None:
        raise ValueError(f'{day} 早于 {name} 统一按成交额计收的起始日，法定费用口径不支持该日期。')
    return rate


def statutory_fee_bps(moment):
    """Statutory ``sell_tax_bps`` and ``transfer_bps`` in force on the trade date of ``moment`` (a date or datetime)."""
    if isinstance(moment, datetime):
        day = moment.date()
    elif isinstance(moment, date):
        day = moment
    else:
        raise ValueError('法定费用需要成交日期。')
    return {'sell_tax_bps': _rate(STAMP_DUTY_BPS, day, 'stamp duty'), 'transfer_bps': _rate(TRANSFER_FEE_BPS, day, 'transfer fee')}


def effective_fee_bps(terms, moment, statutory):
    """Configured or rule-supplied fee terms, raised to the statutory floor when ``statutory`` is on (never double counted)."""
    tax, transfer = terms['sell_tax_bps'], terms['transfer_bps']
    if statutory:
        floor = statutory_fee_bps(moment)
        tax, transfer = max(tax, floor['sell_tax_bps']), max(transfer, floor['transfer_bps'])
    return tax, transfer


__all__ = ['FEE_SCHEDULE_VERSION', 'STAMP_DUTY_BPS', 'TRANSFER_FEE_BPS', 'effective_fee_bps', 'statutory_fee_bps']
