"""Fail-closed raw-daily tail reader for a host-created retro capture pointer.

The pointer is opt-in and inert when absent.  When present, its exact bytes, canonical
capture path and current packed-capture index are verified.  Selected symbol bytes are
then read through ``ArchivedDailyBridge``, which compares the original provider response
with the typed parquet.  This source remains retrospective/research-only.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import date, time, timedelta
from pathlib import Path

import polars as pl

from quantlab.domain import Timeframe
from quantlab.storage.codec import digest

POINTER_RELPATH = "catalog/retro_daily_tail.json"
POINTER_FORMAT = "retro-daily-tail-pointer-v1"
TZ = "Asia/Shanghai"
_MAX_POINTER_BYTES = 64_000
_MAX_CHUNK_DAYS = 371
_HEX = frozenset("0123456789abcdef")


def pointer_path(root) -> Path:
    # Do not resolve here: resolving would hide a symlinked data root or catalog.
    return Path(os.path.abspath(os.fspath(root))) / POINTER_RELPATH


def _system_alias_equivalent(lexical: Path, resolved: Path) -> bool:
    """Allow only macOS' fixed /tmp -> /private/tmp and /var -> /private/var aliases."""
    parts = lexical.parts
    if len(parts) < 2 or parts[1] not in {"tmp", "var"}:
        return False
    expected = Path("/private") / parts[1]
    if len(parts) > 2:
        expected = expected.joinpath(*parts[2:])
    return expected == resolved


def _check_ancestors(path: Path, what: str) -> None:
    """Reject links at the object or any lexical ancestor, except fixed system aliases."""
    for candidate in (path, *path.parents):
        try:
            linked = candidate.is_symlink()
        except OSError as error:
            raise ValueError(f"Cannot inspect {what} path") from error
        if not linked:
            continue
        if candidate in {Path("/tmp"), Path("/var")}:
            target = candidate.resolve(strict=True)
            if target == Path("/private") / candidate.name:
                continue
        raise ValueError(f"{what} path contains a symlink: {candidate}")


def _regular_bytes(path: Path, what: str, limit: int) -> bytes:
    _check_ancestors(path, what)
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_size > limit:
            raise ValueError(f"{what} is not a bounded regular file")
        with path.open('rb') as stream:
            payload = stream.read(limit + 1)
    except OSError as error:
        raise ValueError(f"Cannot read {what}") from error
    if len(payload) != stat.st_size or len(payload) > limit:
        raise ValueError(f"{what} changed while being read")
    return payload


