#!/usr/bin/env python3
"""Historical fundamentals backfill (DATA side): pledge, earnings forecast, financial
statements, share capital and daily valuation.

Datasets (all bronze, written one partition at a time and resumable; an existing
partition is never rewritten):

* ``pledge``     eastmoney RPT_CSDC_LIST, one file per China-Clear statistics date (Fridays)
                 -> provider=eastmoney/equity_pledge_history/date=YYYY-MM-DD.parquet
* ``forecast``   eastmoney RPT_PUBLIC_OP_NEWPREDICT, one file per notice month
                 -> provider=eastmoney/earnings_forecast_history/month=YYYY-MM.parquet
* ``fin_cpd``    eastmoney RPT_LICO_FN_CPD (profit, ROE, YoY, EPS, **original notice date**)
* ``fin_balance``eastmoney RPT_DMSK_FN_BALANCE (assets, liabilities, debt/asset ratio)
* ``fin_cashflow`` eastmoney RPT_DMSK_FN_CASHFLOW (operating cash flow)
                 -> provider=eastmoney/financial_<kind>/report_date=YYYY-MM-DD.parquet
* ``shares``     eastmoney RPT_F10_EH_EQUITY, one file per stock (total shares by effective date)
                 -> provider=eastmoney/share_capital/<code>.parquet
* ``valuation``  baostock daily k-line fields peTTM/pbMRQ/psTTM/pcfNcfTTM, one file per stock
                 -> provider=baostock/valuation_daily_v1/<code>.parquet

Usage:  plan --dataset D [--from YYYY-MM-DD]        writes a plan, prints its sha256
        apply --plan FILE --approve SHA [--max-seconds N]
        update --dataset D [--through YYYY-MM-DD] [--shard K/N]
                                                    daily incremental refresh (used by daily_close_update)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect.paths import DATA_ROOT  # noqa: E402

BRONZE = Path(DATA_ROOT) / "lake" / "bronze"
PLANS = BRONZE / "_fundamentals_plans"
TODAY = date.today()

FIN = {"fin_cpd": ("RPT_LICO_FN_CPD", "REPORTDATE", "financial_cpd"),
       "fin_balance": ("RPT_DMSK_FN_BALANCE", "REPORT_DATE", "financial_balance"),
       "fin_cashflow": ("RPT_DMSK_FN_CASHFLOW", "REPORT_DATE", "financial_cashflow")}
FIN_FIRST_PERIOD = date(2007, 3, 31)
PLEDGE_FIRST_FRIDAY = date(2014, 1, 3)
FORECAST_FIRST_MONTH = date(2007, 1, 1)
VALUATION_FIELDS = "date,code,close,peTTM,pbMRQ,psTTM,pcfNcfTTM"


# ---------------------------------------------------------------- helpers
def core():
    from collect.public_sources import core as c
    return c()


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def fetched(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["fetched_at"] = datetime.now().astimezone().isoformat()
    return df


def quarter_ends(first: date, last: date):
    out = []
    for y in range(first.year, last.year + 1):
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            q = date(y, m, d)
            if first <= q <= last:
                out.append(q)
    return out


def fridays(first: date, last: date):
    d = first + timedelta(days=(4 - first.weekday()) % 7)
    while d <= last:
        yield d
        d += timedelta(days=7)


def months(first: date, last: date):
    d = date(first.year, first.month, 1)
    while d <= last:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def stock_codes() -> list[str]:
    snaps = sorted((BRONZE / "provider=baostock" / "reference_snapshots").glob("snapshot=*/stock_basic.parquet"))
    if not snaps:
        raise FileNotFoundError("no baostock stock_basic snapshot")
    df = pd.read_parquet(snaps[-1])
    df = df[df["type"].astype(str) == "1"]
    return sorted(df["code"].astype(str).unique())


# ---------------------------------------------------------------- partitions per dataset
def partitions(dataset: str, start: date | None):
    if dataset == "pledge":
        base = BRONZE / "provider=eastmoney" / "equity_pledge_history"
        return [(d.isoformat(), base / f"date={d.isoformat()}.parquet")
                for d in fridays(start or PLEDGE_FIRST_FRIDAY, TODAY)]
    if dataset == "forecast":
        base = BRONZE / "provider=eastmoney" / "earnings_forecast_history"
        first = start or FORECAST_FIRST_MONTH
        return [(m.strftime("%Y-%m"), base / f"month={m.strftime('%Y-%m')}.parquet")
                for m in months(first, TODAY)]
    if dataset in FIN:
        base = BRONZE / "provider=eastmoney" / FIN[dataset][2]
        return [(q.isoformat(), base / f"report_date={q.isoformat()}.parquet")
                for q in quarter_ends(start or FIN_FIRST_PERIOD, TODAY)]
    if dataset == "shares":
        base = BRONZE / "provider=eastmoney" / "share_capital"
        return [(c, base / f"{c.split('.')[-1]}.parquet") for c in stock_codes()]
    if dataset == "valuation":
        base = BRONZE / "provider=baostock" / "valuation_daily_v1"
        return [(c, base / f"{c.replace('.', '_')}.parquet") for c in stock_codes()]
    raise SystemExit(f"unknown dataset {dataset}")


def plan_cmd(args):
    start = date.fromisoformat(args.start) if args.start else None
    parts = partitions(args.dataset, start)
    todo = [k for k, p in parts if not p.exists()]
    body = {"dataset": args.dataset, "start": args.start, "built": TODAY.isoformat(),
            "partitions": len(parts), "missing": todo}
    sha = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    PLANS.mkdir(parents=True, exist_ok=True)
    path = PLANS / f"{args.dataset}-{sha[:12]}.json"
    path.write_text(json.dumps({**body, "sha256": sha}, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"plan": str(path), "sha256": sha, "partitions": len(parts), "missing": len(todo)}))


# ---------------------------------------------------------------- fetchers
def fetch_pledge(c, key: str) -> pd.DataFrame:
    try:
        df = c.equity_pledge(date=key)
    except ValueError as exc:                      # not a statistics date
        return pd.DataFrame({"_empty_reason": [str(exc)[:120]]})
    return df[0] if isinstance(df, tuple) else df


def _forecast_rows(c, lo: date, hi: date, depth=0):
    flt = f"(NOTICE_DATE>='{lo}')(NOTICE_DATE<='{hi}')"
    rows = c._em_event_rows("RPT_PUBLIC_OP_NEWPREDICT", flt,
                            "NOTICE_DATE,SECURITY_CODE,REPORT_DATE,PREDICT_FINANCE_CODE", "-1,1,-1,1",
                            5000, narrowed=True, dates={"NOTICE_DATE": (lo.isoformat(), hi.isoformat())})
    if len(rows) >= 5000 and lo < hi:              # hit the cap: split the window
        mid = lo + (hi - lo) // 2
        return _forecast_rows(c, lo, mid, depth + 1) + _forecast_rows(c, mid + timedelta(days=1), hi, depth + 1)
    if len(rows) >= 5000:
        raise RuntimeError(f"forecast single day {lo} has >=5000 rows")
    return rows


def fetch_forecast(c, key: str) -> pd.DataFrame:
    y, m = map(int, key.split("-"))
    lo = date(y, m, 1)
    hi = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    rows = _forecast_rows(c, lo, min(hi, TODAY))
    out = [{"code": r["SECURITY_CODE"], "name": r.get("SECURITY_NAME_ABBR"),
            "notice_date": c._em_day(r.get("NOTICE_DATE")), "report_date": c._em_day(r.get("REPORT_DATE")),
            "indicator": r.get("PREDICT_FINANCE"), "forecast_type": r.get("PREDICT_TYPE"),
            "amount_lower": c._v39_num(r.get("PREDICT_AMT_LOWER")),
            "amount_upper": c._v39_num(r.get("PREDICT_AMT_UPPER")),
            "change_pct_lower": c._v39_num(r.get("ADD_AMP_LOWER")),
            "change_pct_upper": c._v39_num(r.get("ADD_AMP_UPPER")),
            "prior_year_amount": c._v39_num(r.get("PREYEAR_SAME_PERIOD")),
            "content": r.get("PREDICT_CONTENT"), "reason": r.get("CHANGE_REASON_EXPLAIN")} for r in rows]
    return pd.DataFrame(out)


def fetch_fin(c, dataset: str, key: str) -> pd.DataFrame:
    report, field, _ = FIN[dataset]
    rows = c._em_datacenter_strict(report, f"({field}='{key}')", "SECURITY_CODE", "1",
                                   page_size=500, max_rows=30000)
    return pd.DataFrame(rows)


def fetch_shares(c, key: str) -> pd.DataFrame:
    code = key.split(".")[-1]
    rows = c._em_datacenter_strict("RPT_F10_EH_EQUITY", f'(SECURITY_CODE="{code}")', "END_DATE", "-1",
                                   page_size=500, max_rows=5000)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- baostock worker (valuation)
def _bs_worker(conn):
    try:
        import baostock as bs
        login = bs.login()
        if login.error_code != "0":
            conn.send(("startup_error", login.error_msg)); return
        conn.send(("ready", None))
        while True:
            req = conn.recv()
            if req is None:
                break
            code, start, end = req
            try:
                r = bs.query_history_k_data_plus(code, VALUATION_FIELDS, start_date=start, end_date=end,
                                                 frequency="d", adjustflag="3")
                if r.error_code != "0":
                    raise RuntimeError(f"{r.error_code}: {r.error_msg}")
                rows = []
                while r.error_code == "0" and r.next():
                    rows.append(r.get_row_data())
                conn.send(("ok", {"fields": list(r.fields), "rows": rows}))
            except Exception as exc:
                conn.send(("error", f"{type(exc).__name__}: {exc}"))
    except EOFError:
        pass
    finally:
        try:
            bs.logout()
        except Exception:
            pass


class BsSession:
    def __init__(self, timeout=120.0):
        self.timeout, self.ctx, self.proc, self.conn = timeout, multiprocessing.get_context("spawn"), None, None
        self.start()

    def start(self):
        for attempt in range(3):
            parent, child = self.ctx.Pipe()
            self.proc = self.ctx.Process(target=_bs_worker, args=(child,), daemon=True)
            self.proc.start(); child.close(); self.conn = parent
            if parent.poll(60):
                status, detail = parent.recv()
                if status == "ready":
                    return
                self.kill(); raise RuntimeError(detail)
            self.kill()
            time.sleep((30, 90)[min(attempt, 1)])
        raise TimeoutError("baostock worker startup timed out")

    def kill(self):
        if self.conn is not None:
            self.conn.close(); self.conn = None
        if self.proc is not None:
            if self.proc.is_alive():
                self.proc.terminate(); self.proc.join(5)
                if self.proc.is_alive():
                    self.proc.kill(); self.proc.join(5)
            self.proc = None

    def query(self, code, start, end) -> pd.DataFrame:
        self.conn.send((code, start, end))
        if not self.conn.poll(self.timeout):
            self.kill(); self.start()
            raise TimeoutError(f"{code} exceeded {self.timeout}s")
        status, payload = self.conn.recv()
        if status != "ok":
            raise RuntimeError(payload)
        return pd.DataFrame(payload["rows"], columns=payload["fields"])

    def close(self):
        try:
            if self.conn is not None:
                self.conn.send(None)
        except Exception:
            pass
        self.kill()


# ---------------------------------------------------------------- apply
def apply_cmd(args):
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if args.approve != plan["sha256"]:
        raise PermissionError("approved sha does not match plan")
    dataset = plan["dataset"]
    start = date.fromisoformat(plan["start"]) if plan.get("start") else None
    parts = dict(partitions(dataset, start))
    todo = [k for k in plan["missing"] if k in parts and not parts[k].exists()]
    if args.shard:
        k, n = map(int, args.shard.split("/"))
        todo = todo[k::n]
    deadline = time.time() + args.max_seconds if args.max_seconds else None
    receipts = BRONZE / "_fundamentals_receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    done = failed = empty = 0
    errors: dict[str, str] = {}
    c = None if dataset == "valuation" else core()
    session = BsSession() if dataset == "valuation" else None
    consecutive = 0
    t0 = time.time()
    try:
        for i, key in enumerate(todo, 1):
            if deadline and time.time() > deadline:
                break
            try:
                if dataset == "pledge":
                    df = fetch_pledge(c, key)
                elif dataset == "forecast":
                    df = fetch_forecast(c, key)
                elif dataset in FIN:
                    df = fetch_fin(c, dataset, key)
                elif dataset == "shares":
                    df = fetch_shares(c, key)
                else:
                    df = session.query(key, "1990-12-19", TODAY.isoformat())
                    df["fetch_ts"] = datetime.now().astimezone().isoformat()
                if "_empty_reason" in df.columns:  # pledge: not a statistics date, nothing to store
                    empty += 1
                    write_parquet(df, parts[key].parent / "_empty" / parts[key].name)
                    continue
                if df.empty:
                    empty += 1
                    write_parquet(pd.DataFrame({"_empty_reason": ["no rows"]}), parts[key].parent / "_empty" / parts[key].name)
                    continue
                write_parquet(df if dataset == "valuation" else fetched(df), parts[key])
                done += 1; consecutive = 0
            except Exception as exc:
                failed += 1; consecutive += 1
                errors[key] = f"{type(exc).__name__}: {exc}"[:200]
                if consecutive >= 8:
                    print("HALT: 8 consecutive failures", flush=True)
                    break
            if i % 20 == 0:
                print(f"{i}/{len(todo)} done={done} empty={empty} failed={failed} {time.time()-t0:.0f}s", flush=True)
    finally:
        if session:
            session.close()
    out = {"dataset": dataset, "plan_sha": plan["sha256"], "todo": len(todo), "done": done, "empty": empty,
           "failed": failed, "errors": dict(list(errors.items())[:20]), "elapsed_s": round(time.time() - t0, 1)}
    (receipts / f"{dataset}-{plan['sha256'][:12]}-{int(time.time())}.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 1 if failed else 0


# ---------------------------------------------------------------- incremental update
def trading_days() -> list[date]:
    snaps = sorted((BRONZE / "provider=baostock" / "reference_snapshots").glob("snapshot=*/trade_calendar.parquet"))
    if not snaps:
        raise FileNotFoundError("no baostock trade_calendar snapshot")
    df = pd.read_parquet(snaps[-1])
    return sorted(date.fromisoformat(x) for x, f in zip(df["calendar_date"], df["is_trading_day"]) if str(f) == "1")


def weekly_last_trading_days(first: date, last: date) -> list[date]:
    """China Clear publishes the pledge statistics at the last trading day of each week
    (a Friday, except in holiday weeks, e.g. 2026-09-24 or 2026-09-30)."""
    out: dict[tuple, date] = {}
    for d in trading_days():
        if first <= d <= last:
            out[d.isocalendar()[:2]] = d
    return sorted(out.values())


def real_files(directory: Path, prefix: str) -> dict[str, Path]:
    return {p.name[len(prefix):-len(".parquet")]: p for p in directory.glob(f"{prefix}*.parquet")}


def write_real(df: pd.DataFrame, path: Path) -> None:
    write_parquet(df, path)
    marker = path.parent / "_empty" / path.name
    if marker.exists():
        marker.unlink()


def write_empty(path: Path, reason: str) -> None:
    write_parquet(pd.DataFrame({"_empty_reason": [reason]}), path.parent / "_empty" / path.name)


def update_pledge(c, through: date) -> dict:
    base = BRONZE / "provider=eastmoney" / "equity_pledge_history"
    have = real_files(base, "date=")
    first = PLEDGE_FIRST_FRIDAY          # weeks confirmed empty more than 21 days ago are skipped below
    done = empty = failed = 0
    errors = {}
    for d in weekly_last_trading_days(first, through):
        key = d.isoformat()
        if key in have:
            continue
        marker = base / "_empty" / f"date={key}.parquet"
        if marker.exists() and (through - d).days > 21:
            continue                     # confirmed empty long ago
        try:
            df = fetch_pledge(c, key)
            if "_empty_reason" in df.columns or df.empty:
                write_empty(base / f"date={key}.parquet", "not published yet / no rows")
                empty += 1
            else:
                write_real(fetched(df), base / f"date={key}.parquet")
                done += 1
        except Exception as exc:
            failed += 1; errors[key] = f"{type(exc).__name__}: {exc}"[:200]
    return {"done": done, "empty": empty, "failed": failed, "errors": errors}


def update_forecast(c, through: date) -> dict:
    base = BRONZE / "provider=eastmoney" / "earnings_forecast_history"
    this = date(through.year, through.month, 1)
    prev = date(this.year - (this.month == 1), 12 if this.month == 1 else this.month - 1, 1)
    todo = [m for m in months(FORECAST_FIRST_MONTH, through) if m >= prev or not (base / f"month={m:%Y-%m}.parquet").exists()
            and not (base / "_empty" / f"month={m:%Y-%m}.parquet").exists()]
    done = empty = failed = 0
    errors = {}
    for m in todo:
        key = m.strftime("%Y-%m")
        try:
            df = fetch_forecast(c, key)
            if df.empty:
                write_empty(base / f"month={key}.parquet", "no rows"); empty += 1
            else:
                write_real(fetched(df), base / f"month={key}.parquet"); done += 1
        except Exception as exc:
            failed += 1; errors[key] = f"{type(exc).__name__}: {exc}"[:200]
    return {"done": done, "empty": empty, "failed": failed, "errors": errors}


def update_fin(c, dataset: str, through: date) -> dict:
    base = BRONZE / "provider=eastmoney" / FIN[dataset][2]
    quarters = quarter_ends(FIN_FIRST_PERIOD, through)
    recent = set(quarters[-2:])          # the two latest periods keep getting disclosed / restated
    todo = [q for q in quarters if q in recent or not ((base / f"report_date={q}.parquet").exists()
                                                       or (base / "_empty" / f"report_date={q}.parquet").exists())]
    done = empty = failed = 0
    errors = {}
    for q in todo:
        key = q.isoformat()
        try:
            df = fetch_fin(c, dataset, key)
            if df.empty:
                if not (base / f"report_date={key}.parquet").exists():
                    write_empty(base / f"report_date={key}.parquet", "no rows")
                empty += 1
            else:
                write_real(fetched(df), base / f"report_date={key}.parquet"); done += 1
        except Exception as exc:
            failed += 1; errors[key] = f"{type(exc).__name__}: {exc}"[:200]
    return {"done": done, "empty": empty, "failed": failed, "errors": errors}


def update_shares(c, through: date) -> dict:
    base = BRONZE / "provider=eastmoney" / "share_capital"
    mark = base / "_watermark.json"
    if mark.exists():
        since = date.fromisoformat(json.loads(mark.read_text())["notice_date"]) - timedelta(days=7)
    else:
        since = through - timedelta(days=14)
    rows = c._em_datacenter_strict("RPT_F10_EH_EQUITY", f"(NOTICE_DATE>='{since}')", "NOTICE_DATE,SECURITY_CODE,END_DATE",
                                   "1,1,1", page_size=500, max_rows=50000)
    new = pd.DataFrame(rows)
    done = failed = 0
    errors = {}
    if not new.empty:
        stamp = datetime.now().astimezone().isoformat()
        for code, part in new.groupby("SECURITY_CODE"):
            path = base / f"{code}.parquet"
            try:
                part = part.assign(fetched_at=stamp)
                if path.exists():
                    old = pd.read_parquet(path)
                    merged = pd.concat([old, part], ignore_index=True)
                    keys = [k for k in ("END_DATE", "NOTICE_DATE", "CHANGE_REASON", "TOTAL_SHARES") if k in merged.columns]
                    merged = merged.drop_duplicates(subset=keys, keep="first")
                else:
                    merged = part
                merged = merged.sort_values("END_DATE", ascending=False, kind="stable")
                write_parquet(merged, path); done += 1
            except Exception as exc:
                failed += 1; errors[str(code)] = f"{type(exc).__name__}: {exc}"[:200]
    if not failed:
        mark.write_text(json.dumps({"notice_date": through.isoformat(), "updated": datetime.now().isoformat()}))
    return {"done": done, "rows": int(len(new)), "failed": failed, "errors": errors}


def update_valuation(through: date, shard: str | None) -> dict:
    base = BRONZE / "provider=baostock" / "valuation_daily_v1"
    codes = stock_codes()
    if shard:
        k, n = map(int, shard.split("/"))
        codes = codes[k::n]
    session = BsSession()
    done = skipped = failed = consecutive = 0
    errors = {}
    try:
        for code in codes:
            path = base / f"{code.replace('.', '_')}.parquet"
            old = None
            start = "1990-12-19"
            if path.exists():
                old = pd.read_parquet(path)
                last = old["date"].max()
                if last >= through.isoformat():
                    skipped += 1
                    continue
                start = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
            try:
                df = session.query(code, start, through.isoformat())
                df["fetch_ts"] = datetime.now().astimezone().isoformat()
                if old is not None:
                    df = pd.concat([old, df], ignore_index=True).drop_duplicates(subset=["date"], keep="first")
                if old is not None and len(df) == len(old):
                    skipped += 1       # no new trading day for this stock (suspended / delisted)
                    continue
                if df.empty:
                    skipped += 1
                    continue
                write_parquet(df, path)
                done += 1; consecutive = 0
            except Exception as exc:
                failed += 1; consecutive += 1
                errors[code] = f"{type(exc).__name__}: {exc}"[:200]
                if consecutive >= 8:
                    errors["_halt"] = "8 consecutive failures"
                    break
    finally:
        session.close()
    return {"done": done, "skipped": skipped, "failed": failed, "errors": dict(list(errors.items())[:20])}


def update_cmd(args):
    through = date.fromisoformat(args.through) if args.through else TODAY
    t0 = time.time()
    if args.dataset == "valuation":
        result = update_valuation(through, args.shard)
    else:
        c = core()
        if args.dataset == "pledge":
            result = update_pledge(c, through)
        elif args.dataset == "forecast":
            result = update_forecast(c, through)
        elif args.dataset in FIN:
            result = update_fin(c, args.dataset, through)
        elif args.dataset == "shares":
            result = update_shares(c, through)
        else:
            raise SystemExit(f"unknown dataset {args.dataset}")
    result.update(dataset=args.dataset, through=through.isoformat(), elapsed_s=round(time.time() - t0, 1))
    receipts = BRONZE / "_fundamentals_receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    suffix = (args.shard or "all").replace("/", "of")
    (receipts / f"update-{args.dataset}-{through}-{suffix}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if result.get("failed") else 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("plan"); a.add_argument("--dataset", required=True); a.add_argument("--start")
    b = sub.add_parser("apply"); b.add_argument("--plan", required=True); b.add_argument("--approve", required=True)
    b.add_argument("--max-seconds", type=float)
    b.add_argument("--shard", help="K/N: process every N-th missing partition starting at K")
    u = sub.add_parser("update"); u.add_argument("--dataset", required=True)
    u.add_argument("--through"); u.add_argument("--shard")
    args = p.parse_args()
    if args.cmd == "update":
        return update_cmd(args)
    if args.cmd == "plan":
        plan_cmd(args); return 0
    return apply_cmd(args)


if __name__ == "__main__":
    sys.exit(main())
