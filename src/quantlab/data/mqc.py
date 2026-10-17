"""Read-only MQC Parquet adapter. Never rewrites the user's data lake."""

import hashlib
import io
import re
from datetime import date, time, timedelta
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from quantlab.data.base import DataBatch, DataRequest, DataSnapshot
from quantlab.data.dataset_registry import RegistryError, resolve
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

    def _directory(self, timeframe: Timeframe) -> tuple[Path, str | None]:
        if timeframe == Timeframe.DAILY:
            name = 'bars.daily.raw.baostock' if self.adjustment == 'raw' else 'bars.daily.qfq'
            legacy = ('lake/bronze/provider=baostock/stock_kline_daily' if self.adjustment == 'raw'
                      else 'lake/silver/qfq_kline_daily')
        elif timeframe == Timeframe.MIN5:
            name = 'bars.min5.raw.baostock' if self.adjustment == 'raw' else 'bars.min5.qfq'
            legacy = ('lake/bronze/provider=baostock/stock_kline_min5' if self.adjustment == 'raw'
                      else 'lake/silver/qfq_kline_min5')
        else:
            suffix = {Timeframe.MIN1: 'min1'}[timeframe]
            directory = (self.root / 'lake/bronze/provider=baostock' / f'stock_kline_{suffix}'
                         if self.adjustment == 'raw' else self.root / 'lake/silver' / f'qfq_kline_{suffix}')
            return directory, None
        resolved = resolve(self.root, name, legacy_default=legacy)
        return resolved.path, resolved.registry_sha256

    # 已退市股票：Baostock 供应商自己的不复权 / 前复权孪生（单源，未经两源除权核对）。只在数据集登记表登记了
    # 对应名称时才作为回退；没有登记表的测试根用旧默认目录。在市目录里没有该证券文件时才用。
    DELISTED = {'raw': ('bars.daily.raw.delisted', 'lake/bronze/provider=baostock/stock_kline_daily_delisted'),
                'qfq': ('bars.daily.qfq.delisted', 'lake/bronze/provider=baostock/stock_kline_daily_delisted_qfq_bs')}

    def _delisted_path(self, symbol: str, adjustment: str | None = None) -> Path | None:
        name, legacy = self.DELISTED[adjustment or self.adjustment]
        try:
            directory = resolve(self.root, name, legacy_default=legacy).path
        except RegistryError:
            return None
        path = directory / f"{symbol.replace('.', '_')}.parquet"
        return path if path.is_file() else None

    def _delisted_frame(self, symbol: str, path: Path, frame: pl.DataFrame, files: list) -> pl.DataFrame:
        """把退市孪生文件整理成在市文件的列：qfq 加 factor（= 前复权收盘 / 不复权收盘），去掉状态列。"""
        flag = '2' if self.adjustment == 'qfq' else '3'
        if frame.filter(pl.col('adjustflag').is_null() | (pl.col('adjustflag') != flag)).height:
            raise ValueError(f"退市股 {symbol} 的 adjustflag 不是 {flag}: {path}")
        files[-1]['source'] = 'delisted_single_source_baostock'
        if self.adjustment == 'qfq':
            raw_path = self._delisted_path(symbol, 'raw')
            if raw_path is None:
                raise ValueError(f"退市股 {symbol} 缺少不复权孪生文件，无法得出复权因子")
            payload = raw_path.read_bytes()
            raw = pl.from_arrow(pq.read_table(io.BytesIO(payload))).select('date', pl.col('close').alias('_raw_close'))
            files.append({"path": str(raw_path), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
                          'source': 'delisted_single_source_baostock_raw_twin'})
            frame = frame.join(raw, on='date', how='left')
            if frame.filter(pl.col('_raw_close').is_null() | (pl.col('_raw_close') <= 0)).height:
                raise ValueError(f"退市股 {symbol} 的不复权孪生与前复权行不一一对应")
            frame = frame.with_columns((pl.col('close') / pl.col('_raw_close')).alias('factor')).drop('_raw_close')
        return frame.drop([c for c in ('preclose', 'tradestatus', 'isST', 'fetch_ts') if c in frame.columns])

    def _enforce_qfq_coverage(self, request: DataRequest) -> dict[str, bool]:
        """Apply DATA's published qfq boundary; return which symbols have truncated history.

        ``history_truncated=true`` means DATA cut the history at ``valid_from`` (an unconfirmed
        corporate action), so earlier requests are refused.  ``false`` means ``valid_from`` is
        simply where the security's history begins (its listing), so an earlier start behaves
        like raw data: the window is filtered, not refused.  A coverage file without the
        column keeps the strict behaviour for every symbol.
        """
        if self.adjustment != 'qfq' or request.timeframe not in (Timeframe.DAILY, Timeframe.MIN5):
            return {}
        daily = resolve(self.root, 'bars.daily.qfq', legacy_default='lake/silver/qfq_kline_daily')
        coverage_path = daily.path / '_meta' / 'coverage.parquet'
        if not coverage_path.exists():
            if daily.source == 'registry':
                raise ValueError('DATA发布的qfq缺少_meta/coverage.parquet；拒绝回退旧qfq')
            return {}  # legacy/test roots predate the DATA publication contract
        columns = pl.read_parquet_schema(coverage_path)
        wanted = ['code', 'valid_from'] + (['history_truncated'] if 'history_truncated' in columns else [])
        coverage = pl.read_parquet(coverage_path, columns=wanted)
        if coverage.select(pl.col('code').is_duplicated().any()).item():
            raise ValueError('DATA qfq coverage存在重复证券')
        valid_from = dict(zip(coverage['code'].to_list(), coverage['valid_from'].to_list()))
        truncated_flags = (dict(zip(coverage['code'].to_list(), coverage['history_truncated'].to_list()))
                           if 'history_truncated' in coverage.columns else {})
        truncated = {}
        for symbol in request.symbols:
            value = valid_from.get(symbol)
            if not isinstance(value, str):
                if self._delisted_path(symbol) is not None:
                    truncated[symbol] = False   # 退市孪生：历史从上市起完整，不受发布覆盖表约束
                    continue
                raise ValueError(f'DATA qfq coverage缺少证券 {symbol}')
            try:
                first = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f'DATA qfq valid_from无效: {symbol}={value!r}') from exc
            flag = truncated_flags.get(symbol, True) if truncated_flags else True
            if type(flag) is not bool:
                raise ValueError(f'DATA qfq history_truncated无效: {symbol}={flag!r}')
            truncated[symbol] = flag
            if flag and request.start < first:
                raise ValueError(f'DATA未提供 {symbol} 在 {first.isoformat()} 之前的qfq；不会回退旧qfq或用raw补齐')
        return truncated

    def load(self, request: DataRequest) -> DataBatch:
        if request.timeframe in (Timeframe.MIN15,Timeframe.MIN30,Timeframe.MIN60):
            from dataclasses import replace
            from quantlab.multitimeframe.resample import resample_bars
            base=self.load(replace(request,timeframe=Timeframe.MIN5))
            bars=resample_bars(base.bars,request.timeframe)
            identity=digest({'base':base.snapshot.snapshot_id,'request':request,'resampling':'complete_ashare_sessions_v1'})
            return DataBatch(bars,DataSnapshot(identity,'mqc_session_resample',self.adjustment,base.snapshot.files))
        suffix = {Timeframe.DAILY: "daily", Timeframe.MIN5: "min5",Timeframe.MIN1:'min1'}[request.timeframe]
        directory, registry_sha256 = self._directory(request.timeframe)
        truncated = self._enforce_qfq_coverage(request)
        frames, files, tail_ranges, base_present = [], [], {}, set()
        tail_enabled = (
            self.retro_tail is not None
            and request.timeframe == Timeframe.DAILY
            and self.adjustment == "raw"
        )
        for symbol in sorted(request.symbols):
            if not re.fullmatch(r"(?:sh|sz|bj)\.\d{6}", symbol):
                raise ValueError(f"Invalid MQC symbol: {symbol}")
            path = directory / f"{symbol.replace('.', '_')}.parquet"
            eastmoney_minute = False
            delisted = False
            if request.timeframe == Timeframe.DAILY and not path.exists():
                fallback = self._delisted_path(symbol)
                if fallback is not None:
                    path, delisted = fallback, True
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
            if delisted:
                frame = self._delisted_frame(symbol, path, frame, files)
            if self.adjustment == "raw" and frame.filter(pl.col("adjustflag").is_null() | (pl.col("adjustflag") != "3")).height:
                raise ValueError(f"Expected unadjusted bars in {path}")
            if self.adjustment == "qfq" and registry_sha256 is not None and truncated.get(symbol, True):
                first_available = frame["date"].min()
                if first_available is None:
                    raise ValueError(f"DATA发布的qfq文件为空: {symbol}")
                if request.start < first_available:
                    raise ValueError(f"DATA未提供 {symbol} 在 {first_available} 之前的qfq；不会回退旧qfq或用raw补齐")
            # The extension boundary is the full MQC file's maximum daily date, never
            # the maximum after request-window filtering.  Retro may extend only the
            # strict suffix; it cannot replace this trunk or fill an internal gap.
            trunk_end = frame["date"].max() if request.timeframe == Timeframe.DAILY else None
            if tail_enabled:
                if trunk_end is None:
                    raise ValueError(f"MQC daily trunk has no bars for {symbol}")
                if request.end > trunk_end:
                    tail_ranges[symbol] = (max(request.start, trunk_end + timedelta(days=1)), request.end)
            frame = frame.filter(pl.col("date").is_between(request.start, request.end))
            if frame.is_empty() and symbol not in tail_ranges:
                raise ValueError(f"No requested bars for {symbol}")
            if frame.is_empty():
                continue
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
            base_present.add(symbol)
        if tail_ranges:
            # RetroTail verifies exact raw+typed source bytes and requires every planned
            # trading session.  It raises on empty/missing/suspended/invalid rows rather
            # than silently truncating the requested extension.
            tail, tail_files = self.retro_tail.tail_bars(request, tail_ranges)
            if tail is None:  # Pointer absent: preserve the original MQC-only behavior.
                missing = sorted(set(tail_ranges) - base_present)
                if missing:
                    raise ValueError(f"No requested bars for {missing[0]}")
            else:
                frames.append(tail.drop("date"))
                files.extend(tail_files)
        bars = pl.concat(frames).sort("symbol", "datetime")
        validate_bars(bars)
        snapshot_id = digest({"files": files, "request": request, "adjustment": self.adjustment,
                              "dataset_registry_sha256": registry_sha256})
        return DataBatch(bars, DataSnapshot(snapshot_id, "mqc_parquet", self.adjustment, tuple(files)))
