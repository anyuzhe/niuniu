"""Extension contracts, not placeholder implementations of trading theories.

Engines consume already available inputs; replay/orchestration owns time slicing.
Concrete theory algorithms will be implemented and tested in their own modules.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

import polars as pl

from quantlab.domain import Event, MarketState, SequenceMatch, Signal, Structure, Zone


class EventEngine(Protocol):
    def detect(self, bars: pl.DataFrame) -> Sequence[Event]: ...


class ZoneEngine(Protocol):
    def detect(self, bars: pl.DataFrame, events: Sequence[Event]) -> Sequence[Zone]: ...


class StructureEngine(Protocol):
    def detect(self, bars: pl.DataFrame) -> Sequence[Structure]: ...


class RegimeEngine(Protocol):
    def classify(self, factors: pl.DataFrame) -> Sequence[MarketState]: ...


class SequenceEngine(Protocol):
    """Implementations must enforce ordering, timeout and invalidation."""

    def advance(self, events: Sequence[Event], as_of: datetime) -> Sequence[SequenceMatch]: ...


class FittedProcessor(Protocol):
    fit_start: datetime
    fit_end: datetime
    version: str

    def transform(self, values: pl.DataFrame) -> pl.DataFrame: ...


class Processor(Protocol):
    def fit(self, training_values: pl.DataFrame) -> FittedProcessor: ...


class SignalModel(Protocol):
    def predict(self, factors: pl.DataFrame, experiment_id: str) -> Sequence[Signal]: ...


class PortfolioBuilder(Protocol):
    def target_weights(self, signals: Sequence[Signal]) -> dict[str, float]: ...


class RiskPolicy(Protocol):
    def constrain(self, weights: dict[str, float], as_of: datetime) -> dict[str, float]: ...


class ExecutionBacktester(Protocol):
    """Separate from statistical factor evaluation; owns fills and costs."""

    def run(self, targets: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame: ...
