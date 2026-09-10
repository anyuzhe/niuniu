from dataclasses import dataclass
from datetime import date
from typing import Protocol

import polars as pl

from quantlab.domain import Timeframe


@dataclass(frozen=True)
class DataRequest:
    symbols: tuple[str, ...]
    timeframe: Timeframe
    start: date
    end: date

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Provide nonempty, unique symbols")
        if self.start > self.end:
            raise ValueError("start must not exceed end")


@dataclass(frozen=True)
class DataSnapshot:
    snapshot_id: str
    source: str
    adjustment: str
    files: tuple[dict, ...]


@dataclass(frozen=True)
class DataBatch:
    bars: pl.DataFrame
    snapshot: DataSnapshot


class DataProvider(Protocol):
    def load(self, request: DataRequest) -> DataBatch: ...


class UniverseProvider(Protocol):
    universe_id: str
    version: str

    def mask(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Return symbol, datetime, eligible; historical state only."""
        ...


@dataclass(frozen=True)
class ExplicitUniverse:
    """User-selected research universe, NOT a historical tradability universe."""

    symbols: tuple[str, ...]
    universe_id: str = "explicit_symbols"
    version: str = "1.0.0"

    def mask(self, bars: pl.DataFrame) -> pl.DataFrame:
        return bars.select("symbol", "datetime", pl.col("symbol").is_in(self.symbols).alias("eligible"))