def _parse_pointer(root, path: Path, payload: bytes) -> dict:
    def unique_pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('Duplicate retro tail pointer field: ' + key)
            result[key] = item
        return result
    def reject_constant(value):
        raise ValueError('Non-finite pointer value: ' + value)
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_pairs,
                           parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("Retro tail pointer is not valid UTF-8 JSON") from error
    required = {"format", "capture_path", "coverage_end", "digest", "scope"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {'written_by'}:
        raise ValueError("Retro tail pointer fields are invalid")
    if value["format"] != POINTER_FORMAT:
        raise ValueError("Unsupported retro tail pointer format")
    if not isinstance(value['scope'], str) or not value['scope'].strip() or len(value['scope']) > 4000:
        raise ValueError('Retro tail pointer scope must be bounded text')
    if 'written_by' in value and (not isinstance(value['written_by'], str) or len(value['written_by']) > 200):
        raise ValueError('Retro tail pointer written_by must be bounded text')
    expected_digest = value["digest"]
    if not isinstance(expected_digest, str) or len(expected_digest) != 64 \
            or any(char not in _HEX for char in expected_digest):
        raise ValueError("Retro tail pointer digest is invalid")
    try:
        coverage_end = date.fromisoformat(value["coverage_end"])
    except (TypeError, ValueError) as error:
        raise ValueError("Retro tail pointer coverage_end is invalid") from error
    if value['coverage_end'] != coverage_end.isoformat():
        raise ValueError('Retro tail pointer coverage_end must be a canonical ISO date')
    capture_text = value["capture_path"]
    if not isinstance(capture_text, str) or not capture_text or not Path(capture_text).is_absolute():
        raise ValueError("Retro tail capture_path must be absolute")
    supplied = Path(capture_text)
    lexical = Path(os.path.abspath(capture_text))
    if supplied != lexical:
        raise ValueError("Retro tail capture_path is not canonical")
    _check_ancestors(lexical, "Retro tail capture")
    try:
        capture = lexical.resolve(strict=True)
    except OSError as error:
        raise ValueError("Retro tail capture_path does not exist") from error
    if lexical != capture and not _system_alias_equivalent(lexical, capture):
        raise ValueError("Retro tail capture_path is not canonical")
    if not capture.is_dir() or capture.parent.name != "retro_daily" \
            or capture.parent.parent.name != "_market_data":
        raise ValueError("Retro tail capture_path is not a canonical retro_daily capture")
    return {
        "data_root": Path(root), "pointer_path": path,
        "pointer_sha256": hashlib.sha256(payload).hexdigest(), "pointer_bytes": len(payload),
        "capture_path": capture, "output": capture.parents[2], "capture_id": capture.name,
        "coverage_end": coverage_end, "digest": expected_digest, "scope": value["scope"],
    }


def _verify_source(pointer: dict) -> dict:
    """Deep-check capture metadata only when a daily suffix is actually required."""
    from quantlab.data.retro_daily import RetroDailyStore
    store = RetroDailyStore(str(pointer["output"]))
    plan = store.plan(pointer["capture_id"], with_symbols=True)
    index = store.pack_index(pointer["capture_id"])
    if index is None:
        raise ValueError("Retro tail capture has no packed source index")
    index_checksum = digest(index)
    if index_checksum != pointer["digest"]:
        raise ValueError("Retro tail pointer digest does not match current pack index")
    plan_start, plan_end = date.fromisoformat(plan["start"]), date.fromisoformat(plan["end"])
    if not plan_start <= pointer["coverage_end"] <= plan_end:
        raise ValueError("Retro tail coverage_end is outside the capture plan")
    index_path = pointer["capture_path"] / "packs" / "index.json"
    index_payload = _regular_bytes(index_path, "Retro tail pack index", 200_000_000)
    try:
        exact_index = json.loads(index_payload)
    except ValueError as error:
        raise ValueError("Retro tail pack index is not valid JSON") from error
    if not isinstance(exact_index, dict) or exact_index.get("checksum") != pointer["digest"]:
        raise ValueError("Retro tail exact pack index checksum differs from pointer digest")
    exact_core = {key: item for key, item in exact_index.items() if key != "checksum"}
    if digest(exact_core) != pointer["digest"] or exact_core != index:
        raise ValueError("Retro tail pack index changed while being validated")
    return {**pointer, "plan": plan, "pack_index_path": index_path,
            "pack_index_sha256": hashlib.sha256(index_payload).hexdigest(),
            "pack_index_bytes": len(index_payload)}


def _load_pointer_declaration(root):
    path = pointer_path(root)
    try:
        os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError("Cannot inspect retro tail pointer") from error
    payload = _regular_bytes(path, "Retro tail pointer", _MAX_POINTER_BYTES)
    return _parse_pointer(root, path, payload)


def load_pointer(root):
    """Return a fully verified pointer, ``None`` only when the pointer is absent."""
    pointer = _load_pointer_declaration(root)
    return None if pointer is None else _verify_source(pointer)


class RetroTail:
    """Lazily loads only the requested extension beyond each MQC full-file cutoff."""

    def __init__(self, data_root):
        self.data_root = Path(data_root)
        self._pointer_identity = None
        self._source_identity = None
        self.output = None
        self.capture_id = None
        self.coverage_end = None
        self.digest = None

    def _revalidate(self):
        pointer = _load_pointer_declaration(self.data_root)
        if pointer is None:
            if self._pointer_identity is not None:
                raise ValueError("Retro tail pointer disappeared")
            return None
        pointer_identity = pointer["pointer_sha256"]
        if self._pointer_identity is not None and pointer_identity != self._pointer_identity:
            raise ValueError("Retro tail pointer or pack index changed for this provider instance")
        current = _verify_source(pointer)
        source_identity = (current["digest"], current["pack_index_sha256"])
        if self._source_identity is not None and source_identity != self._source_identity:
            raise ValueError("Retro tail pointer or pack index changed for this provider instance")
        self._pointer_identity = pointer_identity
        self._source_identity = source_identity
        self.output = current["output"]
        self.capture_id = current["capture_id"]
        self.coverage_end = current["coverage_end"].isoformat()
        self.digest = current["digest"]
        return current

    @staticmethod
    def _chunks(start: date, end: date):
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=_MAX_CHUNK_DAYS - 1))
            yield cursor, chunk_end
            cursor = chunk_end + timedelta(days=1)

    @staticmethod
    def _validate_window(frame: pl.DataFrame, symbol: str, expected: list[date]) -> None:
        if not expected:
            raise ValueError(f"Retro tail window has no trading sessions for {symbol}")
        actual = frame["date"].to_list() if frame.height else []
        if actual != expected:
            missing = sorted(set(expected) - set(actual))
            raise ValueError(f"Retro tail missing trading day for {symbol}: {missing[:3]}")
        if frame.filter(pl.col("tradestatus") != 1).height:
            raise ValueError(f"Retro tail contains suspended session for {symbol}")
        required = ("open", "high", "low", "close", "volume", "amount")
        if any(frame[name].null_count() for name in required):
            raise ValueError(f"Retro tail has null required value for {symbol}")
        invalid = frame.filter(
            pl.any_horizontal([~pl.col(name).is_finite() for name in required])
            | (pl.min_horizontal("open", "high", "low", "close") <= 0)
            | (pl.col("high") < pl.max_horizontal("open", "low", "close"))
            | (pl.col("low") > pl.min_horizontal("open", "high", "close"))
            | (pl.col("volume") < 0) | (pl.col("amount") < 0)
        )
        if invalid.height:
            raise ValueError(f"Retro tail has invalid OHLCV for {symbol}")

    def tail_bars(self, request, ranges: dict[str, tuple[date, date]]):
        """Return verified normalized tail rows and compact actual-source evidence."""
        if request.timeframe != Timeframe.DAILY or not ranges:
            raise ValueError("Retro tail requires nonempty daily extension ranges")
        current = self._revalidate()
        if current is None:
            return None, []
        plan = current["plan"]
        plan_start = date.fromisoformat(plan["start"])
        coverage_end = current["coverage_end"]
        if not set(ranges) <= set(request.symbols):
            raise ValueError("Retro tail ranges differ from the data request")

        from quantlab.agent.qm50_archived_inputs import ArchivedDailyBridge
        bridge = ArchivedDailyBridge(self.output)
        from quantlab.data.session_coverage import calendar_sessions
        _, _, references = bridge._source(self.capture_id)
        calendar = pl.DataFrame(references['trade_calendar'],
                                schema=['calendar_date', 'is_trading_day'], orient='row')
        known_sessions = calendar_sessions(calendar, plan_start, coverage_end)
        frames, symbol_files = [], []
        plan_sha = calendar_sha = basic_sha = None
        for symbol in sorted(ranges):
            start, end = ranges[symbol]
            if start > end or start < plan_start or end > coverage_end:
                raise ValueError(f"Retro tail request outside pointer coverage for {symbol}")
            symbol_frames, manifest = [], None
            expected_all = []
            for chunk_start, chunk_end in self._chunks(start, end):
                chunk_sessions = [day for day in known_sessions if chunk_start <= day <= chunk_end]
                if not chunk_sessions:
                    continue  # Captured calendar explicitly says closed, not a missing trading row.
                chunk_start, chunk_end = chunk_sessions[0], chunk_sessions[-1]
                payloads, files, evidence, sessions, lo, hi = bridge.load(
                    self.capture_id, symbol, chunk_start.isoformat(), chunk_end.isoformat()
                )
                selected = pl.read_parquet(io.BytesIO(payloads[symbol]["daily"])).filter(
                    pl.col("date").is_between(lo, hi)
                ).sort("date")
                expected = [day for day in sessions if lo <= day <= hi]
                self._validate_window(selected, symbol, expected)
                symbol_frames.append(selected)
                expected_all.extend(expected)
                manifest = evidence["symbols"][symbol]
                values = (evidence["capture_plan_sha256"], evidence["calendar_sha256"],
                          evidence["stock_basic_sha256"])
                if plan_sha is None:
                    plan_sha, calendar_sha, basic_sha = values
                elif values != (plan_sha, calendar_sha, basic_sha):
                    raise ValueError("Retro tail capture evidence changed while reading")
            if not symbol_frames:
                continue
            source = pl.concat(symbol_frames).sort("date")
            if source["date"].to_list() != expected_all:
                raise ValueError(f"Retro tail actual window changed for {symbol}")
            frames.append(source.with_columns(
                pl.col("date").dt.combine(time(15)).dt.replace_time_zone(TZ).alias("datetime")
            ).select(
                "date", pl.col("code").alias("symbol"),
                pl.col("code").str.slice(0, 2).alias("exchange"), "datetime",
                pl.col("datetime").alias("available_at"),
                pl.lit(Timeframe.DAILY.value).alias("timeframe"),
                *[pl.col(name).cast(pl.Float64) for name in ("open", "high", "low", "close", "volume")],
                pl.col("amount").cast(pl.Float64).alias("turnover"),
                pl.lit(1.0).alias("adj_factor"),
            ))
            symbol_files.append({
                "path": str(current["capture_path"]), "role": "raw_daily_tail_symbol",
                "retro_capture_id": self.capture_id, "symbol": symbol,
                "window_start": start.isoformat(), "window_end": end.isoformat(),
                "window_first_session": expected_all[0].isoformat(),
                "window_last_session": expected_all[-1].isoformat(), "rows": len(expected_all),
                "raw_sha256": manifest["raw_sha256"],
                "typed_sha256": manifest["parquet_sha256"],
                "manifest_sha256": digest(manifest),
                "source_fetched_at": manifest["fetched_at"],
                "nominal_availability": "session_date 15:00:00 Asia/Shanghai",
                "historic_available_verified": False, "historical_available_at_verified": False,
                "qualification": "provider_retrospective_research_only",
            })

        # Detect pointer/index replacement after the selected bytes were verified.
        self._revalidate()
        if not frames:
            return None, []  # No source rows are needed after a complete trunk ending before a holiday.
        common = {"retro_capture_id": self.capture_id, "historic_available_verified": False,
                  "historical_available_at_verified": False,
                  "qualification": "provider_retrospective_research_only"}
        files = [
            {"path": str(current["pointer_path"]), "role": "raw_daily_tail",
             "source_component": "pointer", "sha256": current["pointer_sha256"],
             "bytes": current["pointer_bytes"], **common},
            {"path": str(current["pack_index_path"]), "role": "raw_daily_tail_pack_index",
             "sha256": current["pack_index_sha256"], "bytes": current["pack_index_bytes"],
             "index_checksum": current["digest"], "capture_plan_sha256": plan_sha,
             "calendar_sha256": calendar_sha, "stock_basic_sha256": basic_sha, **common},
            *symbol_files,
        ]
        return pl.concat(frames).sort("symbol", "date"), files
