import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RegimeConfig:
    lookback: int = 20
    baseline_window: int = 20
    direction_threshold: float = 0.3
    range_threshold: float = 0.2
    trend_threshold: float = 0.6
    volatility_low: float = 0.75
    volatility_high: float = 1.5

    def __post_init__(self):
        if type(self.lookback) is not int or self.lookback < 2:
            raise ValueError("Regime lookback must be >= 2")
        if type(self.baseline_window) is not int or self.baseline_window < 1:
            raise ValueError("baseline_window must be positive")
        thresholds = (self.direction_threshold, self.range_threshold, self.trend_threshold, self.volatility_low, self.volatility_high)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in thresholds):
            raise ValueError("Regime thresholds must be finite numbers")
        if not 0 < self.direction_threshold <= 1:
            raise ValueError("direction_threshold must be in (0, 1]")
        if not 0 <= self.range_threshold < self.trend_threshold <= 1:
            raise ValueError("Require 0 <= range_threshold < trend_threshold <= 1")
        if not 0 < self.volatility_low < self.volatility_high:
            raise ValueError("Require 0 < volatility_low < volatility_high")


@dataclass(frozen=True)
class RegimeFilter:
    direction: str | None = None
    structure: str | None = None
    volatility: str | None = None
    liquidity: str | None = None
    breadth: str | None = None

    def __post_init__(self):
        for name, allowed in {
            "direction": {"Bull", "Bear", "Neutral"},
            "structure": {"Trend", "Range", "Transition"},
            "volatility": {"Low", "Medium", "High"},
            "liquidity": {"Low", "Medium", "High"},
            "breadth": {"Expansion", "Contraction", "Balanced"},
        }.items():
            value = getattr(self, name)
            if value is not None and value not in allowed:
                raise ValueError(f"Invalid regime {name}: {value}")
        if all(value is None for value in (self.direction, self.structure, self.volatility,self.liquidity,self.breadth)):
            raise ValueError("Specify at least one regime filter")
