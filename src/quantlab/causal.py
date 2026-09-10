"""Small causal checks; a prefix check is evidence, not a general proof."""

import polars as pl
from polars.testing import assert_frame_equal

from quantlab.factors.engine import compute_factor


def assert_prefix_invariant(factor, bars: pl.DataFrame, parameters: dict, cutoffs) -> None:
    full = compute_factor(factor, bars, parameters)
    for cutoff in cutoffs:
        prefix = bars.filter(pl.col("available_at") <= cutoff)
        if prefix.is_empty():
            raise ValueError("Causal check requires nonempty prefix")
        observed = compute_factor(factor, prefix, parameters).filter(pl.col("available_at") <= cutoff)
        expected = full.filter(pl.col("available_at") <= cutoff)
        assert_frame_equal(observed, expected, check_exact=True)


def align_available(low: pl.DataFrame, high: pl.DataFrame) -> pl.DataFrame:
    """Attach last fully available high-timeframe context, per symbol.

    Both frames use available_at as the information clock. High values must
    already be confirmed. No forward fill from a later high-timeframe bar.
    """
    return low.sort("available_at").join_asof(
        high.sort("available_at"), on="available_at", by="symbol",
        strategy="backward", suffix="_context", check_sortedness=False,
    )
