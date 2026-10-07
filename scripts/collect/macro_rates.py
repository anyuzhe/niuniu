#!/usr/bin/env python3
"""Market-context datasets (DATA side): ETF shares, interest rates, macro series, index valuation.

All eight datasets are bronze, idempotent and refreshed by ``update`` (used by
``daily_close_update``; the first run also backfills what the source still offers).
The fetch/parse code is the vendored a-stock-data core; this file only decides what to
fetch, how to merge it, and where it lands.

=====================  =====================================================  ===========================
dataset id             source                                                 output (under lake/bronze)
=====================  =====================================================  ===========================
etf_shares_sse         SSE ETF scale archive, one request per trading day     provider=sse/etf_shares/date=YYYY-MM-DD.parquet
etf_shares_szse        SZSE fund list, **latest snapshot only**               provider=szse/etf_shares/date=<snapshot>.parquet
cn_yield_curve         ChinaBond treasury / bank AAA / MTN AAA curves         provider=chinabond/yield_curve/year=YYYY.parquet
cn_repo_fixing         ChinaMoney FR (about 3y window) and FDR (about 1y)     provider=chinamoney/repo_fixing/{FR,FDR}.parquet
cn_lpr_history         Eastmoney RPTA_WEB_RATE                                provider=eastmoney/lpr_history/lpr.parquet
cn_macro_monthly       Eastmoney RPT_ECONOMY_* (PMI, CPI, PPI, M2, ...)       provider=eastmoney/macro_monthly/<name>.parquet
cn_social_financing    PBC aggregate financing (2021 onwards)                 provider=pbc/social_financing/social_financing.parquet
index_valuation_csindex  CSI index PE / dividend yield (about one month)      provider=csindex/index_valuation/<000300>.parquet
=====================  =====================================================  ===========================

Point in time: the monthly macro tables carry ``period`` (the statistical month) and a
**conservative** ``visible_from`` (month end + a fixed lag per series).  The sources do not
publish the real release date, so ``visible_from`` is an upper bound, not a fact.

Usage:  update [--dataset NAME ...] [--through YYYY-MM-DD] [--max-seconds N]
"""
from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect.fundamentals_history import core, trading_days, write_parquet  # noqa: E402
from collect.paths import DATA_ROOT  # noqa: E402

BRONZE = Path(DATA_ROOT) / "lake" / "bronze"
RECEIPTS = BRONZE / "_macro_receipts"

SSE_DIR = BRONZE / "provider=sse" / "etf_shares"
SZSE_DIR = BRONZE / "provider=szse" / "etf_shares"
CB_DIR = BRONZE / "provider=chinabond" / "yield_curve"
REPO_DIR = BRONZE / "provider=chinamoney" / "repo_fixing"
LPR_FILE = BRONZE / "provider=eastmoney" / "lpr_history" / "lpr.parquet"
MACRO_DIR = BRONZE / "provider=eastmoney" / "macro_monthly"
SOCIAL_FILE = BRONZE / "provider=pbc" / "social_financing" / "social_financing.parquet"
INDEX_DIR = BRONZE / "provider=csindex" / "index_valuation"

SSE_PACE = 0.4
SSE_SCAN_FROM = date(2010, 1, 1)       # the SSE archive returns nothing before 2012-01 (probed 2026-10-07)
SSE_EMPTY_FINAL_AFTER_DAYS = 7         # an empty trading day older than this is final, not "not yet published"
CB_FIRST_DAY = date(2006, 3, 1)
SOCIAL_FIRST_YEAR = 2021               # older PBC workbooks use another layout (vendored code refuses them)

