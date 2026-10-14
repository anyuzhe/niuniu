"""Minimal registry shim for the vendored GTJA191 batches.

Reduced from aurumq-rl `factors/registry.py` (MIT, Copyright (c) 2026 Paris Yu): only what the batch
modules need. Registered implementations are wrapped so +-inf becomes null and finite values are clipped
to +-1e6, exactly as upstream does; this is part of the factor definition and is disclosed in PROVENANCE.md.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field

import polars as pl

FACTOR_CLIP_LIMIT = 1.0e6
GTJA191_REGISTRY: dict[str, "FactorEntry"] = {}


def sanitize_factor_series(series: pl.Series) -> pl.Series:
    if series.dtype != pl.Float64:
        series = series.cast(pl.Float64, strict=False)
    name = series.name
    return pl.DataFrame({name: series}).with_columns(
        pl.when(pl.col(name).is_infinite()).then(None)
        .otherwise(pl.col(name).clip(-FACTOR_CLIP_LIMIT, FACTOR_CLIP_LIMIT)).alias(name))[name]


def _wrap(impl):
    def sanitized(df):
        return sanitize_factor_series(impl(df))
    sanitized.__name__ = getattr(impl, "__name__", "sanitized")
    sanitized.__doc__ = getattr(impl, "__doc__", None)
    sanitized.__wrapped__ = impl
    return sanitized


@dataclass(frozen=True)
class FactorEntry:
    id: str
    impl: Callable
    direction: str
    category: str
    description: str
    legacy_aqml_expr: str | None = None
    quality_flag: int = 0
    references: tuple = field(default_factory=tuple)
    formula_doc_path: str = ""


def register_gtja191(entry: FactorEntry) -> FactorEntry:
    wrapped = dataclasses.replace(entry, impl=_wrap(entry.impl))
    existing = GTJA191_REGISTRY.get(entry.id)
    if existing is not None and getattr(existing.impl, "__wrapped__", existing.impl) is not entry.impl:
        raise ValueError(f"gtja191 factor {entry.id!r} already registered with a different entry")
    GTJA191_REGISTRY[entry.id] = wrapped
    return wrapped
