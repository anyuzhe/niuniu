"""Shared domain objects; all information times must be timezone aware."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Timeframe(str, Enum):
    DAILY = "1d"
    MIN5 = "5m"
    MIN1 = "1m"
    MIN15 = "15m"
    MIN30 = "30m"
    MIN60 = "60m"

    @property
    def minutes(self):
        return 1440 if self==Timeframe.DAILY else int(self.value[:-1])


class FactorType(str, Enum):
    SCALAR = "scalar"
    BOOLEAN = "boolean"
    EVENT = "event"
    STATE = "state"
    PROBABILITY = "probability"
    ZONE = "zone"
    STRUCTURE = "structure"
    SEQUENCE = "sequence"
    UNIVERSE = "universe"


def information_time(occurred_at: datetime, available_at: datetime) -> None:
    if any(t.tzinfo is None or t.utcoffset() is None for t in (occurred_at, available_at)):
        raise ValueError("Information timestamps must be timezone aware")
    if available_at < occurred_at:
        raise ValueError("available_at cannot precede occurred_at")


@dataclass(frozen=True)
class Event:
    event_id: str
    factor_id: str
    symbol: str
    timeframe: Timeframe
    occurred_at: datetime
    available_at: datetime
    direction: int = 0
    strength: float = 0.0
    confirmed_at: datetime | None = None
    version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        information_time(self.occurred_at, self.available_at)
        if self.confirmed_at is not None:
            information_time(self.occurred_at, self.confirmed_at)


@dataclass(frozen=True)
class Zone:
    zone_id: str
    kind: str
    symbol: str
    timeframe: Timeframe
    created_at: datetime
    available_at: datetime
    lower_price: float
    upper_price: float
    direction: int = 0
    invalidated_at: datetime | None = None
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        information_time(self.created_at, self.available_at)
        if not self.lower_price <= self.upper_price:
            raise ValueError("Invalid zone bounds")
        if self.invalidated_at is not None:
            information_time(self.available_at, self.invalidated_at)


@dataclass(frozen=True)
class ZoneUpdate:
    """Append-only observation; never mutate a zone's creation record."""

    zone_id: str
    available_at: datetime
    touch_count: int
    filled_ratio: float
    status: str

    def __post_init__(self) -> None:
        information_time(self.available_at, self.available_at)
        if type(self.touch_count) is not int or self.touch_count < 0:
            raise ValueError("touch_count must be a nonnegative integer")
        if not 0 <= self.filled_ratio <= 1:
            raise ValueError("filled_ratio must be in [0, 1]")
        if self.status not in {"active", "filled", "invalidated"}:
            raise ValueError("Invalid zone status")


@dataclass(frozen=True)
class Structure:
    structure_id: str
    kind: str
    symbol: str
    timeframe: Timeframe
    occurred_at: datetime
    available_at: datetime
    components: tuple[str, ...] = ()
    price: float | None = None
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        information_time(self.occurred_at, self.available_at)


@dataclass(frozen=True)
class MarketState:
    symbol: str
    timeframe: Timeframe
    occurred_at: datetime
    available_at: datetime
    direction: str
    structure: str
    volatility: str
    liquidity: str
    version: str

    def __post_init__(self) -> None:
        information_time(self.occurred_at, self.available_at)


@dataclass(frozen=True)
class SequenceMatch:
    sequence_id: str
    version: str
    symbol: str
    event_ids: tuple[str, ...]
    occurred_at: datetime
    available_at: datetime
    status: str
    match_id: str = ""
    timeframe: Timeframe | None = None
    invalidating_event_id: str | None = None

    def __post_init__(self) -> None:
        information_time(self.occurred_at, self.available_at)


@dataclass(frozen=True)
class Signal:
    """A research signal is not an order."""

    symbol: str
    available_at: datetime
    score: float
    experiment_id: str
