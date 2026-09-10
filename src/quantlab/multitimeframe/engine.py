import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

import polars as pl

from quantlab.data.base import DataBatch, DataProvider, DataRequest
from quantlab.data.validation import ordered_bars
from quantlab.domain import Timeframe
from quantlab.factors.combinations import CombinationFactor
from quantlab.factors.engine import compute_factor
from quantlab.factors.registry import FactorRegistry
from quantlab.storage.codec import digest


def align_context(low: pl.DataFrame, context: pl.DataFrame) -> pl.DataFrame:
    """Use the latest available row, including null values; never skip missing.

    Equal information times are allowed across timeframes. Equal high-timeframe
    information times within a symbol are ambiguous and are rejected.
    """
    for frame in (low, context):
        for key in ("symbol", "datetime", "available_at"):
            if frame[key].null_count():
                raise ValueError("Null context key or information time")
        if frame.select(pl.struct("symbol", "datetime").is_duplicated().any()).item():
            raise ValueError("Duplicate context symbol/datetime")
        if frame.filter(pl.col("available_at") < pl.col("datetime")).height:
            raise ValueError("Context availability precedes bar time")
        for key in ("datetime", "available_at"):
            dtype = frame.schema[key]
            if not isinstance(dtype, pl.Datetime) or dtype.time_zone is None:
                raise ValueError("Context clocks must be timezone aware")
    if context.select(pl.struct("symbol", "available_at").is_duplicated().any()).item():
        raise ValueError("Ambiguous high-timeframe availability")
    if context.filter(pl.col("value").is_not_null() & ~pl.col("value").is_finite()).height:
        raise ValueError("Nonfinite context value")
    high = context.select("symbol", pl.col("datetime").alias("context_datetime"),
        pl.col("available_at").alias("context_available_at"), pl.col("value").alias("context_value"))
    return low.select("symbol", "datetime", "available_at").sort("available_at", "symbol").join_asof(
        high.sort("context_available_at", "symbol"), left_on="available_at", right_on="context_available_at",
        by="symbol", strategy="backward", check_sortedness=False).sort("symbol", "datetime")


@dataclass(frozen=True)
class ContextBatch:
    frame: pl.DataFrame
    manifest: dict
    context_id: str


class MultiTimeframeEngine:
    def __init__(self, provider: DataProvider, registry: FactorRegistry):
        self.provider = provider
        self.registry = registry

    def load(self, low: DataRequest, high: DataRequest, factor_id: str,
             version: str = "1.0.0", parameters: dict | None = None, *, low_batch: DataBatch | None = None) -> ContextBatch:
        if high.timeframe.minutes<=low.timeframe.minutes:
            raise ValueError('Context must have a higher timeframe')
        if set(low.symbols) != set(high.symbols):
            raise ValueError("Both timeframe requests must use the same symbols")
        if high.start > low.start or high.end < low.end:
            raise ValueError("Daily request must cover the low-timeframe interval; start earlier for warmup")
        factor = self.registry.get(factor_id, version)
        params = factor.parameters(parameters or {})
        low_batch = self.provider.load(low) if low_batch is None else low_batch
        high_batch = self.provider.load(high)
        if low_batch.snapshot.adjustment != high_batch.snapshot.adjustment:
            raise ValueError("Timeframes must use the same adjustment basis")
        low_bars, high_bars = ordered_bars(low_batch.bars), ordered_bars(high_batch.bars)
        if low_bars["timeframe"].unique().to_list() != [low.timeframe.value] or high_bars["timeframe"].unique().to_list() != [high.timeframe.value]:
            raise ValueError("Provider returned an unexpected timeframe")
        context = compute_factor(factor, high_bars, params)
        frame = align_context(low_bars, context)
        manifest = {"version": "1.0.0", "alignment": "latest_available_per_symbol_inclusive",
            "low_request": asdict(low), "high_request": asdict(high),
            "low_snapshot": asdict(low_batch.snapshot), "high_snapshot": asdict(high_batch.snapshot),
            "factor": asdict(factor.definition), "parameters": params, "factor_code_hash": self.registry.code_hash(factor),
            "alignment_code_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "output_hash": digest(frame.write_json())}
        if isinstance(factor, CombinationFactor):
            manifest["combination_inputs"] = factor.lineage(params)
        return ContextBatch(frame, manifest, digest(manifest))
