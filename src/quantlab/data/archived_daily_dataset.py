"""Finite immutable research packages compiled from verified retro-daily captures.

The exporter is deliberately host-driven.  It never discovers another capture, downloads
anything, grants data access, or upgrades retrospective provider observations to PIT data.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo
import ctypes
import errno
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys

import polars as pl
import pyarrow.parquet as pq

from quantlab.agent.qm50_archived_inputs import ArchivedDailyBridge
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot
from quantlab.data.retro_daily import FIELDS, SCHEMA, normalize_symbol_rows
from quantlab.data.session_coverage import calendar_sessions
from quantlab.data.validation import SUSPENSION_INPUT_CONTRACT, ordered_bars
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest, encode

MARKER = "archived-daily-dataset.json"
FORMAT_V1 = "niuniu-archived-daily-dataset-v1"
FORMAT_V2 = "niuniu-archived-daily-dataset-v2"
FORMAT = FORMAT_V1  # backward-compatible public constant
CONTRACT_V1 = "tradable_only_v1"
CONTRACT_V2 = SUSPENSION_INPUT_CONTRACT
_CONTRACTS = {CONTRACT_V1: FORMAT_V1, CONTRACT_V2: FORMAT_V2}
_SYMBOL = re.compile(r"^(?:sh|sz)\.\d{6}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SYMBOLS = 10
_MAX_DAYS = 371
_MAX_ROWS = _MAX_SYMBOLS * _MAX_DAYS
_MAX_FILE_BYTES = 64_000_000
_MAX_TOTAL_BYTES = 256_000_000
_MAX_MANIFEST_BYTES = 2_000_000
_MAX_FILES = 24
_TZ = ZoneInfo("Asia/Shanghai")

TIME_POLICY = {
    "datetime": "requested archive session at 15:00 Asia/Shanghai",
    "available_at": "same nominal close timestamp for research alignment only",
    "historical_available_at_verified": False,
    "policy": "research_nominal_close_not_historical_availability",
}
LIMITATIONS = [
    "Retrospective provider observations only; this package is research_only and is not Strict PIT certification.",
    "available_at is a nominal close-time alignment, not evidence of historical publication or availability.",
    "Calendar coverage is the capture's fixed provider calendar, not an official historical security population.",
    "v1 rejects requested tradestatus!=1 rows and never drops, forward-fills, synthesizes, or substitutes sessions.",
    "isST=1 is retained when its archived market row is valid; it does not establish historical tradability.",
    "The package grants no source-workspace, approval, collection, strategy, execution, or trading permission.",
]
LIMITATIONS_V2 = [
    "Retrospective provider observations only; this package is research_only and is not Strict PIT certification.",
    "available_at is a nominal close-time alignment, not evidence of historical publication or availability.",
    "Calendar coverage is the capture's fixed provider calendar, not an official historical security population.",
    "v2 preserves every requested provider session and tradestatus; suspended rows keep OHLC null and are never converted into fill bars.",
    "Suspended rows use source vendor_previous_close only as an explicit valuation mark; it is not an executable price or synthetic OHLC.",
    "Research eligibility excludes bs_trade_status=0; labels keep the full session grid so suspension is not compressed into a later price.",
    "Factors that cannot process null OHLC fail explicitly; no forward-fill, session deletion, or hidden imputation is permitted.",
    "isST=1 is retained when its archived market row is valid; it does not establish historical tradability.",
    "The package grants no source-workspace, approval, collection, strategy, execution, or trading permission.",
]


def _contract(value: str) -> str:
    if value not in _CONTRACTS:
        raise ValueError("Archived daily contract must be tradable_only_v1 or preserve_suspension_state_v2")
    return value


def _limitations(contract: str) -> list[str]:
    return list(LIMITATIONS if contract == CONTRACT_V1 else LIMITATIONS_V2)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_json(payload: bytes, what: str) -> Any:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"Duplicate JSON key in {what}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(payload, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON in {what}") from error


def _gunzip_json(payload: bytes, what: str, limit: int = 32_000_000) -> Any:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
            raw = stream.read(limit + 1)
    except (OSError, EOFError) as error:
        raise ValueError(f"Invalid gzip in {what}") from error
    if len(raw) > limit:
        raise ValueError(f"Inflated {what} exceeds byte budget")
    return _strict_json(raw, what)


def _checked_core(value: Any, what: str) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("checksum"), str):
        raise ValueError(f"{what} lacks a valid checksum")
    core = {key: item for key, item in value.items() if key != "checksum"}
    if value["checksum"] != digest(core):
        raise ValueError(f"{what} checksum mismatch")
    return core


def _parse_symbols(symbols: str) -> tuple[str, ...]:
    if not isinstance(symbols, str):
        raise ValueError("symbols must be a string containing 1–10 distinct archive codes")
    values = tuple(symbols.replace(",", " ").split())
    if not 1 <= len(values) <= _MAX_SYMBOLS or len(set(values)) != len(values):
        raise ValueError("Select 1–10 distinct archive symbols")
    if any(not _SYMBOL.fullmatch(value) for value in values):
        raise ValueError("Archive symbols must use sh/sz.XXXXXX")
    return values


def _parse_range(start: str, end: str) -> tuple[date, date]:
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("start/end must be ISO dates")
    try:
        lo, hi = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as error:
        raise ValueError("start/end must be ISO dates") from error
    if lo.isoformat() != start or hi.isoformat() != end or not 0 <= (hi - lo).days < _MAX_DAYS:
        raise ValueError("Select an ordered range of at most 371 calendar days")
    return lo, hi


def _safe_source_name(symbol: str) -> str:
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError("Invalid archived symbol")
    return symbol.replace(".", "_")


def _expected_paths(symbols: tuple[str, ...]) -> tuple[str, ...]:
    paths = [
        "source/plan.json",
        "source/reference/stock_basic.json.gz",
        "source/reference/trade_calendar.json.gz",
        "normalized/bars.parquet",
    ]
    for symbol in symbols:
        prefix = "source/symbols/" + _safe_source_name(symbol) + "/"
        paths.extend((prefix + "rows.json.gz", prefix + "daily.parquet"))
    return tuple(paths)


def _parquet_frame(payload: bytes, what: str, max_rows: int) -> pl.DataFrame:
    if not payload or len(payload) > _MAX_FILE_BYTES:
        raise ValueError(f"{what} exceeds byte budget")
    try:
        metadata = pq.ParquetFile(io.BytesIO(payload)).metadata
    except Exception as error:
        raise ValueError(f"Invalid parquet in {what}") from error
    if metadata is None or metadata.num_rows < 0 or metadata.num_rows > max_rows \
            or metadata.num_row_groups > 128 or metadata.num_columns > 32:
        raise ValueError(f"{what} exceeds row/column-group budget")
    try:
        frame = pl.read_parquet(io.BytesIO(payload))
    except Exception as error:
        raise ValueError(f"Cannot decode parquet in {what}") from error
    if frame.height != metadata.num_rows:
        raise ValueError(f"{what} row metadata mismatch")
    return frame


def _plan_and_references(files: dict[str, bytes], capture_id: str) -> tuple[dict, list, list]:
    plan_value = _strict_json(files["plan.json"], "plan.json")
    plan = _checked_core(plan_value, "plan.json")
    required = {
        "format", "dataset_format", "capture_id", "start", "end", "fields", "created_at", "sdk_version",
        "provider", "stock_basic_content_hash", "stock_basic_file_sha256", "calendar_content_hash",
        "calendar_file_sha256", "trading_days", "first_trading_day", "last_trading_day", "symbols",
        "symbol_count", "qualification", "limitations",
    }
    if set(plan) != required or plan["capture_id"] != capture_id or tuple(plan["fields"]) != FIELDS:
        raise ValueError("Archived plan identity or field contract mismatch")
    if not isinstance(plan["symbols"], list) or len(plan["symbols"]) != plan["symbol_count"] \
            or len(set(plan["symbols"])) != len(plan["symbols"]):
        raise ValueError("Archived plan symbol inventory mismatch")
    if _sha(files["reference/stock_basic.json.gz"]) != plan["stock_basic_file_sha256"] \
            or _sha(files["reference/trade_calendar.json.gz"]) != plan["calendar_file_sha256"]:
        raise ValueError("Archived reference byte hash mismatch")
    basic = _gunzip_json(files["reference/stock_basic.json.gz"], "stock_basic.json.gz")
    calendar = _gunzip_json(files["reference/trade_calendar.json.gz"], "trade_calendar.json.gz")
    if digest(basic) != plan["stock_basic_content_hash"] or digest(calendar) != plan["calendar_content_hash"]:
        raise ValueError("Archived reference content identity mismatch")
    if basic.get("fields") != ["code", "code_name", "ipoDate", "outDate", "type", "status"] \
            or calendar.get("fields") != ["calendar_date", "is_trading_day"]:
        raise ValueError("Archived reference field contract mismatch")
    if not isinstance(basic.get("rows"), list) or not isinstance(calendar.get("rows"), list):
        raise ValueError("Archived reference rows are invalid")
    return plan, basic["rows"], calendar["rows"]


def _semantic_rows(bars: pl.DataFrame) -> list[dict]:
    result = []
    for row in bars.to_dicts():
        result.append({key: value.isoformat() if isinstance(value, (date, datetime)) else value
                       for key, value in row.items()})
    return result


def _normalize_material(*, capture_id: str, symbols: tuple[str, ...], lo: date, hi: date,
                        payloads: dict[str, dict[str, bytes]], files: dict[str, bytes],
                        source_manifests: dict[str, dict], contract: str = CONTRACT_V1) -> dict:
    contract = _contract(contract)
    if set(payloads) != set(symbols) or set(source_manifests) != set(symbols):
        raise ValueError("Requested source symbol set differs from archived payloads")
    if set(files) != {"plan.json", "reference/stock_basic.json.gz", "reference/trade_calendar.json.gz"}:
        raise ValueError("Archived source file set is not exact")
    total = sum(len(value) for value in files.values())
    for parts in payloads.values():
        if set(parts) != {"raw", "daily"}:
            raise ValueError("Archived symbol payload set is not exact")
        total += sum(len(value) for value in parts.values())
    if total > _MAX_TOTAL_BYTES:
        raise ValueError("Archived material exceeds total byte budget")

    plan, _basic, calendar_rows = _plan_and_references(files, capture_id)
    plan_start, plan_end = date.fromisoformat(plan["start"]), date.fromisoformat(plan["end"])
    if not plan_start <= lo <= hi <= plan_end or not set(symbols) <= set(plan["symbols"]):
        raise ValueError("Requested range or symbols fall outside the exact capture plan")
    calendar = pl.DataFrame(calendar_rows, schema=["calendar_date", "is_trading_day"], orient="row")
    all_sessions = calendar_sessions(calendar, plan_start, plan_end)
    sessions = tuple(day for day in all_sessions if lo <= day <= hi)
    if not sessions:
        raise ValueError("No observed calendar trading sessions in requested range")
    expected = set(sessions)

    parts_out = []
    evidence_symbols = []
    for symbol in symbols:
        source = payloads[symbol]
        manifest = source_manifests[symbol]
        required_manifest = {
            "format", "capture_id", "symbol", "status", "rows", "first_date", "last_date", "tradable_rows",
            "st_rows", "raw_sha256", "parquet_sha256", "content_hash", "fetched_at", "sdk_version",
        }
        if not isinstance(manifest, dict) or set(manifest) != required_manifest \
                or manifest["capture_id"] != capture_id or manifest["symbol"] != symbol:
            raise ValueError("Archived symbol manifest identity mismatch: " + symbol)
        if _sha(source["raw"]) != manifest["raw_sha256"] or _sha(source["daily"]) != manifest["parquet_sha256"]:
            raise ValueError("Archived raw/typed byte hash mismatch: " + symbol)
        raw = _gunzip_json(source["raw"], symbol + " rows.json.gz")
        if not isinstance(raw, dict) or set(raw) != {"format", "symbol", "fields", "rows"} \
                or raw["symbol"] != symbol or tuple(raw["fields"]) != FIELDS or digest(raw) != manifest["content_hash"]:
            raise ValueError("Archived raw identity or schema mismatch: " + symbol)
        normalized = normalize_symbol_rows(raw["rows"], symbol, plan_start, plan_end, {d.isoformat() for d in all_sessions})
        raw_frame = pl.DataFrame(normalized, schema=SCHEMA) if normalized else pl.DataFrame(schema=SCHEMA)
        typed = _parquet_frame(source["daily"], symbol + " daily.parquet", 20_000)
        if typed.columns != list(SCHEMA) or typed.schema != pl.Schema(SCHEMA) \
                or typed.height != manifest["rows"] or not typed.equals(raw_frame):
            raise ValueError("Archived raw response and typed data disagree: " + symbol)
        expected_manifest_summary = {
            "status": "OK" if typed.height else "EMPTY",
            "rows": typed.height,
            "first_date": typed["date"][0].isoformat() if typed.height else None,
            "last_date": typed["date"][-1].isoformat() if typed.height else None,
            "tradable_rows": typed.filter(pl.col("tradestatus") == 1).height,
            "st_rows": typed.filter(pl.col("isST") == 1).height,
        }
        if any(manifest[key] != value for key, value in expected_manifest_summary.items()):
            raise ValueError("Archived symbol manifest summary disagrees with typed data: " + symbol)
        selected = typed.filter(pl.col("date").is_between(lo, hi))
        dates = selected["date"].to_list()
        if len(dates) != len(expected) or len(set(dates)) != len(dates) or set(dates) != expected:
            raise ValueError("Requested archive calendar has missing, duplicate, or unexpected rows: " + symbol)
        required_numbers = ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg"]
        if contract == CONTRACT_V1:
            if selected.filter(pl.col("tradestatus") != 1).height:
                raise ValueError("v1 rejects requested tradestatus!=1 rows: " + symbol)
            if any(selected[column].null_count() for column in required_numbers) \
                    or selected.filter(pl.any_horizontal([~pl.col(column).is_finite() for column in required_numbers])).height:
                raise ValueError("Requested archive row has empty or non-finite required values: " + symbol)
        else:
            tradable = selected.filter(pl.col("tradestatus") == 1)
            suspended = selected.filter(pl.col("tradestatus") == 0)
            if any(tradable[column].null_count() for column in required_numbers) \
                    or tradable.filter(pl.any_horizontal([~pl.col(column).is_finite() for column in required_numbers])).height:
                raise ValueError("v2 tradable archive row has empty or non-finite required values: " + symbol)
            if suspended.height:
                if suspended.filter(pl.any_horizontal([pl.col(column).is_not_null() for column in ("open", "high", "low", "close")])).height:
                    raise ValueError("v2 suspended rows must preserve null OHLC without synthesis: " + symbol)
                if suspended["preclose"].null_count() or suspended.filter(~pl.col("preclose").is_finite() | (pl.col("preclose") <= 0)).height:
                    raise ValueError("v2 suspended rows require finite positive preclose valuation evidence: " + symbol)
                for column in ("volume", "amount", "turn", "pctChg"):
                    if suspended.filter(pl.col(column).is_not_null() & ~pl.col(column).is_finite()).height:
                        raise ValueError("v2 suspended source numeric field is non-finite: " + symbol + ":" + column)
                for column in ("volume", "amount"):
                    if suspended.filter(pl.col(column).is_not_null() & (pl.col(column) < 0)).height:
                        raise ValueError("v2 suspended volume/amount cannot be negative: " + symbol)
        try:
            fetched = datetime.fromisoformat(manifest["fetched_at"])
        except (TypeError, ValueError) as error:
            raise ValueError("Archived source_fetched_at is invalid: " + symbol) from error
        if fetched.tzinfo is None or fetched.utcoffset() is None:
            raise ValueError("Archived source_fetched_at must be timezone-aware: " + symbol)
        timestamp = pl.col("date").dt.combine(time(15)).dt.replace_time_zone(str(_TZ))
        bars = selected.select(
            pl.col("code").alias("symbol"),
            pl.lit(symbol[:2]).alias("exchange"),
            timestamp.alias("datetime"),
            timestamp.alias("available_at"),
            pl.lit("1d").alias("timeframe"),
            *[pl.col(column).cast(pl.Float64) for column in ("open", "high", "low", "close", "volume")],
            pl.col("amount").cast(pl.Float64).alias("turnover"),
            pl.lit(1.0, dtype=pl.Float64).alias("adj_factor"),
            pl.col("preclose").cast(pl.Float64).alias("vendor_previous_close"),
            pl.col("turn").cast(pl.Float64).alias("bs_turn_pct"),
            pl.col("tradestatus").cast(pl.UInt8).alias("bs_trade_status"),
            pl.col("isST").cast(pl.UInt8).alias("bs_is_st"),
            pl.col("pctChg").cast(pl.Float64).alias("vendor_pct_change"),
            pl.lit(manifest["fetched_at"]).alias("source_fetched_at"),
        )
        if contract == CONTRACT_V2:
            bars = bars.with_columns(pl.lit(CONTRACT_V2).alias("input_contract"))
        parts_out.append(bars)
        evidence_symbols.append({
            "symbol": symbol,
            "raw_sha256": manifest["raw_sha256"],
            "typed_sha256": manifest["parquet_sha256"],
            "raw_content_hash": manifest["content_hash"],
            "rows_in_capture": manifest["rows"],
            "source_fetched_at": manifest["fetched_at"],
            "manifest": manifest,
        })
    bars = ordered_bars(pl.concat(parts_out).sort("symbol", "datetime"))
    if bars.height != len(symbols) * len(sessions) or bars.height > _MAX_ROWS:
        raise ValueError("Normalized bar coverage or row budget mismatch")
    semantic_sha = digest({"fields": bars.columns, "rows": _semantic_rows(bars)})
    sessions_hash = digest([day.isoformat() for day in sessions])
    source_snapshot = {
        "source": "archived_retro_daily",
        "capture_id": capture_id,
        "dataset_format": plan["dataset_format"],
        "plan_sha256": _sha(files["plan.json"]),
        "calendar_sha256": _sha(files["reference/trade_calendar.json.gz"]),
        "stock_basic_sha256": _sha(files["reference/stock_basic.json.gz"]),
        "symbols": evidence_symbols,
        "calendar_coverage": {
            "kind": "fixed_capture_provider_calendar_not_official_population",
            "requested_sessions": len(sessions),
            "requested_sessions_sha256": sessions_hash,
        },
        "raw_and_typed_bytes_verified": True,
        "normalized_semantics_sha256": semantic_sha,
        "qualification": "research_only",
        "historical_available_at_verified": False,
    }
    if contract == CONTRACT_V2:
        source_snapshot.update(input_contract=CONTRACT_V2,
                               suspension_state_preserved=True,
                               valuation_policy="vendor_previous_close_for_suspended_valuation_only_never_fill")
    return {"bars": bars, "sessions": sessions, "source_snapshot": source_snapshot, "semantic_sha256": semantic_sha}


def _preview_core(capture_id: str, symbols: tuple[str, ...], lo: date, hi: date, material: dict,
                  contract: str = CONTRACT_V1) -> dict:
    contract = _contract(contract)
    bars = material["bars"]
    result = {
        "capture_id": capture_id,
        "symbols": list(symbols),
        "start": lo.isoformat(),
        "end": hi.isoformat(),
        "rows": bars.height,
        "actual_sessions": len(material["sessions"]),
        "fields": bars.columns,
        "adjustment": "raw",
        "qualification": "research_only",
        "time_policy": TIME_POLICY,
        "source_evidence": material["source_snapshot"],
        "limitations": _limitations(contract),
    }
    if contract == CONTRACT_V2:
        result.update(
            input_contract=CONTRACT_V2,
            tradable_rows=bars.filter(pl.col("bs_trade_status") == 1).height,
            suspended_rows=bars.filter(pl.col("bs_trade_status") == 0).height,
            valuation_policy="carry_last_tradable_close; source vendor_previous_close only if no prior mark; never a fill price",
            research_policy="bs_trade_status=0 is ineligible; full session grid is retained for shifts/labels; no forward-fill",
            execution_policy="bs_trade_status=0 cannot create fills; target changes remain pending/rejected for that session",
        )
    return result


def _prepare_source(source_workspace, capture_id, symbols, start, end, *, contract=CONTRACT_V1) -> dict:
    contract = _contract(contract)
    parsed_symbols = _parse_symbols(symbols)
    lo, hi = _parse_range(start, end)
    if _forbidden_symlink_component(Path(source_workspace).expanduser()):
        raise ValueError("Archive source workspace uses a symlink/redirected ancestor")
    bridge = ArchivedDailyBridge(source_workspace)
    payloads, files, evidence, _days, bridge_lo, bridge_hi = bridge.load(
        capture_id, " ".join(parsed_symbols), start, end
    )
    if (bridge_lo, bridge_hi) != (lo, hi):
        raise ValueError("Archive bridge returned a different request range")
    material = _normalize_material(capture_id=capture_id, symbols=parsed_symbols, lo=lo, hi=hi,
                                   payloads=payloads, files=files, source_manifests=evidence["symbols"],
                                   contract=contract)
    core = _preview_core(capture_id, parsed_symbols, lo, hi, material, contract)
    preview = {"preview_hash": digest(core), **core}
    return {"preview": preview, "payloads": payloads, "files": files, "material": material,
            "symbols": parsed_symbols, "lo": lo, "hi": hi, "source_root": bridge.root,
            "contract": contract}


def preview_archived_daily_dataset(source_workspace, capture_id, symbols, start, end, *, contract=CONTRACT_V1) -> dict:
    """Validate existing exact source bytes and return a stable, write-free export preview."""
    return _prepare_source(source_workspace, capture_id, symbols, start, end, contract=contract)["preview"]


def _file_entry(path: str, payload: bytes, role: str, rows: int | None = None) -> dict:
    result = {"path": path, "sha256": _sha(payload), "bytes": len(payload), "role": role}
    if rows is not None:
        result["rows"] = rows
    return result


def _manifest_for(prepared: dict, serialized_bars: bytes) -> dict:
    preview = prepared["preview"]
    contract = prepared.get("contract", CONTRACT_V1)
    symbols = prepared["symbols"]
    source_files = prepared["files"]
    payloads = prepared["payloads"]
    entries = [
        _file_entry("source/plan.json", source_files["plan.json"], "source_plan"),
        _file_entry("source/reference/stock_basic.json.gz", source_files["reference/stock_basic.json.gz"], "source_stock_basic"),
        _file_entry("source/reference/trade_calendar.json.gz", source_files["reference/trade_calendar.json.gz"], "source_trade_calendar"),
    ]
    for symbol in symbols:
        prefix = "source/symbols/" + _safe_source_name(symbol) + "/"
        entries.extend((
            _file_entry(prefix + "rows.json.gz", payloads[symbol]["raw"], "source_raw_rows"),
            _file_entry(prefix + "daily.parquet", payloads[symbol]["daily"], "source_typed_daily"),
        ))
    entries.append(_file_entry("normalized/bars.parquet", serialized_bars, "normalized_bars", preview["rows"]))
    request_keys = ("capture_id", "symbols", "start", "end", "adjustment")
    summary_keys = ("rows", "actual_sessions", "fields", "qualification", "time_policy", "limitations")
    if contract == CONTRACT_V2:
        request_keys += ("input_contract",)
        summary_keys += ("input_contract", "tradable_rows", "suspended_rows", "valuation_policy", "research_policy", "execution_policy")
    core = {
        "format": _CONTRACTS[contract],
        "request": {key: preview[key] for key in request_keys},
        "summary": {key: preview[key] for key in summary_keys},
        "preview_hash": preview["preview_hash"],
        "source_snapshot": preview["source_evidence"],
        "normalized": {"path": "normalized/bars.parquet", "rows": preview["rows"],
                       "semantics_sha256": prepared["material"]["semantic_sha256"]},
        "files": entries,
    }
    dataset_id = digest(core)
    signed = {**core, "dataset_id": dataset_id}
    return {**signed, "checksum": digest(signed)}


def _forbidden_symlink_component(path: Path) -> bool:
    """Reject user-controlled redirect components, tolerating macOS' system /tmp and /var aliases."""
    allowed_system_aliases = {Path("/tmp"), Path("/var")}
    current = path.absolute()
    while True:
        if current.is_symlink() and current not in allowed_system_aliases:
            return True
        if current == current.parent:
            return False
        current = current.parent


