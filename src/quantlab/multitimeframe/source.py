"""Reuse a daily snapshot across study children with bounded prefix requests."""

from dataclasses import asdict, dataclass

import polars as pl

from quantlab.data.base import DataBatch, DataProvider, DataRequest, DataSnapshot
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest


@dataclass(frozen=True)
class ContextSource:
    low: DataProvider
    daily: DataBatch
    request: DataRequest

    def load(self, request):
        if request.timeframe != self.request.timeframe:
            return self.low.load(request)
        if request.symbols != self.request.symbols or request.start != self.request.start or not request.start <= request.end <= self.request.end:
            raise ValueError("Daily context child must request a bounded prefix")
        if request == self.request:
            return self.daily
        bars = self.daily.bars.filter(pl.col("datetime").dt.date() <= request.end)
        source = self.daily.snapshot
        return DataBatch(bars, DataSnapshot(digest({"parent_snapshot": source.snapshot_id, "prefix_request": request}),
            source.source + ":context_prefix", source.adjustment, source.files))


def with_context_source(low, source, config, manifest):
    if config.context is None:
        return low
    request = config.context.request(config.data)
    daily = source.load(request)
    manifest["context_data_snapshot"] = asdict(daily.snapshot)
    return ContextSource(low, daily, request)
