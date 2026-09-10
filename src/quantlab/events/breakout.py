import polars as pl

from quantlab.domain import Event, Timeframe
from quantlab.storage.codec import digest
from quantlab.data.validation import ordered_bars


class BreakoutHighEngine:
    """Every close strictly above the prior N highs is a distinct event."""

    def __init__(self, lookback: int = 20):
        if type(lookback) is not int or lookback < 1:
            raise ValueError("lookback must be a positive integer")
        self.lookback = lookback

    def flags(self, bars: pl.DataFrame) -> pl.DataFrame:
        return ordered_bars(bars).with_columns(
            pl.col("high").rolling_max(self.lookback).shift(1).over("symbol").alias("level")
        ).with_columns((pl.col("close") > pl.col("level")).alias("breakout_high"))

    def detect(self, bars: pl.DataFrame) -> list[Event]:
        events = []
        for row in self.flags(bars).filter(pl.col("breakout_high")).iter_rows(named=True):
            metadata = {"level": row["level"], "close": row["close"], "lookback": self.lookback}
            identity = {"symbol": row["symbol"], "timeframe": row["timeframe"], "occurred_at": row["datetime"],
                "available_at": row["available_at"], "factor_id": "EVT.BREAKOUT_HIGH", "version": "1.0.0", **metadata}
            events.append(Event(digest(identity), identity["factor_id"], row["symbol"], Timeframe(row["timeframe"]),
                row["datetime"], row["available_at"], direction=1, strength=row["close"] / row["level"] - 1,
                confirmed_at=row["available_at"], metadata=metadata))
        return sorted(events, key=lambda e: (e.available_at, e.symbol, e.event_id))