def _destination(source_root: Path, destination) -> tuple[Path, Path]:
    raw = Path(destination).expanduser()
    if not raw.name or raw.name in (".", "..") or os.path.lexists(raw):
        raise ValueError("Destination must be a wholly new directory")
    parent = raw.parent
    if not parent.is_dir() or parent.is_symlink() or _forbidden_symlink_component(parent):
        raise ValueError("Destination parent is missing or uses a symlink/redirect path")
    parent = parent.resolve()
    target = parent / raw.name
    source_root = source_root.resolve()
    market_tree = source_root / "_market_data"
    if target == source_root or target == market_tree or target.is_relative_to(market_tree):
        raise ValueError("Destination cannot be the source or its _market_data tree")
    return parent, target


def _write_regular(root: Path, relative: str, payload: bytes) -> None:
    path = root / relative
    if path.is_absolute() is False or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Export payload path escaped staging directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    """Best-effort directory durability; some external macOS filesystems reject directory fsync."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in (errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL)):
                raise
    finally:
        os.close(descriptor)


def _publish_marker_last(source: Path, destination: Path) -> None:
    """Claim a new directory on filesystems without exclusive rename.

    The invalid marker makes every intermediate state unreadable as a dataset.
    A failed publication is retained for host inspection, never erased/reused.
    Replacing our own marker is the atomic validity boundary, not directory creation.
    """
    destination.mkdir()  # Atomic exclusive reservation; existing empty dirs also fail.
    incomplete = encode({"format": FORMAT, "publication_state": "INCOMPLETE"}).encode("utf-8")
    _write_regular(destination, MARKER, incomplete)
    for name in ("source", "normalized"):
        child = destination / name
        if os.path.lexists(child):
            raise FileExistsError(str(child))
        os.rename(source / name, child)
    if (destination / MARKER).read_bytes() != incomplete:
        raise ValueError("Export reservation marker changed before publication")
    os.replace(source / MARKER, destination / MARKER)
    _fsync_directory(destination)
    source.rmdir()


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Use native no-replace rename where available; caller also owns a destination lock."""
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renamex = getattr(libc, "renamex_np", None)
        if renamex is not None:
            renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            renamex.restype = ctypes.c_int
            if renamex(os.fsencode(source), os.fsencode(destination), 0x00000004) == 0:  # RENAME_EXCL
                return
            code = ctypes.get_errno()
            if code in (errno.EEXIST, errno.ENOTEMPTY):
                raise FileExistsError(str(destination))
            if code not in (errno.ENOTSUP, errno.EINVAL, errno.ENOSYS):
                raise OSError(code, os.strerror(code), str(destination))
    _publish_marker_last(source, destination)


