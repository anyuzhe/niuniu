from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from quantlab.data.validation import ordered_bars
from quantlab.domain import Event, Timeframe, Zone, ZoneUpdate
from quantlab.storage.codec import digest


@dataclass(frozen=True)
class FVGAnalysis:
    zones: tuple[Zone, ...]
    updates: tuple[ZoneUpdate, ...]
    counts: pl.DataFrame


class FVGZoneEngine:
    """Three-bar strict gap. No displacement, session or trend filters.

    Creation records never include future invalidation. Updates describe only
    observed lifecycle changes; later updates do not supersede history.
    """

    def flags(self, bars: pl.DataFrame) -> pl.DataFrame:
        return ordered_bars(bars).with_columns(
            pl.col("high").shift(2).over("symbol").alias("first_high"),
            pl.col("low").shift(2).over("symbol").alias("first_low"),
        ).with_columns(
            (pl.col("low") > pl.col("first_high")).alias("bull_created"),
            (pl.col("high") < pl.col("first_low")).alias("bear_created"),
        )

    @staticmethod
    def _zone(row: dict) -> Zone | None:
        if row["bull_created"]:
            lower, upper, direction = row["first_high"], row["low"], 1
        elif row["bear_created"]:
            lower, upper, direction = row["high"], row["first_low"], -1
        else:
            return None
        identity = {"kind": "fvg", "symbol": row["symbol"], "timeframe": row["timeframe"],
            "created_at": row["datetime"], "available_at": row["available_at"],
            "lower_price": lower, "upper_price": upper, "direction": direction, "version": "1.0.0"}
        return Zone(digest(identity), "fvg", row["symbol"], Timeframe(row["timeframe"]),
            row["datetime"], row["available_at"], lower, upper, direction)

    def detect(self, bars: pl.DataFrame, events: Sequence[Event] = ()) -> list[Zone]:
        """Bar-only detection; external events are not needed by this rule."""
        result = [self._zone(row) for row in self.flags(bars).filter(
            pl.col("bull_created") | pl.col("bear_created")).iter_rows(named=True)]
        return sorted(result, key=lambda z: (z.available_at, z.symbol, z.zone_id))

    def analyze(self, bars: pl.DataFrame) -> FVGAnalysis:
        frame = self.flags(bars)
        zones, updates, counts = [], [], []
        active: dict[str, tuple[Zone, ZoneUpdate]] = {}
        symbol = None
        for row in frame.iter_rows(named=True):
            if row["symbol"] != symbol:
                active = {}
                symbol = row["symbol"]
            # Only zones known before this bar are eligible for touches.
            for zone_id, (zone, previous) in list(active.items()):
                lo, hi = zone.lower_price, zone.upper_price
                overlaps = row["low"] <= hi and row["high"] >= lo
                jumped = row["high"] < lo if zone.direction == 1 else row["low"] > hi
                if not overlaps and not jumped:
                    continue
                ratio = previous.filled_ratio
                if overlaps:
                    penetration = (hi - row["low"]) / (hi - lo) if zone.direction == 1 else (row["high"] - lo) / (hi - lo)
                    ratio = max(ratio, min(1.0, max(0.0, penetration)))
                status = "invalidated" if jumped else "filled" if ratio == 1.0 else "active"
                update = ZoneUpdate(zone_id, row["available_at"], previous.touch_count + int(overlaps), ratio, status)
                updates.append(update)
                if status == "active":
                    active[zone_id] = zone, update
                else:
                    del active[zone_id]
            zone = self._zone(row)
            if zone is not None:
                zones.append(zone)
                update = ZoneUpdate(zone.zone_id, zone.available_at, 0, 0.0, "active")
                updates.append(update)
                active[zone.zone_id] = zone, update
            # Null until the third bar; counts are relative to loaded history.
            counts.append(None if row["first_high"] is None else len(active))
        return FVGAnalysis(
            tuple(sorted(zones, key=lambda z: (z.available_at, z.symbol, z.zone_id))),
            tuple(sorted(updates, key=lambda u: (u.available_at, u.zone_id))),
            frame.select("symbol", "datetime", "available_at").with_columns(pl.Series("active_count", counts, dtype=pl.Int64)),
        )
