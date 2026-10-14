"""Uncertainty around a backtest's headline numbers: circular block bootstrap of the daily return series.

A Sharpe ratio from one backtest is a point estimate with a wide error bar; this puts the bar on it.
Returns are resampled in circular blocks so serial correlation (rolling holding cohorts make daily
returns strongly autocorrelated) is kept; ``block_sensitivity`` shows how much the answer depends on
the block length. This measures sampling noise of THIS return series only: it does not correct for
how many strategies were tried (see ``multiple_testing``) and it is not a forecast.
"""
from __future__ import annotations

import math

import numpy as np
import polars as pl

from quantlab.statistics.multiple_testing import probabilistic_sharpe_ratio, sharpe_moments

DEFAULT_SEED = 20261014


def daily_returns(curve: pl.DataFrame, initial_cash: float) -> np.ndarray:
    """Daily close-to-close returns with the engine's own convention (``execution.performance``)."""
    daily = (curve.sort("datetime").with_columns(pl.col("datetime").dt.date().alias("date"))
             .group_by("date", maintain_order=True).agg(pl.col("equity").last()))
    equity = np.concatenate([[float(initial_cash)], daily["equity"].to_numpy().astype(float)])
    if (equity[:-1] <= 0).any() or not np.isfinite(equity).all():
        raise ValueError("nonpositive or nonfinite equity")
    return equity[1:] / equity[:-1] - 1.0


def _metrics(paths: np.ndarray, periods_per_year: int) -> dict:
    """Per-row Sharpe, annualised geometric return and max drawdown of return paths (rows x days)."""
    n = paths.shape[1]
    std = paths.std(axis=1, ddof=1)
    sharpe = np.where(std > 0, paths.mean(axis=1) / np.where(std > 0, std, 1.0) * math.sqrt(periods_per_year), np.nan)
    growth = np.cumprod(1.0 + paths, axis=1)
    annual = np.expm1(np.log(growth[:, -1]) * periods_per_year / n)
    peak = np.maximum.accumulate(np.concatenate([np.ones((paths.shape[0], 1)), growth], axis=1), axis=1)[:, 1:]
    drawdown = (growth / peak - 1.0).min(axis=1)
    return {"sharpe": sharpe, "annual_return": annual, "max_drawdown": drawdown}


def _blocks(returns: np.ndarray, block_days: int, resamples: int, rng: np.random.Generator) -> np.ndarray:
    n = returns.size
    count = math.ceil(n / block_days)
    starts = rng.integers(0, n, size=(resamples, count))
    index = (starts[:, :, None] + np.arange(block_days)[None, None, :]) % n
    return returns[index.reshape(resamples, -1)[:, :n]]


def bootstrap_performance(returns, *, block_days: int = 10, resamples: int = 2000, confidence: float = 0.95,
                          seed: int = DEFAULT_SEED, periods_per_year: int = 252) -> dict:
    """Percentile intervals for annualised Sharpe / return / max drawdown, and a Sharpe>0 p-value.

    The p-value resamples the DEMEANED series (null: zero mean, same volatility and dependence)
    and reports P(null Sharpe >= observed), one-sided with the +1 correction.
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim != 1 or r.size < 30 or not np.isfinite(r).all() or (r <= -1).any():
        raise ValueError("returns must be a finite 1-D series of at least 30 daily returns above -100%")
    if type(block_days) is not int or not 1 <= block_days <= r.size // 2:
        raise ValueError("block_days must be an integer between 1 and half the series length")
    if type(resamples) is not int or resamples < 200 or not 0 < confidence < 1 or type(seed) is not int:
        raise ValueError("resamples must be an integer >= 200, confidence in (0, 1), seed an integer")
    rng = np.random.default_rng(seed)
    observed = {k: float(v[0]) for k, v in _metrics(r[None, :], periods_per_year).items()}
    boot = _metrics(_blocks(r, block_days, resamples, rng), periods_per_year)
    null = _metrics(_blocks(r - r.mean(), block_days, resamples, rng), periods_per_year)["sharpe"]
    tail = (1 - confidence) / 2 * 100
    intervals = {k: [float(np.nanpercentile(v, tail)), float(np.nanpercentile(v, 100 - tail))] for k, v in boot.items()}
    m = sharpe_moments(r)
    return {"method": "circular_block_bootstrap_v1", "n_days": int(r.size), "block_days": block_days, "resamples": resamples,
            "confidence": confidence, "seed": seed, "periods_per_year": periods_per_year, "observed": observed, "intervals": intervals,
            "p_sharpe_not_above_zero": float((1 + np.nansum(null >= observed["sharpe"])) / (1 + np.isfinite(null).sum())),
            "iid_psr_vs_zero": probabilistic_sharpe_ratio(m["sharpe"], m["n_obs"], m["skew"], m["kurtosis"]),
            "limits": "Sampling noise of this one return series only; does not account for strategies tried, regime change or costs not modelled."}


def block_sensitivity(returns, blocks=(1, 5, 10, 20, 40, 60), **options) -> list[dict]:
    """Sharpe interval for several block lengths; if it keeps widening, the dependence is long."""
    rows = []
    for block in blocks:
        result = bootstrap_performance(returns, block_days=block, **options)
        low, high = result["intervals"]["sharpe"]
        rows.append({"block_days": block, "sharpe_low": low, "sharpe_high": high, "width": high - low,
                     "p_sharpe_not_above_zero": result["p_sharpe_not_above_zero"]})
    return rows
