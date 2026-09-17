"""Frozen-candidate retrospective validation; no model, network, registration or trading.

The former generation year remains diagnostic. Label ends cannot cross split
boundaries. All candidate/horizon/period hypotheses retain a Holm slot.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
import json
import math

import polars as pl

from quantlab.factors.restricted_dsl import validate_ast
from quantlab.statistics.bootstrap import BootstrapConfig, block_mean_interval
from quantlab.statistics.permutation import PermutationConfig, block_sign_test, holm
from quantlab.storage.codec import digest, encode


def board_of(symbol: str) -> str | None:
    for prefix, board in (("sh.688", "STAR"), ("sh.60", "SH_MAIN"),
                          ("sz.30", "CHINEXT"), ("sz.00", "SZ_MAIN")):
        if symbol.startswith(prefix):
            return board
    return None


def select_symbols(records: list[dict], available: set[str], selection: dict) -> list[dict]:
    """Select by past listing date, current file inventory and seeded code hash only.

    Current status, future coverage, prices, volume and outcomes do not rank stocks.
    This is still a retrospective catalog, NOT a point-in-time universe certificate.
    """
    pools = {board: [] for board in selection["boards"]}
    seen = set()
    for row in records:
        symbol = row["code"]
        if symbol in seen:
            raise ValueError("Duplicate catalog symbol: " + symbol)
        seen.add(symbol)
        board = board_of(symbol)
        if (board not in pools or row.get("type") != "1" or symbol not in available
                or symbol in selection["excluded_symbols"]):
            continue
        try:
            listed = date.fromisoformat(row.get("ipoDate") or "")
        except ValueError:
            continue
        if listed > date.fromisoformat(selection["ipo_cutoff"]):
            continue
        rank = sha256((selection["seed"] + symbol).encode()).hexdigest()
        pools[board].append({"symbol": symbol, "board": board, "ipo_date": listed.isoformat(), "rank": rank})
    selected = []
    for board, items in pools.items():
        count = selection["count_per_board"]
        if len(items) < count:
            raise ValueError(f"Insufficient frozen pool: {board} has {len(items)}, needs {count}")
        selected.extend(sorted(items, key=lambda r: (r["rank"], r["symbol"]))[:count])
    return sorted(selected, key=lambda r: r["symbol"])


def load_candidates(path: Path, expected_sha256: str) -> list[dict]:
    payload = Path(path).read_bytes()
    if sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Frozen candidate bytes changed")
    value = json.loads(payload)
    if value.get("checksum") != digest({k: v for k, v in value.items() if k != "checksum"}):
        raise ValueError("Frozen candidate checksum mismatch")
    rows = value["candidates"]
    if len(rows) != 3 or len({r["candidate"]["name"] for r in rows}) != 3:
        raise ValueError("Exactly three original distinct candidates required")
    for row in rows:
        candidate, spec = row["candidate"], row["spec"]
        if candidate["expected_rank_ic_sign"] not in ("positive", "negative"):
            raise ValueError("Missing preregistered direction")
        expression = validate_ast(candidate["ast"])
        if expression != spec["parameters"]["ast"] or row["spec_digest"] != digest(spec):
            raise ValueError("Original expression/spec binding changed")
    return rows


def validate_protocol(protocol: dict, candidate_count: int = 3) -> None:
    if (protocol.get("format") != "niuniu-frozen-candidate-validation-v1"
            or protocol["qualification"] != "research_only" or protocol["adjustment"] != "qfq"
            or protocol["candidate_change_allowed"] or protocol["trade_execution"]):
        raise ValueError("Invalid research-only validation protocol")
    periods = protocol["periods"]
    if len({p["name"] for p in periods}) != len(periods):
        raise ValueError("Duplicate period name")
    last = None
    for period in periods:
        start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
        if start > end or (last is not None and start <= last):
            raise ValueError("Periods overlap or are out of order")
        if not date.fromisoformat(protocol["data_start"]) <= start <= end <= date.fromisoformat(protocol["data_end"]):
            raise ValueError("Period outside frozen data")
        last = end
    by_name = {p["name"]: p for p in periods}
    if not {"in_sample", "seen_year_diagnostic", "historical_holdout"} <= set(by_name):
        raise ValueError("Missing required phase")
    if by_name["historical_holdout"]["start"] <= protocol["source_generation_period"][1]:
        raise ValueError("Previously seen generation dates cannot be holdout")
    horizons = protocol["horizons"]
    if horizons != [1, 5]:
        raise ValueError("Original horizons must remain 1 and 5")
    stats = protocol["statistics"]
    if stats["holm_family_size"] != candidate_count * len(horizons) * len(periods):
        raise ValueError("Frozen Holm family does not match all slots")
    if stats["min_cross_section"] < 3 or stats["min_board_cross_section"] < 3:
        raise ValueError("IC requires at least three valid securities")
    if stats["block_days"] < max(horizons):
        raise ValueError("Block length must not be shorter than the label horizon")
    BootstrapConfig(stats["bootstrap_resamples"], stats["block_days"], stats["confidence"])
    PermutationConfig(stats["sign_resamples"], stats["block_days"], stats["alpha"])


def period_daily(observations: pl.DataFrame, bars: pl.DataFrame, horizon: int,
                 start: str, end: str, min_cross_section: int = 20) -> tuple[pl.DataFrame, dict]:
    if min_cross_section < 3:
        raise ValueError("IC cross-section minimum must be >=3")
    lo, hi = date.fromisoformat(start), date.fromisoformat(end)
    if lo > hi:
        raise ValueError("Reversed period")
    keys = ["symbol", "datetime"]
    if observations.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate observation keys")
    if observations.filter(pl.col("available_at") != pl.col("datetime")).height:
        raise ValueError("Delayed factor cannot be backdated")
    dates = bars.filter(pl.col("datetime").dt.date().is_between(lo, hi)).select("datetime").unique().sort("datetime")
    sample = observations.filter(pl.col("datetime").dt.date().is_between(lo, hi))
    sample = sample.join(bars.select(*keys, "volume"), on=keys, how="left", validate="1:1")
    label, label_end = f"forward_{horizon}", f"label_end_{horizon}"
    # Signal-time no-volume rows are excluded; outcomes are NEVER used for selection.
    sample = sample.filter(pl.col("eligible") & (pl.col("volume") > 0))
    beyond = sample.filter(pl.col(label).is_not_null() & (pl.col(label_end).dt.date() > hi)).height
    valid = sample.filter(pl.col("value").is_finite() & pl.col(label).is_finite()
                          & (pl.col(label_end) > pl.col("datetime")) & (pl.col(label_end).dt.date() <= hi))
    daily = valid.group_by("datetime").agg(pl.len().alias("n"),
        pl.corr("value", label, method="spearman").alias("rank_ic"))
    daily = daily.with_columns(pl.when((pl.col("n") >= min_cross_section) & pl.col("rank_ic").is_finite())
                              .then(pl.col("rank_ic")).otherwise(None).alias("rank_ic"))
    ranked = valid.with_columns(pl.len().over("datetime").alias("n"),
        pl.col("value").n_unique().over("datetime").alias("unique"),
        pl.col("value").rank("average").over("datetime").alias("rank"))
    ranked = ranked.filter((pl.col("n") >= max(5, min_cross_section)) & (pl.col("unique") >= 5))
    ranked = ranked.with_columns((((pl.col("rank") - 1) / pl.col("n") * 5).floor().cast(pl.Int64) + 1).alias("q"))
    groups = ranked.group_by("datetime", "q").agg(pl.col(label).mean().alias("mean_label"))
    spread = groups.filter(pl.col("q") == 5).select("datetime", pl.col("mean_label").alias("high"))
    spread = spread.join(groups.filter(pl.col("q") == 1).select("datetime", pl.col("mean_label").alias("low")), on="datetime")
    spread = spread.select("datetime", (pl.col("high") - pl.col("low")).alias("gross_high_minus_low"))
    result = dates.join(daily, on="datetime", how="left").join(spread, on="datetime", how="left").sort("datetime")
    return result, {"signal_rows": sample.height, "valid_label_rows": valid.height,
        "boundary_labels_excluded": beyond, "observed_dates": dates.height,
        "securities": valid["symbol"].n_unique(), "minimum_cross_section": min_cross_section}


def descriptive(daily: pl.DataFrame) -> dict:
    values = daily["rank_ic"].drop_nulls()
    return {"rank_ic": values.mean(), "ic_dates": len(values),
        "observed_dates": daily.height, "min_valid_symbols": daily["n"].min(),
        "mean_valid_symbols": daily["n"].mean(), "max_valid_symbols": daily["n"].max(),
        "gross_high_minus_low": daily["gross_high_minus_low"].mean()}


def infer_daily(daily: pl.DataFrame, stats: dict, identity: dict) -> dict:
    values = daily["rank_ic"].to_list()
    seed = int(digest({"seed": stats["seed"], **identity}), 16)
    interval = block_mean_interval(values, BootstrapConfig(stats["bootstrap_resamples"], stats["block_days"], stats["confidence"]), seed)
    test = block_sign_test(values, PermutationConfig(stats["sign_resamples"], stats["block_days"], stats["alpha"]), seed)
    return {**descriptive(daily), "confidence_interval": interval, "test": test}


def finalize_family(rows: list[dict], protocol: dict) -> dict:
    stats = protocol["statistics"]
    if len(rows) != stats["holm_family_size"]:
        raise ValueError("Missing hypotheses must retain their slots")
    identities = {(r["candidate"], r["period"], r["horizon"]) for r in rows}
    names = {r["candidate"] for r in rows}
    expected = {(name, p["name"], h) for name in names for p in protocol["periods"] for h in protocol["horizons"]}
    if identities != expected or len(names) != 3:
        raise ValueError("Frozen family identities do not match")
    adjusted = holm([row["test"]["p_value"] for row in rows])
    for row, pvalue in zip(rows, adjusted):
        direction = 1 if row["expected_sign"] == "positive" else -1
        mean = row["rank_ic"]
        row.update(p_holm=pvalue, expected_direction_matches=mean is not None and direction * mean > 0,
            signed_rank_ic=None if mean is None else direction * mean)
        row["significant_expected_direction"] = bool(pvalue is not None and pvalue <= stats["alpha"] and row["expected_direction_matches"])
    conclusions = []
    for name in sorted(names):
        mine = [r for r in rows if r["candidate"] == name]
        train = [r for r in mine if r["period"] == "in_sample"]
        holdout = [r for r in mine if r["period"] == "historical_holdout"]
        acceptable = (all(r["expected_direction_matches"] for r in train)
            and all(r["significant_expected_direction"] and r["signed_rank_ic"] >= stats["minimum_signed_rank_ic"] for r in holdout))
        conclusions.append({"candidate": name, "next_stage_eligible": bool(acceptable),
            "status": "RETROSPECTIVE_SIGNAL_CANDIDATE" if acceptable else "NOT_SUPPORTED_BY_FROZEN_GATE",
            "alpha_verified": False, "production_registered": False})
    return {"format": "niuniu-frozen-candidate-results-v1", "protocol_checksum": digest(protocol),
        "family_size": len(rows), "tests": rows, "conclusions": conclusions,
        "limitations": protocol["limitations"], "alpha_verified": False}


def normalize_research_frame(frame: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """Explicit research-only nullable-volume adapter, not the production MQC gate.

    Price/time errors fail closed. Null volume/turnover remain null and their signal
    dates are ineligible. Rows remain on the time axis; no fill or gap compression.
    """
    from datetime import time
    if frame.is_empty() or frame.filter(pl.col("code").is_null() | (pl.col("code") != symbol)).height:
        raise ValueError("Empty data or security mismatch")
    clock = pl.col("date").dt.combine(time(15)).dt.replace_time_zone("Asia/Shanghai")
    bars = frame.select(pl.col("code").alias("symbol"), pl.lit(symbol[:2]).alias("exchange"),
        clock.alias("datetime"), clock.alias("available_at"), pl.lit("1d").alias("timeframe"),
        *[pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close", "volume")],
        pl.col("amount").cast(pl.Float64).alias("turnover"), pl.col("factor").cast(pl.Float64).alias("adj_factor"))
    required = ("symbol", "datetime", "available_at", "open", "high", "low", "close", "adj_factor")
    if any(bars[c].null_count() for c in required):
        raise ValueError("Missing price/time/adjustment data is not permitted")
    if bars.select(pl.struct("symbol", "datetime").is_duplicated().any()).item():
        raise ValueError("Duplicate bars")
    invalid = (pl.any_horizontal([~pl.col(c).is_finite() for c in ("open", "high", "low", "close", "adj_factor")])
        | (pl.min_horizontal("open", "high", "low", "close", "adj_factor") <= 0)
        | (pl.col("high") < pl.max_horizontal("open", "low", "close"))
        | (pl.col("low") > pl.min_horizontal("open", "high", "close")))
    for c in ("volume", "turnover"):
        invalid = invalid | (pl.col(c).is_not_null() & (~pl.col(c).is_finite() | (pl.col(c) < 0)))
    if bars.filter(invalid).height:
        raise ValueError("Invalid price, quantity, or adjustment")
    return bars.sort("symbol", "datetime")
