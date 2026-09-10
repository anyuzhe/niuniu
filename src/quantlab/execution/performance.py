"""Daily close-to-close account performance, after modeled costs.

Intraday observations are collapsed to the last observed close of each local
trading date. The first return starts at initial cash. No missing dates are
fabricated. Annualization uses 252 observed trading days, zero risk-free rate.
"""
import math
import statistics

import polars as pl


def performance_metrics(curve, initial_cash):
    daily = curve.sort('datetime').with_columns(pl.col('datetime').dt.date().alias('date')).group_by('date', maintain_order=True).agg(pl.col('equity').last())
    previous = float(initial_cash)
    returns = []
    for equity in daily['equity']:
        if previous <= 0 or not math.isfinite(equity):
            return {'sharpe': None, 'performance_status': 'nonpositive_previous_equity'}
        returns.append(equity / previous - 1)
        previous = equity
    sd = statistics.stdev(returns) if len(returns) > 1 else 0.0
    annualized = None
    if returns and previous > 0:
        exponent = math.log(previous / initial_cash) * 252 / len(returns)
        if exponent < 709:annualized = math.expm1(exponent)
    return {
        'sharpe': statistics.mean(returns) / sd * math.sqrt(252) if sd > 0 else None,
        'annualized_volatility': sd * math.sqrt(252) if len(returns) > 1 else None,
        'annualized_return': annualized,
        'performance_days': len(returns),
        'performance_status': 'computed' if sd > 0 else 'insufficient_days_or_zero_variance',
        'performance_convention': 'Last observed close per local date; first return from initial cash; net of modeled costs; 252 days/year; risk-free=0; sample standard deviation; no missing-date fill.'}
