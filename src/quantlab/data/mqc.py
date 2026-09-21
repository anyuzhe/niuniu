"""Read-only MQC Parquet adapter. Never rewrites the user's data lake."""

import hashlib
import io
import re
from datetime import time, date
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from quantlab.data.base import DataBatch, DataRequest, DataSnapshot
from quantlab.data.validation import validate_bars
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest

TZ = "Asia/Shanghai"


class MQCParquetProvider:
    def __init__(self, root: Path, adjustment: str = "raw", *, retro_tail=None):
        if adjustment not in {"raw", "qfq"}:
            raise ValueError("adjustment must be raw or qfq")
        self.root = Path(root).resolve()
        self.adjustment = adjustment
        self.retro_tail = retro_tail

    def load(self, request: DataRequest) -> DataBatch:
        if request.timeframe in (Timeframe.MIN15,Timeframe.MIN30,Timeframe.MIN60):
            from dataclasses import replace
            from quantlab.multitimeframe.resample import resample_bars
            base=self.load(replace(request,timeframe=Timeframe.MIN5))
            bars=resample_bars(base.bars,request.timeframe)
            identity=digest({'base':base.snapshot.snapshot_id,'request':request,'resampling':'complete_ashare_sessions_v1'})
            return DataBatch(bars,DataSnapshot(identity,'mqc_session_resample',self.adjustment,base.snapshot.files))
        suffix = {Timeframe.DAILY: "daily", Timeframe.MIN5: "min5",Timeframe.MIN1:'min1'}[request.timeframe]
        directory = (
            self.root / "lake/bronze/provider=baostock" / f"stock_kline_{suffix}"
            if self.adjustment == "raw" else self.root / "lake/silver" / f"qfq_kline_{suffix}"
        )
        frames, files = [], []
        for symbol in sorted(request.symbols):
            if not re.fullmatch(r"(?:sh|sz|bj)\.\d{6}", symbol):
                raise ValueError(f"Invalid MQC symbol: {symbol}")
            path = directory / f"{symbol.replace('.', '_')}.parquet"
            eastmoney_minute = False
            if request.timeframe == Timeframe.MIN1 and not path.exists():
                if self.adjustment == 'qfq':
                    raise ValueError('缺少前复权 1m 数据；不会把原始 1m 或 5m 当作前复权 1m。可由用户主动选择 raw 并检查可用日期。')
                path=self.root/'lake/bronze/provider=eastmoney/stock_kline_min1'/f"{symbol.replace('.', '_')}.parquet"
                eastmoney_minute=True
            # Hash the exact bytes decoded, avoiding a read/hash race.
            payload = path.read_bytes()
            frame = pl.from_arrow(pq.read_table(io.BytesIO(payload)))
            files.append({"path": str(path), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
            if eastmoney_minute:
                # stock_zh_a_hist_min_em 1m: unadjusted, volume in lots.
                # Preserve raw prices; invalid/zero OHLC is rejected below.
                files[-1]['normalization']='eastmoney_min1_raw_lots_to_shares_v1'
                files[-1]['schema_source']='https://akshare.akfamily.xyz/data/stock/stock.html'
                if frame.filter(~pl.col('time').str.contains(r'^\d{12}0000$') | pl.col('time').is_null()).height:
                    raise ValueError('Unsupported MQC Eastmoney minute timestamp format')
                frame=frame.with_columns(pl.lit('3').alias('adjustflag'),(pl.col('volume')*100).alias('volume'))
            if frame.filter(pl.col("code").is_null() | (pl.col("code") != symbol)).height:
                raise ValueError(f"Symbol mismatch in {path}")
            if self.adjustment == "raw" and frame.filter(pl.col("adjustflag").is_null() | (pl.col("adjustflag") != "3")).height:
                raise ValueError(f"Expected unadjusted bars in {path}")
            frame = frame.filter(pl.col("date").is_between(request.start, request.end))
            if frame.is_empty():
                raise ValueError(f"No requested bars for {symbol}")
            if request.timeframe == Timeframe.DAILY:
                timestamp = pl.col("date").dt.combine(time(15)).dt.replace_time_zone(TZ)
            elif eastmoney_minute:
                timestamp = pl.col('time').str.slice(0,14).str.strptime(pl.Datetime('us'),'%Y%m%d%H%M%S',strict=True).dt.replace_time_zone(TZ)
            else:
                timestamp = pl.col("time").str.strptime(pl.Datetime("us"), "%Y%m%d%H%M%S%3f", strict=True).dt.replace_time_zone(TZ)
            frame = frame.with_columns(timestamp.alias("datetime"))
            if frame.filter(pl.col("datetime").dt.date() != pl.col("date")).height:
                raise ValueError(f"Date/time mismatch in {path}")
            frame = frame.select(
                pl.col("code").alias("symbol"),
                pl.lit(symbol[:2]).alias("exchange"), "datetime",
                pl.col("datetime").alias("available_at"),
                pl.lit(request.timeframe.value).alias("timeframe"),
                *[pl.col(c).cast(pl.Float64) for c in ["open", "high", "low", "close", "volume"]],
                pl.col("amount").cast(pl.Float64).alias("turnover"),
                (pl.col("factor") if "factor" in frame.columns else pl.lit(1.0)).alias("adj_factor"),
            )
            frames.append(frame)
        if self.retro_tail is not None and request.timeframe == Timeframe.DAILY and self.adjustment == "raw" and frames:
            # Extend the recent raw-daily tail beyond Baostock coverage from a verified retro pack.
            # Kept raw-only (no qfq fabrication); snapshot identity absorbs the retro source so the
            # approval-time freeze and reproduction capture exactly what the runner used.
            base = pl.concat(frames)
            covered = base.group_by("symbol").agg(pl.col("datetime").dt.date().max().alias("md"))
            tail, tail_files = self.retro_tail.tail_bars(request)
            if tail.height:
                tail = tail.join(covered, on="symbol", how="left")
                tail = tail.filter(pl.col("date") > pl.col("md").fill_null(pl.lit(date(1970, 1, 1)))).drop("md", "date")
                if tail.height:
                    frames.append(tail)
                    files.extend(tail_files)
        bars = pl.concat(frames).sort("symbol", "datetime")
        validate_bars(bars)
        snapshot_id = digest({"files": files, "request": request, "adjustment": self.adjustment})
        return DataBatch(bars, DataSnapshot(snapshot_id, "mqc_parquet", self.adjustment, tuple(files)))
