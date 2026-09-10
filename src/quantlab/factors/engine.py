import polars as pl

from quantlab.domain import FactorType, Timeframe
from quantlab.factors.base import Factor


def compute_factor(factor: Factor, bars: pl.DataFrame, parameters: dict) -> pl.DataFrame:
    from quantlab.progress import checkpoint
    checkpoint('因子计算 '+factor.definition.factor_id)
    cache=getattr(factor,'_persistent_cache',None)
    if cache is not None and not getattr(factor,'caches_structures',False):
        return cache.compute(factor,bars.sort('symbol','datetime'),parameters,
            lambda:_compute_factor(factor,bars,parameters))
    return _compute_factor(factor,bars,parameters)


def _compute_factor(factor: Factor, bars: pl.DataFrame, parameters: dict) -> pl.DataFrame:
    definition = factor.definition
    if not definition.causal or definition.lookahead_risk not in {"none", "low"}:
        raise ValueError("Non-causal or unaudited high-risk factor is not allowed")
    if definition.factor_type not in {FactorType.SCALAR, FactorType.BOOLEAN, FactorType.PROBABILITY}:
        raise ValueError("Numeric research engine does not accept object-valued factors")
    if set(definition.required_fields) - set(bars.columns):
        raise ValueError("Missing required factor fields")
    if any(Timeframe(t) not in definition.timeframes for t in bars["timeframe"].unique()):
        raise ValueError("Unsupported factor timeframe")
    output = factor.compute(bars.sort("symbol", "datetime"), parameters)
    if set(output.columns) != {"symbol", "datetime", "available_at", "value"}:
        raise ValueError("Invalid factor output schema")
    if output.height != bars.height or output.select(pl.struct("symbol", "datetime").is_duplicated().any()).item():
        raise ValueError("Factor must return one row per input bar")
    if any(output[c].null_count() for c in ["symbol", "datetime", "available_at"]):
        raise ValueError("Null factor key or information time")
    joined = output.join(bars.select("symbol", "datetime", pl.col("available_at").alias("bar_available_at")), on=["symbol", "datetime"], how="left", validate="1:1")
    if joined["bar_available_at"].null_count() or joined.filter(pl.col("available_at") < pl.col("bar_available_at")).height:
        raise ValueError("Invalid factor keys or early availability")
    output = output.with_columns(pl.col("value").cast(pl.Float64))
    if output.filter(pl.col("value").is_not_null() & ~pl.col("value").is_finite()).height:
        raise ValueError("Nonfinite factor values")
    return output.sort("symbol", "datetime")
