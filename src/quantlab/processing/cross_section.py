import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

import polars as pl


@dataclass(frozen=True)
class CrossSectionConfig:
    method: str = "cs_rank"

    def __post_init__(self):
        if self.method not in ("cs_rank", "cs_zscore"):
            raise ValueError("Unknown cross-sectional processor")


def processing_manifest(config: CrossSectionConfig) -> dict:
    return {"version": "1.0.0", "parameters": asdict(config), "fit_period": None,
        "scope": "eligible_universe_before_regime_filter",
        "code_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def transform_cross_section(values: pl.DataFrame, mask: pl.DataFrame, config: CrossSectionConfig) -> pl.DataFrame:
    """Stateless transform within each timestamp; no historical fitting.

    Rank uses (average_rank - 0.5) / n; z-score uses population std.
    Constant sections map to 0.5 (rank) or 0 (z-score). Missing stays missing.
    """
    joined = values.join(mask.select("symbol", "datetime", "eligible"), on=["symbol", "datetime"], how="left", validate="1:1")
    if joined["eligible"].null_count():
        raise ValueError("Universe mask must cover every factor row")
    selected = joined.filter(pl.col("eligible") & pl.col("value").is_not_null()).sort("datetime", "symbol")
    if selected.filter(~pl.col("value").is_finite()).height:
        raise ValueError("Nonfinite processor input")
    value = pl.col("value")
    if config.method == "cs_rank":
        transformed = (value.rank("average").over("datetime") - 0.5) / pl.len().over("datetime")
    else:
        deviation = value.std(ddof=0).over("datetime")
        transformed = pl.when(deviation == 0).then(0.0).otherwise((value - value.mean().over("datetime")) / deviation)
    selected = selected.select("symbol", "datetime", transformed.alias("processed_value"),
        pl.col("available_at").max().over("datetime").alias("processed_available_at"))
    output = values.join(selected, on=["symbol", "datetime"], how="left", validate="1:1")
    return output.select("symbol", "datetime",
        pl.coalesce("processed_available_at", "available_at").alias("available_at"),
        pl.col("processed_value").cast(pl.Float64).alias("value")).sort("symbol", "datetime")
