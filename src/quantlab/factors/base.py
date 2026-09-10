from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping

import polars as pl

from quantlab.domain import FactorType, Timeframe


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    version: str
    name_cn: str
    category: str
    factor_type: FactorType
    required_fields: tuple[str, ...]
    timeframes: tuple[Timeframe, ...]
    description: str
    formula: str
    causal: bool = True
    lookahead_risk: str = "low"
    tags: tuple[str, ...] = ()
    source_theory: tuple[str, ...] = ()
    available_at_rule: str = "bar close"


class Factor(ABC):
    definition: FactorDefinition

    @abstractmethod
    def parameters(self, supplied: Mapping[str, Any]) -> dict[str, Any]:
        """Validate parameters and fill defaults."""

    @abstractmethod
    def compute(self, bars: pl.DataFrame, parameters: Mapping[str, Any]) -> pl.DataFrame:
        """Return exactly symbol, datetime, available_at, value; null is warmup."""


class ExpressionFactor(Factor):
    @abstractmethod
    def expression(self, parameters: Mapping[str, Any]) -> pl.Expr:
        """Use symbol-scoped rolling/shift operations; never eval user strings."""

    def compute(self, bars: pl.DataFrame, parameters: Mapping[str, Any]) -> pl.DataFrame:
        return bars.select("symbol", "datetime", "available_at", self.expression(parameters).alias("value"))


class ComputedFactor(Factor):
    """Explicit algorithm path with the same output contract as expressions."""
