"""Source-independent validation of normalized bars."""

import polars as pl


def validate_bars(bars: pl.DataFrame) -> None:
    if bars.is_empty():
        raise ValueError("No bars in requested interval")
    required = ["symbol", "datetime", "available_at", "open", "high", "low", "close", "volume", "turnover"]
    if any(bars[c].null_count() for c in required):
        raise ValueError("Null in required bar field")
    if bars.select(pl.struct("symbol", "datetime").is_duplicated().any()).item():
        raise ValueError("Duplicate symbol/datetime")
    invalid = bars.filter(
        pl.any_horizontal([~pl.col(c).is_finite() for c in ["open", "high", "low", "close", "volume", "turnover"]])
        | (pl.min_horizontal("open", "high", "low", "close") <= 0)
        | (pl.col("high") < pl.max_horizontal("open", "low", "close"))
        | (pl.col("low") > pl.min_horizontal("open", "high", "close"))
        | (pl.col("volume") < 0) | (pl.col("turnover") < 0)
        | (pl.col("available_at") < pl.col("datetime"))
    )
    if invalid.height:
        raise ValueError(f"Invalid OHLCV/time in {invalid.height} bars")


def ordered_bars(bars: pl.DataFrame) -> pl.DataFrame:
    validate_bars(bars)
    if bars["timeframe"].n_unique() != 1:
        raise ValueError("Detect one timeframe at a time")
    ordered = bars.sort("symbol", "datetime")
    if ordered.filter(pl.col("available_at").diff().over("symbol") < pl.duration()).height:
        raise ValueError("Bar availability must be nondecreasing")
    return ordered


