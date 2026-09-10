import math
import random
from dataclasses import dataclass

import polars as pl

from quantlab.storage.codec import digest


@dataclass(frozen=True)
class BootstrapConfig:
    resamples: int = 1000
    block_days: int = 5
    confidence: float = 0.95

    def __post_init__(self):
        if type(self.resamples) is not int or self.resamples < 20:
            raise ValueError("Bootstrap requires at least 20 resamples")
        if type(self.block_days) is not int or self.block_days < 1:
            raise ValueError("Bootstrap block_days must be positive")
        if type(self.confidence) not in (int, float) or not math.isfinite(self.confidence) or not 0 < self.confidence < 1:
            raise ValueError("Bootstrap confidence must be in (0, 1)")


def percentile(sorted_values, probability):
    index = (len(sorted_values) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (index - lower)


def block_mean_interval(values: list[float | None], config: BootstrapConfig, seed: int) -> dict:
    """Circular moving blocks on the observed-date grid; None stays missing."""
    if type(seed) is not int:
        raise ValueError("Bootstrap seed must be an integer")
    if any(value is not None and not math.isfinite(value) for value in values):
        raise ValueError("Nonfinite bootstrap input")
    valid = [value for value in values if value is not None]
    result = {"method": "circular_date_block_percentile_v1", "status": "unavailable", "reason": None,
        "observed_days": len(values), "valid_days": len(valid), "block_days": config.block_days,
        "confidence": config.confidence, "resamples_requested": config.resamples, "resamples_used": 0,
        "seed": seed, "estimate": math.fsum(valid) / len(valid) if valid else None, "ci_low": None, "ci_high": None}
    # Require two blocks' worth of valid dates; do not silently shorten blocks.
    if len(valid) < 2 * config.block_days:
        result["reason"] = "insufficient_valid_days_for_two_blocks"
        return result
    rng = random.Random(seed)
    n = len(values)
    estimates = []
    for _ in range(config.resamples):
        if _%100==0:
            from quantlab.progress import checkpoint
            checkpoint()
        sampled = []
        drawn = 0
        while drawn < n:
            start = rng.randrange(n)
            length = min(config.block_days, n - drawn)
            sampled.extend(values[(start + i) % n] for i in range(length))
            drawn += length
        observed = [value for value in sampled if value is not None]
        if observed:
            estimates.append(math.fsum(observed) / len(observed))
    result["resamples_used"] = len(estimates)
    if len(estimates) < 20:
        result["reason"] = "insufficient_nonempty_resamples"
        return result
    estimates.sort()
    tail = (1 - config.confidence) / 2
    result.update({"status": "computed", "ci_low": percentile(estimates, tail), "ci_high": percentile(estimates, 1-tail)})
    return result


def bootstrap_statistics(observations: pl.DataFrame, horizons: tuple[int, ...], config: BootstrapConfig, seed: int, *, boolean_factor: bool = False) -> dict:
    frame = observations.sort("datetime", "symbol").with_columns(pl.col("datetime").dt.date().alias("date"))
    dates = frame.select("date").unique().sort("date")
    result = {}
    for horizon in horizons:
        label = f"forward_{horizon}"
        valid = frame.filter(pl.col("value").is_not_null() & pl.col(label).is_not_null())
        daily_returns = valid.group_by("date", maintain_order=True).agg(pl.col(label).mean().alias("value"))
        correlations = valid.group_by("datetime", maintain_order=True).agg(
            pl.len().alias("n"), pl.corr("value", label).alias("ic"),
            pl.corr("value", label, method="spearman").alias("rank_ic"),
        ).filter(pl.col("n") >= 3).with_columns(pl.col("datetime").dt.date().alias("date"))
        series = {"daily_mean_forward_return": daily_returns}
        for key in ("ic", "rank_ic"):
            series[f"daily_mean_{key}"] = correlations.filter(pl.col(key).is_finite()).group_by("date", maintain_order=True).agg(pl.col(key).mean().alias("value"))
        if boolean_factor:
            series["triggered_daily_mean_forward_return"] = valid.filter(pl.col("value") == 1).group_by("date", maintain_order=True).agg(pl.col(label).mean().alias("value"))
        result[str(horizon)] = {}
        for metric, daily in series.items():
            values = dates.join(daily, on="date", how="left", validate="1:1").sort("date")["value"].to_list()
            stream_seed = int(digest({"seed": seed, "horizon": horizon, "metric": metric}), 16)
            result[str(horizon)][metric] = block_mean_interval(values, config, stream_seed)
    return result