# EM report -> (output name, days after the end of the statistical month before the value is surely public)
MACRO = {
    "pmi": ("RPT_ECONOMY_PMI", 1),
    "cpi": ("RPT_ECONOMY_CPI", 15),
    "ppi": ("RPT_ECONOMY_PPI", 15),
    "currency_supply": ("RPT_ECONOMY_CURRENCY_SUPPLY", 20),
    "rmb_loan": ("RPT_ECONOMY_RMB_LOAN", 20),
    "industry_growth": ("RPT_ECONOMY_INDUS_GROW", 20),
    "retail_sales": ("RPT_ECONOMY_TOTAL_RETAIL", 20),
    "asset_investment": ("RPT_ECONOMY_ASSET_INVEST", 20),
    "customs": ("RPT_ECONOMY_CUSTOMS", 20),
    "reserves": ("RPT_ECONOMY_GOLD_CURRENCY", 12),
    "gdp": ("RPT_ECONOMY_GDP", 25),
}
SOCIAL_LAG_DAYS = 20

INDEX_CODES = ["000016", "000300", "000905", "000852", "000510", "932000", "000688", "000906", "000985"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def drop_source_cols(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in ("source", "source_url") if c in df.columns])


def merge_by(old: pd.DataFrame | None, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if old is None or old.empty:
        merged = new.copy()
    else:
        merged = pd.concat([old, new], ignore_index=True)
    return merged.drop_duplicates(keys, keep="last").sort_values(keys).reset_index(drop=True)


def read_if(path: Path) -> pd.DataFrame | None:
    return pd.read_parquet(path) if path.is_file() else None


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


# ------------------------------------------------------------------ ETF shares
def sse_have() -> set[date]:
    return {date.fromisoformat(p.stem.split("=", 1)[1]) for p in SSE_DIR.glob("date=*.parquet")}


def sse_empty() -> set[date]:
    return {date.fromisoformat(p.stem.split("=", 1)[1]) for p in (SSE_DIR / "_empty").glob("date=*.parquet")}


def sse_fetch(c, day: date) -> pd.DataFrame | None:
    """None when the exchange has no data for that day (holiday or not published yet)."""
    try:
        df = c.etf_shares(day.isoformat(), "SH")
    except ValueError as exc:
        if "没有 ETF 份额数据" in str(exc):
            return None
        raise
    return drop_source_cols(df)


def sse_first_day(c, days: list[date]) -> date | None:
    """First trading day with data: probe the first trading day of each month from 2010."""
    seen = set()
    for d in days:
        if d < SSE_SCAN_FROM or (d.year, d.month) in seen:
            continue
        seen.add((d.year, d.month))
        time.sleep(SSE_PACE)
        if sse_fetch(c, d) is not None:
            # data started somewhere in the previous month at the earliest
            prev = date(d.year - (d.month == 1), 12 if d.month == 1 else d.month - 1, 1)
            return next(x for x in days if x >= prev)
    return None


def update_etf_sse(c, through: date, max_seconds: float) -> dict:
    days = [d for d in trading_days() if d <= through]
    have, empty = sse_have(), sse_empty()
    first = min(have) if have else sse_first_day(c, days)
    if first is None:
        raise RuntimeError("上交所 ETF 份额：2010 年以来没有找到任何有数据的日期，接口可能改了")
    final_before = through - timedelta(days=SSE_EMPTY_FINAL_AFTER_DAYS)
    todo = [d for d in days if d >= first and d not in have and not (d in empty and d < final_before)]
    started, done, none, failed, errors = time.monotonic(), 0, 0, 0, {}
    for day in reversed(todo):                       # newest first: the daily run must get today
        if time.monotonic() - started > max_seconds:
            break
        try:
            time.sleep(SSE_PACE)
            df = sse_fetch(c, day)
        except Exception as exc:                     # noqa: BLE001 - recorded, the next run retries
            failed += 1
            errors[day.isoformat()] = f"{type(exc).__name__}: {exc}"[:200]
            if failed >= 8 and done == 0:
                break
            continue
        if df is None:
            none += 1
            if day < final_before:
                write_parquet(pd.DataFrame({"_empty_reason": ["no data on this trading day"]}),
                              SSE_DIR / "_empty" / f"date={day}.parquet")
            continue
        write_parquet(df, SSE_DIR / f"date={day}.parquet")
        (SSE_DIR / "_empty" / f"date={day}.parquet").unlink(missing_ok=True)
        done += 1
    remaining = len([d for d in todo if d not in sse_have() and d not in sse_empty()])
    return {"done": done, "empty": none, "failed": failed, "remaining": remaining, "first_day": first.isoformat(),
            "errors": dict(list(errors.items())[:5])}


def update_etf_szse(c, through: date) -> dict:
    try:
        df = c.etf_shares(through.isoformat(), "SZ")
        snapshot = through
    except ValueError as exc:
        found = re.search(r"快照日期是 (\d{4}-\d{2}-\d{2})", str(exc))
        if not found:
            raise
        snapshot = date.fromisoformat(found.group(1))
        df = c.etf_shares(snapshot.isoformat(), "SZ")
    write_parquet(drop_source_cols(df), SZSE_DIR / f"date={snapshot}.parquet")   # a later fetch of the same date is more settled
    return {"done": 1, "rows": len(df), "snapshot": snapshot.isoformat()}


# ------------------------------------------------------------------ rates
def update_yield_curve(c, through: date) -> dict:
    files = sorted(CB_DIR.glob("year=*.parquet"))
    start = CB_FIRST_DAY
    if files:
        latest = pd.read_parquet(files[-1], columns=["date"])["date"].max()
        start = date.fromisoformat(str(latest)) - timedelta(days=10)
    if start > through:
        return {"done": 0, "rows": 0}
    try:
        df = c.chinabond_yield_curve(start.isoformat(), through.isoformat(), "all")
    except ValueError as exc:                         # no trading day in the range (holiday stretch)
        return {"done": 0, "rows": 0, "note": str(exc)[:120]}
    df = drop_source_cols(df)
    written = 0
    for year, part in df.groupby(df["date"].str[:4]):
        path = CB_DIR / f"year={year}.parquet"
        write_parquet(merge_by(read_if(path), part, ["date", "curve"]), path)
        written += 1
    return {"done": written, "rows": len(df), "from": start.isoformat()}


def update_repo_fixing(c) -> dict:
    rows = 0
    for kind in ("FR", "FDR"):
        df = drop_source_cols(c.repo_fixing_rates(kind))
        path = REPO_DIR / f"{kind}.parquet"
        write_parquet(merge_by(read_if(path), df, ["date"]), path)
        rows += len(df)
        time.sleep(0.5)
    return {"done": 2, "rows": rows}


def update_lpr(c) -> dict:
    df = drop_source_cols(c.lpr_history())
    write_parquet(df.sort_values("date").reset_index(drop=True), LPR_FILE)
    return {"done": 1, "rows": len(df)}


# ------------------------------------------------------------------ macro
def update_macro_monthly(c) -> dict:
    done, rows, failed, errors = 0, 0, 0, {}
    for name, (report, lag) in MACRO.items():
        try:
            data = c._em_datacenter_strict(report, "", "REPORT_DATE", "-1", 500, 5000)
            if not data:
                raise RuntimeError("empty report")
            df = pd.DataFrame(data)
            period = pd.to_datetime(df["REPORT_DATE"].astype(str).str[:10])
            df.insert(0, "period", period.dt.date.map(lambda d: d.isoformat()))
            df.insert(1, "visible_from", period.dt.date.map(lambda d: (month_end(d) + timedelta(days=lag)).isoformat()))
            df["fetched_at"] = now_iso()
            write_parquet(df.sort_values("period").reset_index(drop=True), MACRO_DIR / f"{name}.parquet")
            done += 1
            rows += len(df)
        except Exception as exc:                      # noqa: BLE001
            failed += 1
            errors[name] = f"{type(exc).__name__}: {exc}"[:200]
    return {"done": done, "rows": rows, "failed": failed, "errors": errors}


def update_social_financing(c, through: date) -> dict:
    old = read_if(SOCIAL_FILE)
    years = list(range(SOCIAL_FIRST_YEAR, through.year + 1)) if old is None else \
        [through.year] + ([through.year - 1] if through.month <= 3 else [])
    frames, errors = [], {}
    for year in years:
        try:
            frames.append(c.pboc_social_financing(year))
        except ValueError as exc:                     # the year page is not there yet (early January)
            errors[str(year)] = str(exc)[:120]
        time.sleep(1.0)
    if not frames:
        raise RuntimeError(f"人民银行社融：没有取到任何年份 {errors}")
    df = pd.concat(frames, ignore_index=True)
    df.insert(1, "visible_from", df["month"].map(
        lambda m: (month_end(date.fromisoformat(m + "-01")) + timedelta(days=SOCIAL_LAG_DAYS)).isoformat()))
    df["fetched_at"] = now_iso()
    write_parquet(merge_by(old, df, ["month"]), SOCIAL_FILE)
    return {"done": 1, "rows": len(df), "years": years, "errors": errors}


def update_index_valuation(c) -> dict:
    done, failed, errors = 0, 0, {}
    for code in INDEX_CODES:
        try:
            df = drop_source_cols(c.index_valuation(code))
            df["fetched_at"] = now_iso()
            path = INDEX_DIR / f"{code}.parquet"
            write_parquet(merge_by(read_if(path), df, ["date"]), path)
            done += 1
        except Exception as exc:                      # noqa: BLE001
            failed += 1
            errors[code] = f"{type(exc).__name__}: {exc}"[:200]
        time.sleep(1.0)
    return {"done": done, "failed": failed, "errors": errors}


# ------------------------------------------------------------------ cli
DATASETS = ["etf_shares_sse", "etf_shares_szse", "cn_yield_curve", "cn_repo_fixing", "cn_lpr_history",
            "cn_macro_monthly", "cn_social_financing", "index_valuation_csindex"]


def run_one(name: str, c, through: date, max_seconds: float) -> dict:
    if name == "etf_shares_sse":
        return update_etf_sse(c, through, max_seconds)
    if name == "etf_shares_szse":
        return update_etf_szse(c, through)
    if name == "cn_yield_curve":
        return update_yield_curve(c, through)
    if name == "cn_repo_fixing":
        return update_repo_fixing(c)
    if name == "cn_lpr_history":
        return update_lpr(c)
    if name == "cn_macro_monthly":
        return update_macro_monthly(c)
    if name == "cn_social_financing":
        return update_social_financing(c, through)
    if name == "index_valuation_csindex":
        return update_index_valuation(c)
    raise ValueError(name)


def update_cmd(args) -> int:
    through = date.fromisoformat(args.through) if args.through else date.today()
    names = args.dataset or DATASETS
    c = core()
    started, results, bad = time.monotonic(), {}, []
    for name in names:
        t0 = time.monotonic()
        try:
            info = run_one(name, c, through, args.max_seconds)
            # SSE day failures are retried by the next run and only count when nothing at all got through
            if info.get("failed") and (name != "etf_shares_sse" or not info.get("done")):
                bad.append(name)
        except Exception as exc:                      # noqa: BLE001 - one dataset never stops the others
            info = {"error": f"{type(exc).__name__}: {exc}"[:300]}
            bad.append(name)
        info["elapsed_s"] = round(time.monotonic() - t0, 1)
        results[name] = info
    summary = {"through": through.isoformat(), "datasets": results, "failed": bad,
               "elapsed_s": round(time.monotonic() - started, 1)}
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    (RECEIPTS / f"update-{through}-{datetime.now().strftime('%H%M%S')}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("update")
    u.add_argument("--dataset", action="append", choices=DATASETS)
    u.add_argument("--through")
    u.add_argument("--max-seconds", type=float, default=600.0, help="time cap for the SSE per-day backfill")
    args = parser.parse_args()
    return update_cmd(args)


if __name__ == "__main__":
    sys.exit(main())
