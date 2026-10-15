#!/usr/bin/env python3
"""Build the real-data bar sample used by factor_causality_audit.py (qfq daily OHLCV + Baostock valuation columns).

12 symbols (first of a universe.json list), last 700 sessions. Columns: symbol, datetime (15:00 Asia/Shanghai), available_at (= datetime), timeframe,
open/high/low/close/volume/turnover (qfq), adj_factor (=1), bs_pe_ttm / bs_pb_mrq / bs_ps_ttm / bs_pcf_ncf_ttm (Baostock valuation, as published),
bs_turn_pct (PLACEHOLDER = volume/1e7: the lake has no turnover-rate column, so BAO.TURN_PCT is audited on a stand-in series).

    python scripts/research/build_audit_bars.py --data-root /Volumes/Lexar/niuniu-data --universe artifacts/_gtja191_confirm_2026-10-15/universe.json --out /tmp/audit_bars.parquet
"""
import argparse, json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

TZ = ZoneInfo("Asia/Shanghai")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--universe", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--symbols", type=int, default=12)
    ap.add_argument("--tail", type=int, default=700)
    args = ap.parse_args()
    root = args.data_root / "lake"
    symbols = json.loads(args.universe.read_text())["symbols"][: args.symbols]
    frames = []
    for symbol in symbols:
        name = symbol.replace(".", "_") + ".parquet"
        q = pl.read_parquet(root / "silver/qfq_kline_daily" / name).select("date", "open", "high", "low", "close", "volume", "amount")
        v = pl.read_parquet(root / "bronze/provider=baostock/valuation_daily_v1" / name).select(
            pl.col("date").str.to_date(), pl.col("peTTM").alias("bs_pe_ttm"), pl.col("pbMRQ").alias("bs_pb_mrq"),
            pl.col("psTTM").alias("bs_ps_ttm"), pl.col("pcfNcfTTM").alias("bs_pcf_ncf_ttm"))
        frames.append(q.join(v, on="date", how="left").with_columns(pl.lit(symbol).alias("symbol")))
    frame = pl.concat(frames).sort("symbol", "date")
    keep = sorted(frame["date"].unique().to_list())[-args.tail:]
    frame = frame.filter(pl.col("date").is_in(keep))
    for column in ("bs_pe_ttm", "bs_pb_mrq", "bs_ps_ttm", "bs_pcf_ncf_ttm"):
        frame = frame.with_columns(pl.col(column).cast(pl.Float64, strict=False))
    frame = frame.with_columns(
        pl.col("date").map_elements(lambda d: datetime.combine(d, time(15), tzinfo=TZ), return_dtype=pl.Datetime("us", "Asia/Shanghai")).alias("datetime"),
        pl.col("amount").alias("turnover"), pl.col("volume").cast(pl.Float64), pl.lit("1d").alias("timeframe"), pl.lit(1.0).alias("adj_factor"),
        (pl.col("volume") / 1e7).alias("bs_turn_pct")).with_columns(pl.col("datetime").alias("available_at")).drop("date", "amount")
    frame.write_parquet(args.out)
    print(frame.height, frame["symbol"].n_unique())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