def export_archived_daily_dataset(source_workspace, capture_id, symbols, start, end, destination, *,
                                  expected_preview_hash, confirmed=False, contract=CONTRACT_V1) -> dict:
    """Re-read a preview, stage exact bytes beside the target, and publish without overwrite."""
    if confirmed is not True:
        raise ValueError("Export requires confirmed=True")
    if not isinstance(expected_preview_hash, str) or not _HEX64.fullmatch(expected_preview_hash):
        raise ValueError("A complete expected_preview_hash is required")
    # Validate the target before expensive source reads and again while holding the lock.
    bridge = ArchivedDailyBridge(source_workspace)
    parent, target = _destination(bridge.root, destination)
    lock_path = parent / ("." + target.name + ".archived-dataset-export.lock")
    lock_fd = None
    owns_lock = False
    stage = None
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        owns_lock = True
        os.write(lock_fd, str(os.getpid()).encode())
        os.fsync(lock_fd)
        if os.path.lexists(target):
            raise ValueError("Destination must be a wholly new directory")
        prepared = _prepare_source(source_workspace, capture_id, symbols, start, end, contract=contract)
        if prepared["preview"]["preview_hash"] != expected_preview_hash:
            raise ValueError("Preview hash changed; source/request must be reviewed again")
        buffer = io.BytesIO()
        prepared["material"]["bars"].write_parquet(buffer, compression="zstd")
        bars_payload = buffer.getvalue()
        manifest = _manifest_for(prepared, bars_payload)
        if len(manifest["files"]) > _MAX_FILES or sum(item["bytes"] for item in manifest["files"]) > _MAX_TOTAL_BYTES:
            raise ValueError("Dataset package exceeds file or byte budget")
        stage = parent / ("." + target.name + ".stage-" + str(uuid4()))
        stage.mkdir()
        payload_map = {
            "source/plan.json": prepared["files"]["plan.json"],
            "source/reference/stock_basic.json.gz": prepared["files"]["reference/stock_basic.json.gz"],
            "source/reference/trade_calendar.json.gz": prepared["files"]["reference/trade_calendar.json.gz"],
            "normalized/bars.parquet": bars_payload,
        }
        for symbol in prepared["symbols"]:
            prefix = "source/symbols/" + _safe_source_name(symbol) + "/"
            payload_map[prefix + "rows.json.gz"] = prepared["payloads"][symbol]["raw"]
            payload_map[prefix + "daily.parquet"] = prepared["payloads"][symbol]["daily"]
        for relative in _expected_paths(prepared["symbols"]):
            _write_regular(stage, relative, payload_map[relative])
        marker_payload = encode(manifest).encode("utf-8")
        if len(marker_payload) > _MAX_MANIFEST_BYTES:
            raise ValueError("Dataset manifest exceeds byte budget")
        _write_regular(stage, MARKER, marker_payload)
        _inspect_package(stage)
        _fsync_directory(stage)
        _rename_noreplace(stage, target)
        stage = None
        _fsync_directory(parent)
        result = {"dataset_id": manifest["dataset_id"], "path": str(target),
                  "preview_hash": expected_preview_hash, "rows": prepared["preview"]["rows"]}
        if contract == CONTRACT_V2:
            result["input_contract"] = CONTRACT_V2
        return result
    except FileExistsError as error:
        raise ValueError("Destination or concurrent export already exists") from error
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        if owns_lock and lock_path.exists() and not lock_path.is_symlink():
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def _safe_package_root(root) -> Path:
    raw = Path(root).expanduser()
    if raw.is_symlink() or not raw.is_dir() or _forbidden_symlink_component(raw):
        raise ValueError("Archived dataset root is missing or uses a symlink/redirected ancestor")
    return raw.resolve()


