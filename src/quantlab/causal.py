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


# ---------------------------------------------------------------------------
# Registry-wide audit: structured, non-raising counterpart of the helper above.
# ---------------------------------------------------------------------------
_PRICE_FIELDS = ("open", "high", "low", "close")
_VOLUME_FIELDS = ("volume", "turnover", "amount")


def _tamper_future(bars: pl.DataFrame, cutoff) -> pl.DataFrame:
    """Rescale every bar after ``cutoff`` so any leak of future values shows up."""
    future = pl.col("available_at") > cutoff
    prices = [pl.when(future).then(pl.col(c) * 1.37).otherwise(pl.col(c)).alias(c) for c in _PRICE_FIELDS if c in bars.columns]
    volumes = [pl.when(future).then(pl.col(c) * 2.5).otherwise(pl.col(c)).alias(c) for c in _VOLUME_FIELDS if c in bars.columns]
    return bars.with_columns(*prices, *volumes)


def _diff(expected: pl.DataFrame, observed: pl.DataFrame, tolerance: float) -> tuple[int, dict | None]:
    joined = expected.join(observed, on=["symbol", "datetime"], how="full", coalesce=True, suffix="_o")
    value, other = pl.col("value"), pl.col("value_o")
    scale = pl.max_horizontal(pl.lit(1.0), value.abs().fill_null(0.0), other.abs().fill_null(0.0))
    bad = joined.filter(
        (value.is_null() != other.is_null())
        | (value.is_not_null() & other.is_not_null() & ((value - other).abs() > tolerance * scale))
        | (pl.col("available_at") != pl.col("available_at_o"))
        | pl.col("available_at").is_null() | pl.col("available_at_o").is_null())
    if bad.is_empty():
        return 0, None
    row = bad.sort("symbol", "datetime").row(0, named=True)
    return bad.height, {"symbol": row["symbol"], "datetime": str(row["datetime"]),
                        "full_data_value": row["value"], "cut_data_value": row["value_o"]}


def audit_prefix_invariance(factor, bars: pl.DataFrame, parameters: dict | None = None, *,
                            cutoff_fractions=(0.5, 0.75, 0.9), tolerance: float = 1e-9, tamper: bool = True) -> dict:
    """Check one factor: values up to a cutoff must not change when later data is removed or altered.

    Evidence, not proof: it only exercises the supplied bars and cutoffs. Returns a report
    dict with status PASS / FAIL / SKIP / ERROR and never raises for factor-side problems.
    """
    from quantlab.domain import Timeframe
    from quantlab.factors.engine import _compute_factor
    definition = factor.definition
    report = {"factor_id": definition.factor_id, "version": definition.version, "status": "PASS",
              "checks": [], "reason": ""}
    try:
        params = factor.parameters(parameters or {})
    except Exception as exc:
        return {**report, "status": "SKIP", "reason": "needs_parameters: " + str(exc)[:160]}
    missing = set(definition.required_fields) - set(bars.columns)
    if missing:
        return {**report, "status": "SKIP", "reason": "missing_fields: " + ",".join(sorted(missing))}
    frames = bars.sort("symbol", "datetime")
    if any(Timeframe(t) not in definition.timeframes for t in frames["timeframe"].unique()):
        return {**report, "status": "SKIP", "reason": "timeframe_unsupported"}
    times = frames["available_at"].unique().sort().to_list()
    if len(times) < 10:
        return {**report, "status": "SKIP", "reason": "too_few_bars"}
    try:
        full = _compute_factor(factor, frames, params)
        for fraction in cutoff_fractions:
            cutoff = times[min(len(times) - 1, max(0, int(len(times) * fraction) - 1))]
            expected = full.filter(pl.col("available_at") <= cutoff)
            variants = [("truncate", frames.filter(pl.col("available_at") <= cutoff))]
            if tamper:
                variants.append(("tamper_future", _tamper_future(frames, cutoff)))
            for mode, variant in variants:
                observed = _compute_factor(factor, variant, params).filter(pl.col("available_at") <= cutoff)
                count, first = _diff(expected, observed, tolerance)
                report["checks"].append({"mode": mode, "cutoff": str(cutoff), "compared_rows": expected.height,
                                         "compared_values": expected["value"].drop_nulls().len(),
                                         "mismatches": count, "first_mismatch": first})
                if count:
                    report["status"] = "FAIL"
    except Exception as exc:
        return {**report, "status": "ERROR", "reason": type(exc).__name__ + ": " + str(exc)[:200]}
    if report["status"] == "PASS" and not any(c["compared_values"] for c in report["checks"]):
        return {**report, "status": "SKIP", "reason": "all_null_output: nothing non-null was compared"}
    return report


def audit_registry(registry, bars: pl.DataFrame, factor_ids=None, **options) -> list[dict]:
    """Audit every (or the selected) factor in ``registry`` with default parameters."""
    reports = []
    for factor_id, _version, factor in registry.factors():
        if factor_ids is not None and factor_id not in factor_ids:
            continue
        reports.append(audit_prefix_invariance(factor, bars, **options))
    return reports
