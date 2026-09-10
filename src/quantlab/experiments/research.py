"""Cross-sectional numeric factor research; returns are gross diagnostics.

Forward returns use close[t+h]/close[t]-1. They are prediction labels, not
fills: this engine makes no same-close execution or tradability claim.
"""

import math

import polars as pl


def finite_or_none(value):
    return float(value) if value is not None and math.isfinite(value) else None


def information_ratio(values: pl.Series):
    """Unannualized mean / sample std across finite cross-sectional ICs."""
    values = values.filter(values.is_finite())
    deviation = values.std(ddof=1)
    if deviation is None or deviation == 0:
        return None
    return finite_or_none(values.mean() / deviation)


class FactorResearchEngine:
    def evaluate(self, bars: pl.DataFrame, values: pl.DataFrame, mask: pl.DataFrame, horizons: tuple[int, ...], quantiles: int, *, boolean_factor: bool = False):
        # Delayed events need an event-time evaluator, not an implicit backdate.
        if values.filter(pl.col("available_at") != pl.col("datetime")).height:
            raise ValueError("This evaluator requires factors available at their bar close")
        labels = bars.sort("symbol", "datetime")
        for horizon in horizons:
            # Rolling [t+1, t+h], excluding the signal bar. Full window only.
            labels = labels.with_columns(
                pl.col('datetime').shift(-horizon).over('symbol').alias(f'label_end_{horizon}'),
                (pl.col('close').shift(-horizon).over('symbol') / pl.col('close').shift(-(horizon-1)).over('symbol') - 1).alias(f'decay_{horizon}'),
                (pl.col("close").shift(-horizon).over("symbol") / pl.col("close") - 1).alias(f"forward_{horizon}"),
                (pl.col("high").rolling_max(horizon).shift(-horizon).over("symbol") / pl.col("close") - 1).clip(lower_bound=0).alias(f"mfe_{horizon}"),
                (pl.col("low").rolling_min(horizon).shift(-horizon).over("symbol") / pl.col("close") - 1).clip(upper_bound=0).alias(f"mae_{horizon}"),
            )
        frame = values.join(labels.select("symbol", "datetime", *[f"{name}_{h}" for h in horizons for name in ("forward", "mfe", "mae", "decay", "label_end")]), on=["symbol", "datetime"], validate="1:1")
        frame = frame.join(mask, on=["symbol", "datetime"], how="left", validate="1:1")
        if frame["eligible"].null_count():
            raise ValueError("Universe mask must cover every input bar")
        frame = frame.filter(pl.col("eligible")).sort("datetime", "symbol")
        if boolean_factor and frame.filter(pl.col("value").is_not_null() & ~pl.col("value").is_in([0.0, 1.0])).height:
            raise ValueError("Boolean factor values must be 0, 1 or null")
        results = {}
        from quantlab.experiments.event_metrics import event_path_metrics, signal_turnover
        turnover = signal_turnover(frame, quantiles)
        for horizon in horizons:
            label = f"forward_{horizon}"
            valid = frame.filter(pl.col("value").is_not_null() & pl.col(label).is_not_null())
            correlations = valid.group_by("datetime", maintain_order=True).agg(
                pl.len().alias("n"),
                pl.corr("value", label).alias("ic"),
                pl.corr("value", label, method="spearman").alias("rank_ic"),
                pl.corr('value', f'decay_{horizon}').alias('decay_ic'),
                pl.corr('value', f'decay_{horizon}', method='spearman').alias('decay_rank_ic'),
            ).filter(pl.col("n") >= 3).sort("datetime")
            # Equal values stay together. Constant cross sections cannot form
            # quantiles and are excluded, instead of ranking by stock name.
            ranked = valid.with_columns(
                pl.col("value").rank("average").over("datetime").alias("rank"),
                pl.len().over("datetime").alias("n"),
                pl.col("value").n_unique().over("datetime").alias("unique"),
            ).filter((pl.col("n") >= quantiles) & (pl.col("unique") >= quantiles))
            ranked = ranked.with_columns((((pl.col("rank") - 1) / pl.col("n") * quantiles).floor().cast(pl.Int64) + 1).alias("quantile"))
            # First equal weight within each date, then across dates.
            daily = ranked.group_by("datetime", "quantile", maintain_order=True).agg(pl.col(label).mean().alias("mean_return")).sort("quantile", "datetime")
            qreturns = daily.group_by("quantile", maintain_order=True).agg(pl.col("mean_return").mean()).sort("quantile")
            paired = daily.filter(pl.col("quantile") == quantiles).select("datetime", pl.col("mean_return").alias("top")).join(
                daily.filter(pl.col("quantile") == 1).select("datetime", pl.col("mean_return").alias("bottom")),
                on="datetime", validate="1:1",
            ).sort("datetime")
            results[str(horizon)] = {
                "observations": valid.height,
                "eligible_bars": frame.height,
                "factor_coverage": finite_or_none(frame["value"].is_not_null().mean()),
                "labelled_coverage": valid.height / frame.height if frame.height else 0.0,
                "mean_forward_return": finite_or_none(valid[label].mean()),
                "median_forward_return": finite_or_none(valid[label].median()),
                "positive_return_rate": finite_or_none((valid[label] > 0).mean()),
                "ic": finite_or_none(correlations["ic"].filter(correlations["ic"].is_finite()).mean()),
                "rank_ic": finite_or_none(correlations["rank_ic"].filter(correlations["rank_ic"].is_finite()).mean()),
                "icir": information_ratio(correlations["ic"]),
                "rank_icir": information_ratio(correlations["rank_ic"]),
                "ic_dates": correlations.filter(pl.col("ic").is_finite()).height,
                "mean_mfe": finite_or_none(valid[f"mfe_{horizon}"].mean()),
                "mean_mae": finite_or_none(valid[f"mae_{horizon}"].mean()),
                "long_short_spread": finite_or_none((paired["top"] - paired["bottom"]).mean()),
                "long_short_dates": paired.height,
                "quantile_returns": qreturns.to_dicts(),
                'signal_turnover': turnover,
                'decay': {'lag_bars': horizon, 'ic': finite_or_none(correlations['decay_ic'].filter(correlations['decay_ic'].is_finite()).mean()),
                    'rank_ic': finite_or_none(correlations['decay_rank_ic'].filter(correlations['decay_rank_ic'].is_finite()).mean()),
                    'convention': 'Factor at t versus single-bar close return from t+h-1 to t+h, not cumulative forward return'},
            }
            if boolean_factor:
                triggered = valid.filter(pl.col("value") == 1)
                results[str(horizon)]["triggered"] = {
                    "event_count": frame.filter(pl.col("value") == 1).height,
                    "labelled_count": triggered.height,
                    "mean_forward_return": finite_or_none(triggered[label].mean()),
                    "positive_return_rate": finite_or_none((triggered[label] > 0).mean()),
                    "mean_mfe": finite_or_none(triggered[f"mfe_{horizon}"].mean()),
                    "mean_mae": finite_or_none(triggered[f"mae_{horizon}"].mean()),
                    'path_metrics': event_path_metrics(bars, triggered, horizon),
                }
        return results, frame
