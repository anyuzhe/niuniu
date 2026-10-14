"""Selection-bias corrections for strategy search: PSR / Deflated Sharpe, BH-FDR, CSCV-PBO.

Formulas follow Bailey & Lopez de Prado (2012, 2014) and Benjamini & Hochberg (1995). All
Sharpe ratios here are PER-PERIOD (not annualised); convert with sqrt(periods_per_year).
These are corrections for how many things were tried, not proofs of skill: they assume the
number of independent trials is known, which in practice is a judgement (see ``n_trials``).
"""
from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

import numpy as np

_NORMAL = NormalDist()
EULER_GAMMA = 0.5772156649015329


def sharpe_moments(returns) -> dict:
    """Per-period Sharpe, skewness, (non-excess) kurtosis and length of a return series."""
    r = np.asarray(returns, dtype=float)
    if r.ndim != 1 or r.size < 4 or not np.isfinite(r).all():
        raise ValueError("returns must be a finite 1-D series with at least 4 observations")
    mean, std = r.mean(), r.std(ddof=1)
    if std <= 0:
        raise ValueError("returns have zero variance")
    z = (r - mean) / r.std(ddof=0)
    return {"sharpe": float(mean / std), "skew": float((z ** 3).mean()), "kurtosis": float((z ** 4).mean()), "n_obs": int(r.size)}


def probabilistic_sharpe_ratio(sharpe: float, n_obs: int, skew: float = 0.0, kurtosis: float = 3.0,
                               benchmark: float = 0.0) -> float:
    """P(true per-period Sharpe > benchmark) given the observed one, with skew/kurtosis correction."""
    if n_obs < 2:
        raise ValueError("n_obs must be at least 2")
    denominator = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe ** 2
    if denominator <= 0:
        raise ValueError("Sharpe/skew/kurtosis combination is outside the estimator's domain")
    return _NORMAL.cdf((sharpe - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denominator))


def expected_max_sharpe(n_trials: int, sharpe_std: float) -> float:
    """Expected best per-period Sharpe among ``n_trials`` independent zero-skill trials.

    ``sharpe_std`` is the cross-trial standard deviation of the per-period Sharpe estimates.
    """
    if type(n_trials) is not int or n_trials < 1:
        raise ValueError("n_trials must be a positive integer")
    if not math.isfinite(sharpe_std) or sharpe_std < 0:
        raise ValueError("sharpe_std must be finite and non-negative")
    if n_trials == 1:
        return 0.0
    return sharpe_std * ((1 - EULER_GAMMA) * _NORMAL.inv_cdf(1 - 1 / n_trials)
                         + EULER_GAMMA * _NORMAL.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe_ratio(returns, n_trials: int, sharpe_std: float | None = None) -> dict:
    """PSR of the selected strategy against the Sharpe that pure luck would reach after ``n_trials``.

    ``sharpe_std`` defaults to the null standard error of one Sharpe estimate, 1/sqrt(n_obs-1)
    (zero-skill, i.i.d.), which is the right order of magnitude when the trials are noise.
    Pass the observed cross-trial dispersion when you have all trial returns.
    """
    m = sharpe_moments(returns)
    sigma = 1.0 / math.sqrt(m["n_obs"] - 1) if sharpe_std is None else sharpe_std
    hurdle = expected_max_sharpe(n_trials, sigma)
    return {**m, "n_trials": n_trials, "sharpe_std": sigma, "luck_hurdle": hurdle,
            "dsr": probabilistic_sharpe_ratio(m["sharpe"], m["n_obs"], m["skew"], m["kurtosis"], hurdle),
            "psr_vs_zero": probabilistic_sharpe_ratio(m["sharpe"], m["n_obs"], m["skew"], m["kurtosis"], 0.0)}


def benjamini_hochberg(p_values, alpha: float = 0.05) -> dict:
    """BH false-discovery-rate adjustment; ``None`` p-values keep their slot in m (as in ``holm``)."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    if any(p is not None and (not math.isfinite(p) or not 0 <= p <= 1) for p in p_values):
        raise ValueError("p-values must be in [0, 1] or null")
    m = len(p_values)
    q = [None] * m
    ordered = sorted((p, i) for i, p in enumerate(p_values) if p is not None)
    running = 1.0
    for rank in range(len(ordered), 0, -1):
        p, i = ordered[rank - 1]
        running = min(running, p * m / rank)
        q[i] = running
    return {"q_values": q, "reject": [None if v is None else v <= alpha for v in q], "alpha": alpha, "m": m}


def probability_of_backtest_overfitting(returns_matrix, n_splits: int = 16) -> dict:
    """CSCV-PBO: how often the in-sample best variant ranks in the bottom half out-of-sample.

    ``returns_matrix`` is (periods x variants) of per-period returns for EVERY variant that was
    tried, aligned in time. Rows are cut into ``n_splits`` contiguous blocks; every way of
    picking half the blocks as in-sample is evaluated (C(16,8)=12870 by default).
    """
    x = np.asarray(returns_matrix, dtype=float)
    if x.ndim != 2 or x.shape[1] < 2 or not np.isfinite(x).all():
        raise ValueError("returns_matrix must be a finite (periods x variants) array with >= 2 variants")
    if n_splits < 4 or n_splits % 2:
        raise ValueError("n_splits must be an even number >= 4")
    per_block = x.shape[0] // n_splits
    if per_block < 5:
        raise ValueError("too few periods for this many splits")
    x = x[: per_block * n_splits]
    blocks = x.reshape(n_splits, per_block, -1)
    s1, s2 = blocks.sum(axis=1), (blocks ** 2).sum(axis=1)      # (n_splits, variants)
    n_variants = x.shape[1]
    half = n_splits // 2

    def sharpe(idx):
        n = per_block * len(idx)
        mean = s1[idx].sum(axis=0) / n
        var = (s2[idx].sum(axis=0) - n * mean ** 2) / (n - 1)
        return np.where(var > 0, mean / np.sqrt(np.where(var > 0, var, 1.0)), -np.inf)

    logits, is_best, oos_of_best = [], [], []
    everything = set(range(n_splits))
    for chosen in combinations(range(n_splits), half):
        train = list(chosen)
        test = sorted(everything - set(chosen))
        s_train, s_test = sharpe(train), sharpe(test)
        best = int(np.argmax(s_train))
        rank = int((s_test < s_test[best]).sum()) + 1            # 1 = worst ... n_variants = best
        omega = rank / (n_variants + 1)
        logits.append(math.log(omega / (1 - omega)))
        is_best.append(float(s_train[best]))
        oos_of_best.append(float(s_test[best]))
    logits = np.asarray(logits)
    return {"pbo": float((logits <= 0).mean()), "n_combinations": int(logits.size), "n_variants": n_variants,
            "mean_in_sample_best_sharpe": float(np.mean(is_best)), "mean_out_of_sample_sharpe_of_that_variant": float(np.mean(oos_of_best)),
            "share_out_of_sample_loss": float((np.asarray(oos_of_best) < 0).mean())}
