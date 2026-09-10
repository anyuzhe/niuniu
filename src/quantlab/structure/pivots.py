import polars as pl

from quantlab.data.validation import ordered_bars
from quantlab.domain import Structure, Timeframe
from quantlab.storage.codec import digest


class ConfirmedPivotEngine:
    """Strict extrema; equal highs/lows do not qualify. No alternating filter."""

    def __init__(self, left: int = 2, right: int = 2):
        if any(type(n) is not int or n < 1 for n in (left, right)):
            raise ValueError("left and right must be positive integers")
        self.left, self.right = left, right

    def flags(self, bars: pl.DataFrame) -> pl.DataFrame:
        bars = ordered_bars(bars)
        left, right = self.left, self.right
        high = pl.col("high").shift(right)
        low = pl.col("low").shift(right)
        return bars.with_columns(
            ((high > pl.col("high").rolling_max(left).shift(right + 1))
             & (high > pl.col("high").rolling_max(right))).over("symbol").alias("pivot_high"),
            ((low < pl.col("low").rolling_min(left).shift(right + 1))
             & (low < pl.col("low").rolling_min(right))).over("symbol").alias("pivot_low"),
            pl.col("datetime").shift(right).over("symbol").alias("pivot_at"),
            high.over("symbol").alias("pivot_high_price"),
            low.over("symbol").alias("pivot_low_price"),
            (pl.int_range(pl.len()).over("symbol") >= left + right).alias("ready"),
        )

    def detect(self, bars: pl.DataFrame) -> list[Structure]:
        structures = []
        for row in self.flags(bars).filter(pl.col("ready") & (pl.col("pivot_high") | pl.col("pivot_low"))).iter_rows(named=True):
            for side in ("high", "low"):
                if row[f"pivot_{side}"]:
                    identity = {"kind": f"pivot_{side}", "symbol": row["symbol"], "timeframe": row["timeframe"],
                        "occurred_at": row["pivot_at"], "available_at": row["available_at"],
                        "price": row[f"pivot_{side}_price"], "left": self.left, "right": self.right, "version": "1.0.0"}
                    structures.append(Structure(digest(identity), identity["kind"], row["symbol"], Timeframe(row["timeframe"]),
                        row["pivot_at"], row["available_at"], price=identity["price"]))
        return sorted(structures, key=lambda s: (s.available_at, s.symbol, s.kind))
