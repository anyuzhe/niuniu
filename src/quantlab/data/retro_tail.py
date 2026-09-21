"""Opt-in raw-daily tail fallback to a retro_daily capture, activated by a data-root pointer.

Why a pointer in the data root (not a workspace path threaded through callers):
every consumer that builds a provider via ``local_data_provider(data_root)`` — the
experiment runner, approval-time freeze, qualification, campaign, tracking and the
local data tools — reads only from ``data_root``.  A single data-root pointer makes
them all see the *same* Baostock + retro-tail data, preserving the
"approve A == execute A" approval-freeze invariant.

Boundaries (never violated here):
- raw only.  A qfq request whose range exceeds Baostock coverage still fails; this
  module never fabricates adjustment history.
- research_only.  The retro capture is a supplier retrospective observation; the tail
  is never upgraded to Strict PIT.
- additive and inert.  Without the pointer file, behaviour is byte-for-byte unchanged.
"""
from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

import polars as pl

from quantlab.domain import Timeframe

POINTER_RELPATH = "catalog/retro_daily_tail.json"
POINTER_FORMAT = "retro-daily-tail-pointer-v1"
TZ = "Asia/Shanghai"
_EPOCH = date(1970, 1, 1)


def pointer_path(root) -> Path:
    return Path(root).resolve() / POINTER_RELPATH


def load_pointer(root):
    """Return the validated pointer dict, or None when absent/invalid (never raises)."""
    path = pointer_path(root)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("format") != POINTER_FORMAT:
        return None
    capture = value.get("capture_path")
    if not isinstance(capture, str) or not capture:
        return None
    capture_path = Path(capture)
    if capture_path.is_symlink() or not capture_path.is_dir():
        return None
    # output root is three levels up from <output>/_market_data/retro_daily/<capture_id>
    return {"capture_path": capture_path, "output": capture_path.parents[2],
            "capture_id": capture_path.name,
            "coverage_end": value.get("coverage_end"), "digest": value.get("digest")}


class RetroTail:
    """Loads the recent raw-daily tail from a verified retro_daily pack."""

    def __init__(self, pointer: dict):
        self.output = pointer["output"]
        self.capture_id = pointer["capture_id"]
        self.coverage_end = pointer.get("coverage_end")
        self.digest = pointer.get("digest")

    def _planned_symbols(self, store):
        return set(store.plan(self.capture_id, with_symbols=True)["symbols"])

    def tail_bars(self, request):
        """Return (frame_with_date, files) mapped to the MQC daily bar schema.

        The frame keeps a temporary ``date`` column so the caller can drop rows that
        are already covered by Baostock per symbol; only the strict tail is appended.
        """
        from quantlab.data.retro_daily import RetroDailyStore
        store = RetroDailyStore(output=str(self.output))
        planned = self._planned_symbols(store)
        wanted = [s for s in sorted(request.symbols) if s in planned]
        files = [{"path": str(self.output / "_market_data" / "retro_daily" / self.capture_id),
                  "retro_capture_id": self.capture_id, "retro_digest": self.digest,
                  "coverage_end": self.coverage_end, "role": "raw_daily_tail"}]
        if not wanted:
            return pl.DataFrame(), files
        panel, meta = store.read_panel(self.capture_id, start=request.start, end=request.end,
                                       symbols=wanted, require_complete=False)
        if panel.is_empty():
            return pl.DataFrame(), files
        frame = panel.filter(
            pl.all_horizontal([pl.col(c).is_finite() for c in ("open", "high", "low", "close", "volume")])
            & (pl.min_horizontal("open", "high", "low", "close") > 0)
            & (pl.col("volume") >= 0)
            & pl.col("amount").is_finite() & (pl.col("amount") >= 0)
        )
        if frame.is_empty():
            return pl.DataFrame(), files
        frame = frame.with_columns(
            pl.col("date").dt.combine(time(15)).dt.replace_time_zone(TZ).alias("datetime")
        ).select(
            "date",
            pl.col("code").alias("symbol"),
            pl.col("code").str.slice(0, 2).alias("exchange"),
            "datetime",
            pl.col("datetime").alias("available_at"),
            pl.lit(Timeframe.DAILY.value).alias("timeframe"),
            *[pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close", "volume")],
            pl.col("amount").cast(pl.Float64).alias("turnover"),
            pl.lit(1.0).alias("adj_factor"),
        )
        return frame, files
