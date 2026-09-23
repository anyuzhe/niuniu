"""Collect public A-share datasets found in a-stock-data into bronze partitions.

Each dataset is a named fetcher (mostly the vendored, validated a-stock-data
functions) plus a partition rule:

* ``date``     one file per trading or calendar day; history can be back-filled
* ``snapshot`` one file per observation day; the source only serves "now"

Same contract as the other collectors: ``plan`` is read-only and prints a plan
SHA; ``apply`` needs ``--approve-sha256`` of that exact plan, writes atomically,
records a per-partition receipt, is resumable and stops before ``--max-seconds``.
A source returning nothing is written as an explicit ``_empty/<partition>.json``
marker; a fetch error is recorded as ``failed`` and never becomes an empty file.

Eastmoney requests all go through the vendored ``em_get`` serial throttle
(>=1.5 s here); other sources sleep ``--throttle`` between partitions.  Nothing is
parallel.  Output: ``<data-root>/lake/bronze/provider=<p>/<dataset>/<partition>.parquet``.

    python scripts/collect/public_sources.py plan --dataset ths_limit_up --start 2026-09-01 --end 2026-09-23 --out plan.json
    python scripts/collect/public_sources.py apply --plan plan.json --approve-sha256 <sha>
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import paths  # noqa: E402

PLAN_FORMAT = "niuniu-public-sources-plan-v1"
HERE = Path(__file__).resolve().parent
CERT = HERE / "certs" / "geotrust_g2_tls_cn_rsa4096_sha256_2022_ca1.pem"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CSI_INDICES = ("000300", "000905", "000852", "000016", "000688", "000510", "932000")
CNI_INDICES = ("399006",)


def core():
    from collect.vendor.a_stock_data import core as c
    c.EM_MIN_INTERVAL = max(getattr(c, "EM_MIN_INTERVAL", 1.0), 1.5)
    return c


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical(body) -> bytes:
    return (json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1, default=str) + "\n").encode()


# ------------------------------------------------------------------ fetchers
def _frame(rows):
    import pandas as pd
    return rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)


def fetch_sw_industry_history(day: date):
    """申万行业归属变迁史（官方 xls，全历史一次下载）。站点缺中间证书，用仓库内固定的中间证书补齐。"""
    import certifi
    import pandas as pd
    import requests
    import tempfile
    bundle = Path(tempfile.gettempdir()) / "niuniu-swsresearch-ca-bundle.pem"
    bundle.write_bytes(Path(certifi.where()).read_bytes() + b"\n" + CERT.read_bytes())
    url = core().SW_URL
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://www.swsresearch.com/"},
                     timeout=90, verify=str(bundle))
    r.raise_for_status()
    raw = r.content
    df = pd.read_excel(io.BytesIO(raw))
    df = df.rename(columns={"股票代码": "code", "计入日期": "start_date", "行业代码": "industry_code",
                            "更新日期": "update_date"})
    missing = {"code", "start_date", "industry_code"} - set(df.columns)
    if missing:
        raise RuntimeError(f"申万表结构变化，缺列 {sorted(missing)}")
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["industry_code"] = df["industry_code"].astype(str).str.zfill(6)
    df["l1_code"] = df["industry_code"].str[:2] + "0000"
    df["l2_code"] = df["industry_code"].str[:4] + "00"
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce").dt.date
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(lambda v: None if v is None else str(v))
    return df, {"source_url": url, "raw_bytes": raw, "raw_ext": "xls"}


def fetch_ths_limit_up(day: date):
    """同花顺涨停揭秘：涨停原因题材、板型、封板成功率、炸板次数、封单额。"""
    import requests
    url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
    rows, page, total = [], 1, None
    while True:
        params = {"page": page, "limit": 200,
                  "field": "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
                  "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": "0",
                  "date": day.strftime("%Y%m%d")}
        r = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": "https://data.10jqka.com.cn/"},
                         timeout=20)
        r.raise_for_status()
        payload = r.json()
        if payload.get("status_code") not in (0, None):
            raise RuntimeError(f"同花顺返回错误 {payload.get('status_code')} {payload.get('status_msg')}")
        data = payload.get("data") or {}
        info = data.get("info") or []
        pg = data.get("page") or {}
        total = pg.get("total", total)
        for it in info:
            ft = it.get("first_limit_up_time")
            lt = it.get("last_limit_up_time")
            rows.append({"date": day, "code": it.get("code"), "name": it.get("name"),
                         "price": it.get("latest"), "pct": it.get("change_rate"),
                         "reason": it.get("reason_type"), "board_type": it.get("limit_up_type"),
                         "seal_rate": it.get("limit_up_suc_rate"), "break_times": it.get("open_num"),
                         "seal_amount": it.get("order_amount"), "high_days": it.get("high_days"),
                         "first_limit_up_ts": int(ft) if ft else None, "last_limit_up_ts": int(lt) if lt else None,
                         "is_again": it.get("is_again_limit"), "raw_json": json.dumps(it, ensure_ascii=False)})
        pages = pg.get("page_count") or pg.get("pages")
        if not info or (pages and page >= int(pages)) or (total is not None and len(rows) >= int(total)):
            break
        page += 1
        time.sleep(1.0)
    if total is not None and int(total) != len(rows):
        raise RuntimeError(f"同花顺涨停池分页不完整：{len(rows)}/{total}")
    return _frame(rows), {"source_url": url, "source_total": total}


def fetch_em_monitor(day: date):
    rows = core().em_stock_monitor(only_active=False)
    for r in rows:
        r["observed_date"] = day
    return _frame(rows), {"source_url": core().MONITOR_URL}


def fetch_em_anomaly(day: date):
    c = core()
    rows, page = [], 1
    while True:
        res = c.em_price_anomaly(page_size=200, page_no=page)
        items = res.get("items") or res.get("data") or res.get("list") or []
        rows.extend(items)
        total = res.get("total")
        if len(items) < 200 or (total is not None and len(rows) >= int(total)):
            break
        page += 1
    for r in rows:
        r["observed_date"] = day
    return _frame(rows), {"source_url": c.ANOMALY_BASE}


def fetch_index_weights(day: date):
    import pandas as pd
    c = core()
    frames = []
    for code in CSI_INDICES:
        frames.append(c.index_weights(code, "csi"))
        time.sleep(1.0)
    for code in CNI_INDICES:
        frames.append(c.index_weights(code, "cni"))
        time.sleep(1.0)
    df = pd.concat(frames, ignore_index=True)
    df["observed_date"] = day
    return df, {"source_url": "csindex.com.cn / cnindex.com.cn", "indices": list(CSI_INDICES + CNI_INDICES)}


def _margin_sse(day: date):
    """上交所两融明细。上游一次取 5000 条，但上交所现在每页最多返回 2000 条，这里按页取全并核对总数。"""
    c = core()
    url = "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
    data, page, total = [], 1, None
    while True:
        response = c._official_get(url, {
            "isPagination": "true", "tabType": "mxtype", "detailsDate": day.strftime("%Y%m%d"),
            "pageHelp.pageSize": 1000, "pageHelp.pageNo": page, "pageHelp.beginPage": page,
            "pageHelp.cacheSize": 1, "pageHelp.endPage": page}, "https://www.sse.com.cn/")
        helper = response.json().get("pageHelp") or {}
        chunk = helper.get("data") or []
        total = c._official_total(helper.get("total")) if total is None else total
        data.extend(chunk)
        if not chunk or len(data) >= total:
            break
        page += 1
        time.sleep(1.0)
    if not data or len(data) != total:
        raise RuntimeError(f"上交所两融 {day} 未发布或分页不完整：{len(data)}/{total}")
    fields = {"rzye": "margin_balance", "rzmre": "margin_buy", "rqylje": "short_balance",
              "rqyl": "short_volume", "rqmcl": "short_sell_volume"}
    rows = []
    for rec in data:
        if c._official_date(rec.get("opDate")) != day.isoformat():
            raise RuntimeError("上交所两融数据日期不符")
        rows.append({"date": day.isoformat(), "code": c._official_margin_code(rec["stockCode"], "SH"),
                     "name": rec.get("securityAbbr"), "exchange": "SH",
                     **{dest: c._official_number(rec[src], required=(src != "rqylje")) for src, dest in fields.items()}})
    frame = c._official_frame(rows, ["date", "code"], "sse", url)
    if frame["code"].duplicated().any():
        raise RuntimeError("上交所两融分页出现重复证券")
    return frame


def fetch_margin_official(day: date):
    import pandas as pd
    c = core()
    frames = [_margin_sse(day)]
    time.sleep(1.0)
    frames.append(c.margin_trading_backup(day.isoformat(), "SZ"))
    return pd.concat(frames, ignore_index=True), {"source_url": "query.sse.com.cn / szse.cn"}


def _em_by_day(report, field, day, sort, value_fmt="'{d}'"):
    c = core()
    filt = f"({field}={value_fmt.format(d=day.isoformat())})"
    rows = c._em_datacenter_strict(report, filt, sort[0], sort[1], page_size=500, max_rows=20000)
    for r in rows:
        if str(r.get(field) or "")[:10] != day.isoformat():
            raise RuntimeError(f"东财 {report} 请求 {field}={day}，返回了 {r.get(field)}")
    return _frame(rows), {"source_url": c.DATACENTER_URL + "?reportName=" + report}


def fetch_block_trades(day: date):
    return _em_by_day("RPT_DATA_BLOCKTRADE", "TRADE_DATE", day,
                      ("SECURITY_CODE,DEAL_PRICE,DEAL_VOLUME,BUYER_CODE,SELLER_CODE", "1,1,1,1,1"))


def fetch_lockup_expiry(day: date):
    return _em_by_day("RPT_LIFT_STAGE", "FREE_DATE", day, ("SECURITY_CODE,FREE_SHARES_TYPE", "1,1"))


def fetch_holder_count_latest(day: date):
    c = core()
    rows = c._em_datacenter_strict("RPT_HOLDERNUMLATEST", "", "SECURITY_CODE", "1",
                                   page_size=500, max_rows=20000)
    if not rows:
        raise RuntimeError("东财股东户数全市场返回 0 行")
    df = _frame(rows)
    df["observed_date"] = day
    return df, {"source_url": c.DATACENTER_URL + "?reportName=RPT_HOLDERNUMLATEST"}


def fetch_northbound_minute(day: date):
    df = core().hsgt_realtime()
    df["date"] = day
    return df, {"source_url": "https://data.hexin.cn/market/hsgtApi/method/dayChart/"}


def _event(fn, **kwargs):
    df = fn(**kwargs)
    return df, {"source": "eastmoney datacenter", **{k: str(v) for k, v in kwargs.items()}}


EARNINGS_REPORT_DATES = ("2026-06-30", "2026-09-30")


def fetch_earnings_forecast(day: date):
    """业绩预告按报告期分别取（全表超过上游 5000 条上限，不分期会被截断）。"""
    import pandas as pd
    frames = []
    for rd in EARNINGS_REPORT_DATES:
        df = core().earnings_forecast(report_date=rd, limit=5000)
        if len(df) >= 5000:
            raise RuntimeError(f"业绩预告 {rd} 达到 5000 条上限，结果可能被截断")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["observed_date"] = day
    return df, {"source": "eastmoney datacenter", "report_dates": list(EARNINGS_REPORT_DATES)}


def fetch_institution_survey(day: date):
    return _event(core().institution_survey, start=day.isoformat(), end=day.isoformat(), detail=True, limit=5000)


def fetch_holder_trades(day: date):
    return _event(core().holder_trades, start=day.isoformat(), end=day.isoformat(), limit=5000)


def fetch_share_buyback(day: date):
    """回购：上游单次最多 5000 条（按公告日倒序），全表更长；这里明确记录是“最近 5000 条”。"""
    df, meta = _event(core().share_buyback, limit=5000)
    df["observed_date"] = day
    meta["truncated_to_latest"] = len(df) >= 5000
    return df, meta


def fetch_equity_pledge(day: date):
    df, meta = _event(core().equity_pledge, limit=5000)
    df["observed_date"] = day
    return df, meta


def fetch_ipo_calendar(day: date):
    df, meta = _event(core().ipo_calendar, limit=5000)
    meta["truncated_to_latest"] = len(df) >= 5000
    df["observed_date"] = day
    return df, meta


def fetch_cninfo_announcements(day: date):
    """巨潮全市场公告：按公告日期逐页取全，保留 announcementTime（毫秒时间戳）作为发布时点证据。"""
    import requests
    url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    headers = {"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
               "Referer": "https://www.cninfo.com.cn/new/disclosure", "Origin": "https://www.cninfo.com.cn"}
    session = requests.Session()
    rows, total, seen = [], None, set()
    # 实测 column 参数不过滤市场：szse/sse 返回同一份全市场结果，所以只取一遍并核对总数
    for column in ("szse",):
        page = 1
        while True:
            payload = {"pageNum": str(page), "pageSize": "30", "column": column, "tabName": "fulltext",
                       "plate": "", "stock": "", "searchkey": "", "secid": "", "category": "", "trade": "",
                       "seDate": f"{day.isoformat()}~{day.isoformat()}", "sortName": "", "sortType": "",
                       "isHLtitle": "false"}
            for attempt in range(4):   # 巨潮偶发 502，同页有限重试
                r = session.post(url, data=payload, headers=headers, timeout=30)
                if r.status_code not in (502, 503, 504):
                    break
                time.sleep(3 * (attempt + 1))
            r.raise_for_status()
            d = r.json()
            items = d.get("announcements") or []
            total = d.get("totalAnnouncement", total)
            for it in items:
                key = it.get("announcementId")
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"date": day, "column": column, "code": it.get("secCode"), "name": it.get("secName"),
                             "org_id": it.get("orgId"), "announcement_id": key,
                             "title": it.get("announcementTitle"), "type": it.get("announcementTypeName"),
                             "announcement_time_ms": it.get("announcementTime"),
                             "adjunct_url": it.get("adjunctUrl"), "adjunct_type": it.get("adjunctType"),
                             "raw_json": json.dumps(it, ensure_ascii=False)})
            if not d.get("hasMore") or not items:
                break
            page += 1
            if page > 400:
                raise RuntimeError("巨潮单日分页超过 400 页，停止以免无界请求")
            time.sleep(0.6)
        time.sleep(1.0)
    if total is not None and len(rows) != int(total):
        raise RuntimeError(f"巨潮 {day} 公告分页不完整：{len(rows)}/{total}")
    return _frame(rows), {"source_url": url, "source_total": total}


DATASETS = {
    # name: (provider, dataset dir, partition kind, fetcher, calendar: trading|calendar|today)
    "sw_industry_history": ("swsresearch", "industry_classification_history", "snapshot", fetch_sw_industry_history),
    "cninfo_announcements": ("cninfo", "announcements", "date_calendar", fetch_cninfo_announcements),
    "ths_limit_up": ("ths", "limit_up_pool", "date", fetch_ths_limit_up),
    "em_monitor": ("eastmoney", "monitor_pool", "snapshot", fetch_em_monitor),
    "em_anomaly": ("eastmoney", "price_anomaly_pool", "snapshot", fetch_em_anomaly),
    "index_weights": ("csindex", "index_weights", "snapshot", fetch_index_weights),
    "margin_official": ("exchange", "margin_trading", "date", fetch_margin_official),
    "block_trades": ("eastmoney", "block_trades", "date", fetch_block_trades),
    "lockup_expiry": ("eastmoney", "lockup_expiry", "date_calendar", fetch_lockup_expiry),
    "holder_count": ("eastmoney", "holder_count_latest", "snapshot", fetch_holder_count_latest),
    "northbound_minute": ("ths", "northbound_minute", "snapshot", fetch_northbound_minute),
    "earnings_forecast": ("eastmoney", "earnings_forecast", "snapshot", fetch_earnings_forecast),
    "institution_survey": ("eastmoney", "institution_survey", "date_calendar", fetch_institution_survey),
    "holder_trades": ("eastmoney", "holder_trades", "date_calendar", fetch_holder_trades),
    "share_buyback": ("eastmoney", "share_buyback", "snapshot", fetch_share_buyback),
    "equity_pledge": ("eastmoney", "equity_pledge", "snapshot", fetch_equity_pledge),
    "ipo_calendar": ("eastmoney", "ipo_calendar", "snapshot", fetch_ipo_calendar),
}


# ------------------------------------------------------------------ plan / apply
def trading_days(data_root: Path, start: date, end: date, snapshot: str) -> list[date]:
    import pandas as pd
    cal = pd.read_parquet(data_root / "lake/bronze/provider=baostock/reference_snapshots"
                          / f"snapshot={snapshot}" / "trade_calendar.parquet")
    mask = cal["is_trading_day"].astype(str).isin({"1", "1.0", "True", "true"})
    days = sorted({date.fromisoformat(str(v)[:10]) for v in cal.loc[mask, "calendar_date"]})
    return [d for d in days if start <= d <= end]


def dataset_dir(data_root: Path, name: str) -> Path:
    provider, directory, _kind, _fn = DATASETS[name]
    return data_root / "lake" / "bronze" / f"provider={provider}" / directory


def code_sha() -> str:
    h = hashlib.sha256(Path(__file__).read_bytes())
    h.update((HERE / "vendor" / "a_stock_data" / "core.py").read_bytes())
    return h.hexdigest()


def build_plan(data_root: Path, name: str, start: date | None, end: date | None, snapshot: str,
               today: date) -> dict:
    if name not in DATASETS:
        raise ValueError(f"unknown dataset {name}; choose from {sorted(DATASETS)}")
    kind = DATASETS[name][2]
    if kind == "snapshot":
        parts = [today]
    elif kind == "date":
        parts = trading_days(data_root, start, end, snapshot)
    else:
        parts = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    target = dataset_dir(data_root, name)
    existing = {p.stem for p in target.glob("*.parquet")} | {p.stem for p in (target / "_empty").glob("*.json")}
    body = {"format": PLAN_FORMAT, "dataset": name, "kind": kind, "target": str(target),
            "data_root": str(data_root), "code_sha256": code_sha(),
            "partitions": [d.isoformat() for d in parts if d.isoformat() not in existing],
            "already_present": sorted(existing & {d.isoformat() for d in parts})}
    body["plan_sha256"] = sha256_bytes(canonical(body))
    return body


def _check(plan: dict, approve: str) -> None:
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    if plan.get("format") != PLAN_FORMAT or sha256_bytes(canonical(body)) != plan.get("plan_sha256"):
        raise PermissionError("plan content does not match plan_sha256")
    if approve != plan["plan_sha256"]:
        raise PermissionError("approval SHA does not match the plan")
    if code_sha() != plan["code_sha256"]:
        raise PermissionError("collector code changed since plan; re-plan")


def _atomic(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return sha256_bytes(data)


def _to_parquet_bytes(df) -> bytes:
    buf = io.BytesIO()
    for col in df.columns:
        if df[col].dtype == object:
            kinds = {type(v).__name__ for v in df[col].dropna().head(2000)}
            if len(kinds) > 1 or kinds - {"str", "date", "datetime", "Timestamp"}:
                df[col] = df[col].map(lambda v: None if v is None else (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)))
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def apply(plan: dict, approve: str, *, max_seconds: float, throttle: float) -> dict:
    _check(plan, approve)
    fetch = DATASETS[plan["dataset"]][3]
    target = Path(plan["target"])
    receipt_path = target / "_receipts" / f"public-{plan['dataset']}-{plan['plan_sha256'][:16]}.json"
    receipt = (json.loads(receipt_path.read_text()) if receipt_path.is_file()
               else {"plan_sha256": plan["plan_sha256"], "dataset": plan["dataset"], "results": {}})
    start = time.monotonic()
    for part in plan["partitions"]:
        if part in receipt["results"] and receipt["results"][part]["status"] in ("ok", "empty"):
            continue
        if time.monotonic() - start > max_seconds:
            break
        observed_at = datetime.now(timezone.utc).isoformat()
        try:
            df, meta = fetch(date.fromisoformat(part))
            raw = meta.pop("raw_bytes", None)
            entry = {"observed_at": observed_at, "meta": meta}
            if raw is not None:
                entry["raw_sha256"] = _atomic(target / "_raw" / f"{part}.{meta.pop('raw_ext', 'bin')}", raw)
            if len(df) == 0:
                marker = canonical({"dataset": plan["dataset"], "partition": part, "observed_at": observed_at,
                                    "meta": meta, "reason": "source returned zero rows"})
                entry.update(status="empty", marker_sha256=_atomic(target / "_empty" / f"{part}.json", marker))
            else:
                df = df.copy()
                df["_observed_at"] = observed_at
                entry.update(status="ok", rows=int(len(df)), columns=list(map(str, df.columns)),
                             sha256=_atomic(target / f"{part}.parquet", _to_parquet_bytes(df)))
        except Exception as exc:  # recorded, never written as data
            entry = {"observed_at": observed_at, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:500]}
        receipt["results"][part] = entry
        _atomic(receipt_path, canonical(receipt))
        time.sleep(throttle)
    counts = {}
    for e in receipt["results"].values():
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    receipt["complete"] = all(p in receipt["results"] and receipt["results"][p]["status"] in ("ok", "empty")
                              for p in plan["partitions"])
    _atomic(receipt_path, canonical(receipt))
    return {"dataset": plan["dataset"], "partitions": len(plan["partitions"]), **counts,
            "complete": receipt["complete"], "receipt": str(receipt_path)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=str(paths.DATA_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat)
    p.add_argument("--today", type=date.fromisoformat, default=None, help="snapshot 分区的观察日（默认北京时间今天）")
    p.add_argument("--calendar-snapshot", default="2026-09-23", help="交易日历使用的参考快照日期")
    p.add_argument("--out", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--plan", required=True)
    a.add_argument("--approve-sha256", required=True)
    a.add_argument("--max-seconds", type=float, default=1e9)
    a.add_argument("--throttle", type=float, default=1.0)
    sub.add_parser("list")
    args = parser.parse_args(argv)
    if args.command == "list":
        for name, (provider, directory, kind, _f) in sorted(DATASETS.items()):
            print(f"{name:22s} {kind:14s} provider={provider}/{directory}")
        return 0
    if args.command == "plan":
        today = args.today or (datetime.now(timezone.utc) + timedelta(hours=8)).date()
        kind = DATASETS[args.dataset][2]
        if kind != "snapshot" and not (args.start and args.end):
            parser.error("--start/--end required for date datasets")
        plan = build_plan(Path(args.data_root), args.dataset, args.start, args.end, args.calendar_snapshot, today)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_bytes(canonical(plan))
        print(json.dumps({"plan": args.out, "dataset": args.dataset, "partitions": len(plan["partitions"]),
                          "already_present": len(plan["already_present"]), "plan_sha256": plan["plan_sha256"]}))
        return 0
    plan = json.loads(Path(args.plan).read_text())
    result = apply(plan, args.approve_sha256, max_seconds=args.max_seconds, throttle=args.throttle)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