def _read_bounded_regular(path: Path, limit: int, what: str) -> bytes:
    if path.is_symlink():
        raise ValueError(f"Symlink rejected in {what}")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError(f"{what} is not a bounded regular file")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) != info.st_size or len(payload) > limit:
        raise ValueError(f"{what} changed while reading or exceeds budget")
    return payload


def _validate_relative(value: Any) -> str:
    if not isinstance(value, str) or "\\" in value:
        raise ValueError("Manifest contains an invalid payload path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("Manifest payload path escapes the dataset")
    return value


def _exact_tree(root: Path, symbols: tuple[str, ...]) -> None:
    expected_dirs = {
        ".": {MARKER, "source", "normalized"},
        "source": {"plan.json", "reference", "symbols"},
        "source/reference": {"stock_basic.json.gz", "trade_calendar.json.gz"},
        "source/symbols": {_safe_source_name(symbol) for symbol in symbols},
        "normalized": {"bars.parquet"},
    }
    for symbol in symbols:
        expected_dirs["source/symbols/" + _safe_source_name(symbol)] = {"rows.json.gz", "daily.parquet"}
    if len(expected_dirs) > _MAX_FILES:
        raise ValueError("Dataset directory budget exceeded")
    for relative, expected in expected_dirs.items():
        directory = root if relative == "." else root / relative
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Dataset directory layout is invalid")
        names = set()
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index > _MAX_FILES:
                    raise ValueError("Dataset directory entry budget exceeded")
                if entry.is_symlink():
                    raise ValueError("Dataset tree contains a symlink")
                names.add(entry.name)
        if names != expected:
            raise ValueError("Dataset contains missing or extra package state at " + relative)


def _manifest_identity(manifest: dict) -> None:
    required = {"format", "request", "summary", "preview_hash", "source_snapshot", "normalized",
                "files", "dataset_id", "checksum"}
    if set(manifest) != required or manifest.get("format") not in (FORMAT_V1, FORMAT_V2):
        raise ValueError("Archived dataset manifest format or fields are invalid")
    signed = {key: value for key, value in manifest.items() if key != "checksum"}
    if manifest["checksum"] != digest(signed):
        raise ValueError("Archived dataset manifest checksum mismatch")
    identity_core = {key: value for key, value in signed.items() if key != "dataset_id"}
    if manifest["dataset_id"] != digest(identity_core) or not _HEX64.fullmatch(str(manifest["dataset_id"])):
        raise ValueError("Archived dataset_id mismatch")


def _inspect_package(root) -> dict:
    root = _safe_package_root(root)
    marker_path = root / MARKER
    marker_payload = _read_bounded_regular(marker_path, _MAX_MANIFEST_BYTES, MARKER)
    manifest = _strict_json(marker_payload, MARKER)
    if not isinstance(manifest, dict):
        raise ValueError("Archived dataset manifest must be an object")
    _manifest_identity(manifest)
    request = manifest["request"]
    contract = CONTRACT_V1 if manifest["format"] == FORMAT_V1 else CONTRACT_V2
    expected_request = {"capture_id", "symbols", "start", "end", "adjustment"}
    if contract == CONTRACT_V2:
        expected_request.add("input_contract")
    if not isinstance(request, dict) or set(request) != expected_request \
            or request["adjustment"] != "raw" or not isinstance(request["symbols"], list) \
            or (contract == CONTRACT_V2 and request.get("input_contract") != CONTRACT_V2):
        raise ValueError("Archived dataset request is invalid")
    if any(not isinstance(symbol, str) for symbol in request["symbols"]):
        raise ValueError("Archived dataset symbols must be strings")
    symbols = _parse_symbols(" ".join(request["symbols"]))
    if list(symbols) != request["symbols"]:
        raise ValueError("Archived dataset symbol order or values are invalid")
    lo, hi = _parse_range(request["start"], request["end"])
    _exact_tree(root, symbols)
    expected_paths = set(_expected_paths(symbols))
    entries = manifest["files"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= _MAX_FILES:
        raise ValueError("Archived dataset file table exceeds budget")
    table = {}
    total = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) not in ({"path", "sha256", "bytes", "role"},
                                                              {"path", "sha256", "bytes", "role", "rows"}):
            raise ValueError("Archived dataset file entry is invalid")
        relative = _validate_relative(entry["path"])
        if relative in table or type(entry["bytes"]) is not int or not 0 <= entry["bytes"] <= _MAX_FILE_BYTES \
                or not isinstance(entry["sha256"], str) or not _HEX64.fullmatch(entry["sha256"]):
            raise ValueError("Archived dataset file identity is invalid or duplicated")
        table[relative] = entry
        total += entry["bytes"]
    if set(table) != expected_paths or total > _MAX_TOTAL_BYTES:
        raise ValueError("Archived dataset file table is not exact or exceeds budget")
    expected_roles = {
        "source/plan.json": "source_plan",
        "source/reference/stock_basic.json.gz": "source_stock_basic",
        "source/reference/trade_calendar.json.gz": "source_trade_calendar",
        "normalized/bars.parquet": "normalized_bars",
    }
    for symbol in symbols:
        prefix = "source/symbols/" + _safe_source_name(symbol) + "/"
        expected_roles[prefix + "rows.json.gz"] = "source_raw_rows"
        expected_roles[prefix + "daily.parquet"] = "source_typed_daily"
    for relative, entry in table.items():
        if entry["role"] != expected_roles[relative] \
                or ((relative == "normalized/bars.parquet") != (entry.get("rows") == manifest["summary"].get("rows"))):
            raise ValueError("Archived dataset file role/row contract is invalid")
    payload_by_path = {}
    for relative in sorted(expected_paths):
        entry = table[relative]
        payload = _read_bounded_regular(root / relative, min(_MAX_FILE_BYTES, entry["bytes"]), relative)
        if len(payload) != entry["bytes"] or _sha(payload) != entry["sha256"]:
            raise ValueError("Archived dataset payload hash or size mismatch: " + relative)
        payload_by_path[relative] = payload

    files = {
        "plan.json": payload_by_path["source/plan.json"],
        "reference/stock_basic.json.gz": payload_by_path["source/reference/stock_basic.json.gz"],
        "reference/trade_calendar.json.gz": payload_by_path["source/reference/trade_calendar.json.gz"],
    }
    source_snapshot = manifest["source_snapshot"]
    if not isinstance(source_snapshot, dict) or source_snapshot.get("capture_id") != request["capture_id"] \
            or not isinstance(source_snapshot.get("symbols"), list):
        raise ValueError("Archived source snapshot identity is invalid")
    evidence = {}
    payloads = {}
    for item in source_snapshot["symbols"]:
        if not isinstance(item, dict) or not isinstance(item.get("manifest"), dict) or item.get("symbol") in evidence:
            raise ValueError("Archived source symbol evidence is invalid or duplicated")
        symbol = item["symbol"]
        if symbol not in symbols:
            raise ValueError("Archived source evidence contains an unexpected symbol")
        evidence[symbol] = item["manifest"]
        prefix = "source/symbols/" + _safe_source_name(symbol) + "/"
        payloads[symbol] = {"raw": payload_by_path[prefix + "rows.json.gz"],
                            "daily": payload_by_path[prefix + "daily.parquet"]}
    material = _normalize_material(capture_id=request["capture_id"], symbols=symbols, lo=lo, hi=hi,
                                   payloads=payloads, files=files, source_manifests=evidence, contract=contract)
    if source_snapshot != material["source_snapshot"]:
        raise ValueError("Archived source snapshot does not match saved raw/typed/calendar semantics")
    preview_core = _preview_core(request["capture_id"], symbols, lo, hi, material, contract)
    if manifest["preview_hash"] != digest(preview_core):
        raise ValueError("Archived preview hash does not match saved source semantics")
    summary_keys = ("rows", "actual_sessions", "fields", "qualification", "time_policy", "limitations")
    if contract == CONTRACT_V2:
        summary_keys += ("input_contract", "tradable_rows", "suspended_rows", "valuation_policy", "research_policy", "execution_policy")
    expected_summary = {key: preview_core[key] for key in summary_keys}
    if manifest["summary"] != expected_summary:
        raise ValueError("Archived dataset summary does not match saved source semantics")
    normalized = manifest["normalized"]
    if normalized != {"path": "normalized/bars.parquet", "rows": material["bars"].height,
                       "semantics_sha256": material["semantic_sha256"]}:
        raise ValueError("Archived normalized identity does not match source semantics")
    stored = _parquet_frame(payload_by_path["normalized/bars.parquet"], "normalized/bars.parquet", _MAX_ROWS)
    stored = ordered_bars(stored)
    if stored.columns != material["bars"].columns or stored.schema != material["bars"].schema \
            or not stored.equals(material["bars"]):
        raise ValueError("Normalized bars disagree with saved raw/typed/calendar semantics")
    return {"root": root, "manifest": manifest, "marker_payload": marker_payload,
            "payloads": payload_by_path, "bars": stored, "sessions": material["sessions"],
            "contract": contract,
            "preview": {"preview_hash": manifest["preview_hash"], **preview_core}}


def inspect_archived_daily_dataset(root) -> dict:
    """Deeply validate a package without consulting its original source workspace."""
    checked = _inspect_package(root)
    preview = checked["preview"]
    return {"dataset_id": checked["manifest"]["dataset_id"], "path": str(checked["root"]), **preview}


class ArchivedDailyDatasetProvider:
    """Read-only provider for one finite archived daily dataset package."""

    def __init__(self, root, adjustment="raw"):
        if adjustment != "raw":
            raise ValueError("Archived daily dataset supports adjustment='raw' only")
        self.root = _safe_package_root(root)
        self.adjustment = adjustment

    def load(self, request: DataRequest) -> DataBatch:
        if not isinstance(request, DataRequest):
            raise ValueError("load requires a DataRequest")
        if request.timeframe != Timeframe.DAILY:
            raise ValueError("Archived daily dataset supports timeframe=1d only; no fallback or resampling")
        checked = _inspect_package(self.root)  # deliberately no cache: every read observes tampering
        manifest = checked["manifest"]
        packaged = manifest["request"]
        if not set(request.symbols) <= set(packaged["symbols"]):
            raise ValueError("Requested symbols exceed the finite archived dataset")
        lo, hi = date.fromisoformat(packaged["start"]), date.fromisoformat(packaged["end"])
        if request.start < lo or request.end > hi:
            raise ValueError("Requested dates exceed the finite archived dataset")
        sessions = tuple(day for day in checked["sessions"] if request.start <= day <= request.end)
        if not sessions:
            raise ValueError("No archived calendar trading sessions in requested subrange")
        bars = checked["bars"].filter(
            pl.col("symbol").is_in(request.symbols)
            & pl.col("datetime").dt.date().is_between(request.start, request.end)
        )
        bars = ordered_bars(bars)
        if bars.height != len(request.symbols) * len(sessions):
            raise ValueError("Requested package slice lacks exact symbol/session coverage")
        source_evidence = manifest["source_snapshot"]
        common = {
            "dataset_id": manifest["dataset_id"],
            "source_evidence": source_evidence,
            "qualification": "research_only",
            "historical_available_at_verified": False,
            "time_policy": TIME_POLICY,
        }
        if checked["contract"] == CONTRACT_V2:
            common.update(input_contract=CONTRACT_V2,
                          suspension_state_preserved=True,
                          valuation_policy="carry_last_tradable_close_then_vendor_previous_close_for_valuation_only")
        file_entries = []
        for entry in manifest["files"]:
            file_entries.append({**entry, "path": str(self.root / entry["path"]), **common})
        file_entries.append({"path": str(self.root / MARKER), "sha256": _sha(checked["marker_payload"]),
                             "bytes": len(checked["marker_payload"]), "role": "dataset_manifest", **common})
        snapshot_id = digest({"dataset_id": manifest["dataset_id"], "request": request,
                              "bars_semantics_sha256": digest(_semantic_rows(bars))})
        snapshot = DataSnapshot(snapshot_id=snapshot_id, source="archived_retro_daily_dataset",
                                adjustment="raw", files=tuple(file_entries))
        return DataBatch(bars=bars, snapshot=snapshot)
