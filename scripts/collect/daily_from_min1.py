#!/usr/bin/env python3
"""由通达信 1 分钟线合成当日日K，写入 Baostock 日K文件（provider=baostock/stock_kline_daily）。

背景：Baostock 日K只能一只一只地取，全市场每天约 2 小时。通达信 1 分钟线本来就每天全市场采集，
2026-09-08 至 09-30 的 8.3 万个"股票×日"对账：开盘价 99.98%、最高/最低/收盘 99.99%–100% 与 Baostock 完全一致；
成交量因通达信按 100 股取整，97% 在 0.1% 以内。所以日K改由 1 分钟线合成，合成不了的再回退到 Baostock。

合成规则（逐只股票）：
  - 只取交易时段内的 1 分钟线：09:31–11:30 与 13:01–15:00，必须正好 240 根，否则跳过（交给 Baostock）。
    通达信偶尔多出 13:00 的假线（2026-09-28 有 4,154 只、09-30 有 11 只，是 11:30 那根的复制品），按时段过滤掉。
  - 开盘 = 第一根的开盘；最高/最低 = 全天极值；收盘 = 最后一根的收盘；成交量、成交额 = 合计。
  - 成交量为 0（停牌）不写，和 Baostock 一样停牌日没有行；价格非正或高低价自相矛盾的跳过。
  - 该日已有行不覆盖（除非 --replace）；没有日K文件的新股不处理（交给 Baostock 的整只回补）。
  - 前一个交易日（各文件最后日期里最常见的那个）缺行的股票不合成（停牌或取数失败），由 Baostock 按状态补尾部，避免在中间留空洞。
  - 每次运行把"哪些股票的哪天是合成的"写到 provider=tdx/bars_daily_from_min1/date=YYYY-MM-DD.parquet。
日K文件没有来源列，合成行的 fetch_ts 与别的行格式相同，来源以上面的记录为准。

5 分钟线（--kind min5）：同样由 1 分钟线合成，写进 provider=baostock/stock_kline_min5。每 5 根 1 分钟线并成 1 根，
时间标签取这 5 分钟的结束时刻（09:35 … 11:30、13:05 … 15:00，一天 48 根），记录在 provider=tdx/bars_min5_from_min1。
精度比日K差：沪市主板/科创板的收盘价 99.8% 一致、成交量 90% 误差在 0.3% 以内；深市主板/创业板收盘价 72–76% 一致
（95%/89% 在 1 个最小报价单位内），成交量只有 42–45% 在 0.2% 以内，因为通达信与 Baostock 对 5 分钟内成交的归属略有不同，
这是两家数据本身的差异，不是合成方式的问题（通达信自己的 5 分钟线同样如此）。全天合计不受影响。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import polars as pl

DEFAULT_ROOT = Path(os.environ.get("NIUNU_DATA_ROOT", "/Volumes/Lexar/niuniu-data"))
BARS_PER_DAY = 240


def in_session(hhmm: str) -> bool:
    return "0931" <= hhmm <= "1130" or "1301" <= hhmm <= "1500"


def session_frame(min1_path: Path, day: str):
    """读出当日交易时段内的 1 分钟线。返回 (DataFrame | None, 跳过原因 | None, 通达信原始行数, 时段内行数)。"""
    frame = pl.read_parquet(min1_path, columns=["date", "time", "open", "high", "low", "close", "volume", "amount"])
    frame = frame.filter(pl.col("date").cast(pl.String) == day)
    raw = frame.height
    if raw == 0:
        return None, "no_day_rows", 0, 0
    frame = frame.with_columns(pl.col("time").str.slice(8, 4).alias("hhmm"))
    frame = frame.filter(pl.col("hhmm").map_elements(in_session, return_dtype=pl.Boolean)).sort("time")
    if frame.height != BARS_PER_DAY or frame["time"].n_unique() != BARS_PER_DAY:
        return None, "bad_row_count", raw, frame.height
    volume = int(frame["volume"].sum())
    if volume <= 0:
        return None, "no_volume", raw, frame.height
    return frame, None, raw, frame.height


def derive_min5(frame: pl.DataFrame, day: str):
    """240 根 1 分钟线 → 48 根 5 分钟线。时间标签 = 这 5 分钟的结束时刻（和 Baostock 一样），
    即 09:31–09:35 → 09:35，……，14:56–15:00 → 15:00。每个桶必须正好 5 根。
    零成交的桶也写（Baostock 的 5 分钟线里同样有，一天固定 48 根）。返回 (行列表 | None, 跳过原因 | None)。"""
    stamp = day.replace("-", "")
    frame = frame.with_columns(
        (pl.col("hhmm").str.slice(0, 2).cast(pl.Int32) * 60 + pl.col("hhmm").str.slice(2, 2).cast(pl.Int32)).alias("minute"))
    frame = frame.with_columns((((pl.col("minute") + 4) // 5) * 5).alias("end")).sort("time")
    groups = frame.group_by("end", maintain_order=True).agg(
        pl.col("open").first().alias("open"), pl.col("high").max().alias("high"), pl.col("low").min().alias("low"),
        pl.col("close").last().alias("close"), pl.col("volume").sum().alias("volume"),
        pl.col("amount").sum().alias("amount"), pl.len().alias("n"))
    if groups.height != BARS_PER_DAY // 5 or groups["n"].min() != 5 or groups["n"].max() != 5:
        return None, "bad_bucket"
    rows = []
    for rec in groups.iter_rows(named=True):
        top, bottom = max(rec["open"], rec["close"]), min(rec["open"], rec["close"])
        if min(rec["open"], rec["high"], rec["low"], rec["close"]) <= 0 or rec["high"] < top or rec["low"] > bottom:
            return None, "bad_price"
        end = rec["end"]
        rows.append({"time": f"{stamp}{end // 60:02d}{end % 60:02d}00000", "open": float(rec["open"]),
                     "high": float(rec["high"]), "low": float(rec["low"]), "close": float(rec["close"]),
                     "volume": int(rec["volume"]), "amount": float(rec["amount"])})
    return rows, None


def derive(min1_path: Path, day: str):
    """返回 (行字典 | None, 跳过原因 | None, 通达信原始行数, 时段内行数)。"""
    frame, why, raw, used = session_frame(min1_path, day)
    if why:
        return None, why, raw, used
    volume = int(frame["volume"].sum())
    row = {"open": float(frame["open"][0]), "high": float(frame["high"].max()), "low": float(frame["low"].min()),
           "close": float(frame["close"][-1]), "volume": volume, "amount": float(frame["amount"].sum())}
    top, bottom = max(row["open"], row["close"]), min(row["open"], row["close"])
    if min(row["open"], row["high"], row["low"], row["close"]) <= 0 or row["high"] < top or row["low"] > bottom:
        return None, "bad_price", raw, frame.height
    return row, None, raw, frame.height


def write_atomic(frame: pl.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        frame.write_parquet(tmp)
        back = pl.read_parquet(tmp)
        if back.height != frame.height or back.schema != frame.schema:
            raise ValueError("读回校验失败")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def apply_one(name: str, daily_dir: Path, min1_dir: Path, day: str, replace: bool, dry_run: bool, prev: str | None):
    daily_path, min1_path = daily_dir / f"{name}.parquet", min1_dir / f"{name}.parquet"
    if not daily_path.is_file():
        return name, "no_daily_file", None
    if not min1_path.is_file():
        return name, "no_min1_file", None
    old = pl.read_parquet(daily_path)
    has_day = old.filter(pl.col("date").cast(pl.String) == day).height > 0
    if has_day and not replace:
        return name, "already_present", None
    row, why, raw, used = derive(min1_path, day)
    if why:
        return name, why, None
    last = old["date"].cast(pl.String).max() if old.height else None
    if last and last > day and not replace:
        return name, "newer_rows_exist", None
    if prev and not replace and (last is None or last < prev):
        return name, "behind", None   # 前一个交易日缺行（停牌或取数失败）：交给 Baostock 按状态补尾部，别在中间留空洞
    template = old.tail(1)
    new = pl.DataFrame({
        "date": [datetime.strptime(day, "%Y-%m-%d").date()], "code": [name.replace("_", ".", 1)],
        "open": [row["open"]], "high": [row["high"]], "low": [row["low"]], "close": [row["close"]],
        "volume": [row["volume"]], "amount": [row["amount"]],
        "adjustflag": [template["adjustflag"][0] if "adjustflag" in old.columns and old.height else "3"],
        "fetch_ts": [time.strftime("%Y-%m-%dT%H:%M:%S")],
    }).select(old.columns).cast(old.schema)
    merged = pl.concat([old.filter(pl.col("date").cast(pl.String) != day), new]).sort("date")
    if merged.select("date").n_unique() != merged.height:
        return name, "duplicate_dates", None
    if not dry_run:
        write_atomic(merged, daily_path)
    return name, "derived", {"code": new["code"][0], "volume": row["volume"], "amount": row["amount"],
                              "tdx_rows": raw, "session_rows": used}


def apply_one_min5(name: str, min5_dir: Path, min1_dir: Path, day: str, replace: bool, dry_run: bool, prev: str | None):
    """把当日 48 根 5 分钟线写进 Baostock 5 分钟文件。规则与日K一致；当日已有不足 48 根（取到一半）的算缺，整天重写。"""
    min5_path, min1_path = min5_dir / f"{name}.parquet", min1_dir / f"{name}.parquet"
    if not min5_path.is_file():
        return name, "no_daily_file", None
    if not min1_path.is_file():
        return name, "no_min1_file", None
    old = pl.read_parquet(min5_path)
    old_day = old.filter(pl.col("date").cast(pl.String) == day).height
    if old_day >= 48 and not replace:
        return name, "already_present", None
    frame, why, raw, used = session_frame(min1_path, day)
    if why:
        return name, why, None
    rows, why = derive_min5(frame, day)
    if why:
        return name, why, None
    last = old["date"].cast(pl.String).max() if old.height else None
    if last and last > day and not replace:
        return name, "newer_rows_exist", None
    if prev and not replace and (last is None or last < prev):
        return name, "behind", None
    template = old.tail(1)
    code = name.replace("_", ".", 1)
    new = pl.DataFrame({
        "date": [datetime.strptime(day, "%Y-%m-%d").date()] * len(rows), "time": [r["time"] for r in rows],
        "code": [code] * len(rows), "open": [r["open"] for r in rows], "high": [r["high"] for r in rows],
        "low": [r["low"] for r in rows], "close": [r["close"] for r in rows], "volume": [r["volume"] for r in rows],
        "amount": [r["amount"] for r in rows],
        "adjustflag": [template["adjustflag"][0] if "adjustflag" in old.columns and old.height else "3"] * len(rows),
        "fetch_ts": [time.strftime("%Y-%m-%dT%H:%M:%S")] * len(rows),
    }).select(old.columns).cast(old.schema)
    merged = pl.concat([old.filter(pl.col("date").cast(pl.String) != day), new]).sort(["date", "time"])
    if merged.select(["date", "time"]).n_unique() != merged.height:
        return name, "duplicate_dates", None
    if not dry_run:
        write_atomic(merged, min5_path)
    return name, "derived", {"code": code, "volume": int(sum(r["volume"] for r in rows)),
                              "amount": float(sum(r["amount"] for r in rows)), "tdx_rows": raw, "session_rows": used}


def cmd_apply(args) -> int:
    started = time.time()
    root = Path(args.data_root)
    is_min5 = args.kind == "min5"
    daily_dir = Path(args.daily_dir) if args.daily_dir else root / (
        "lake/bronze/provider=baostock/stock_kline_min5" if is_min5 else "lake/bronze/provider=baostock/stock_kline_daily")
    min1_dir = Path(args.min1_dir) if args.min1_dir else root / "lake/bronze/provider=tdx/kline_min1"
    log_dir = Path(args.log_dir) if args.log_dir else root / (
        "lake/bronze/provider=tdx/bars_min5_from_min1" if is_min5 else "lake/bronze/provider=tdx/bars_daily_from_min1")
    worker = apply_one_min5 if is_min5 else apply_one
    names = sorted(p.stem for p in daily_dir.glob("*.parquet"))
    if args.only:
        wanted = set(args.only.split(","))
        names = [n for n in names if n in wanted]
    prev = None
    if not args.replace:   # 前一个交易日 = 各文件“早于本日的最后日期”里最常见的那个（重跑也稳定）
        import duckdb
        rows = duckdb.sql(f"select m, count(*) c from (select max(date) filter (where date < '{args.day}')::varchar m "
                          f"from read_parquet('{daily_dir}/*.parquet', filename=true) group by filename) "
                          f"where m is not null group by m order by c desc limit 1").fetchall()
        prev = rows[0][0] if rows else None
    counts: dict[str, int] = {}
    derived, failed = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(worker, n, daily_dir, min1_dir, args.day, args.replace, args.dry_run, prev) for n in names]
        for name, future in zip(names, futures):
            try:
                _, status, info = future.result()
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{name}: {exc}")
                continue
            counts[status] = counts.get(status, 0) + 1
            if status == "derived":
                derived.append(info)
    if derived and not args.dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)
        frame = pl.DataFrame(derived).with_columns(
            pl.lit(datetime.strptime(args.day, "%Y-%m-%d").date()).alias("date"),
            pl.lit(datetime.now().strftime("%Y-%m-%dT%H:%M:%S")).alias("derived_at"))
        frame = frame.select(["date", "code", "volume", "amount", "tdx_rows", "session_rows", "derived_at"])
        out = log_dir / f"date={args.day}.parquet"
        if out.exists() and not args.replace:   # 已有的合成记录保留，只追加新合成的股票
            frame = pl.concat([pl.read_parquet(out), frame]).unique(["code"], keep="last")
        elif out.exists():
            frame = pl.concat([pl.read_parquet(out).filter(~pl.col("code").is_in(frame["code"])), frame])
        write_atomic(frame.sort("code"), out)
    print(json.dumps({"day": args.day, "kind": args.kind, "dry_run": args.dry_run, "prev_day": prev, "symbols": len(names), "derived": len(derived),
                      "status": counts, "failed": failed, "elapsed_s": round(time.time() - started, 1)},
                     ensure_ascii=False))
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--day", required=True)
    p.add_argument("--kind", choices=("daily", "min5"), default="daily", help="合成日K（默认）或 5 分钟线")
    p.add_argument("--data-root", default=str(DEFAULT_ROOT))
    p.add_argument("--daily-dir")
    p.add_argument("--min1-dir")
    p.add_argument("--log-dir")
    p.add_argument("--only", help="逗号分隔的文件名（如 sh_600000），测试用")
    p.add_argument("--replace", action="store_true", help="覆盖该日已有的行（测试用）")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    return cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
