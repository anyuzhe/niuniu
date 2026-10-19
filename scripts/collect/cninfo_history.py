#!/usr/bin/env python3
"""巨潮历史公告目录回补（只要标题、时间和类别，不下载正文/PDF）。

子命令：
  delisted  退市股（取自 stock_kline_daily_delisted 的 290 个代码）按股票取 2010-01-01 至 --end 的全部公告
            -> provider=cninfo/announcements_history/scope=delisted/<code>.parquet
  keywords  全市场风险类公告：按标题关键词 × 年份取（巨潮在服务端按标题匹配），2010 年至 --end
            -> provider=cninfo/announcements_history/scope=keyword/<关键词>/year=YYYY.parquet（多一列 searchkey）
  days      全市场按公告日逐日回补，从 --end 往回走（新的先补）。单日超限先按板块拆；单个板块单日仍超限
            （年报/半年报高峰）再按证监会行业门类拆，门类仍超限再按巨潮公告分类拆，去重合并，
            与总数的差额记入回执 warnings（2026-10-18 起）
            -> provider=cninfo/announcements_history/date=YYYY-MM-DD.parquet
  status    统计已有文件、行数、日期范围

列：date, code, name, org_id, announcement_id, title, type, category_codes, announcement_time_ms,
    column_id, adjunct_url, fetched_at。`type` 巨潮常为空，真正的类别在 `category_codes`
    （形如 01010503||010113||01250710，分类码用 || 分隔）。
date 取巨潮公告日：逐日模式是查询日；退市模式由 announcement_time_ms 按北京时间换算。
较老的公告 announcement_time_ms 只有日期（北京时间 00:00:00），没有盘中时点。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(os.environ.get("NIUNIU_DATA_ROOT", "/Volumes/Lexar/niuniu-data"))
BRONZE = ROOT / "lake" / "bronze"
BASE = BRONZE / "provider=cninfo" / "announcements_history"
DELISTED_SRC = BRONZE / "provider=baostock" / "stock_kline_daily_delisted"
URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
TOP = "https://www.cninfo.com.cn/new/information/topSearch/query"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
HEADERS = {"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
           "Referer": "https://www.cninfo.com.cn/new/disclosure", "Origin": "https://www.cninfo.com.cn"}
CST = timezone(timedelta(hours=8))
COLUMNS = ["date", "code", "name", "org_id", "announcement_id", "title", "type", "category_codes",
           "announcement_time_ms", "column_id", "adjunct_url", "fetched_at"]
PAGE_CAP = 700
PACE = 0.3
DUP_RETRY_SLEEP = 15   # 整页重复（多为限流）时，退避后重取同一页；最多 2 次，再不行才算失败（2026-10-19 DATA）


def post(session, payload, url=URL):
    last = None
    for attempt in range(6):
        try:
            r = session.post(url, data=payload, headers=HEADERS, timeout=30)
            if r.status_code in (403, 429):   # 被限流：长退避，别继续冲击
                last = f"HTTP {r.status_code}"
                time.sleep(60 * (attempt + 1))
                continue
            if r.status_code in (502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, ValueError) as exc:
            last = repr(exc)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"巨潮请求失败：{last}")


MAX_ITEMS = 2970      # 巨潮单次查询最多翻 100 页（3000 条），第 101 页起重复第 100 页之后的内容
PLATES = ("szmb", "szcy", "shmb", "shkcp", "bj")   # 深主板、创业板、沪主板、科创板、北交所：互不重叠，合计等于全市场
# 高峰日（年报、半年报截止前后）单个板块单日仍超 3000 条时，先按证监会行业门类拆（互不重叠，合计等于总数，
# 2025-04-30 沪主板日常经营类实测 19 个门类合计 3706 = 总数）；某个门类仍超限（通常是制造业）再按巨潮公告分类拆。
# 分类之间可能重叠，也有不属于任何分类的公告，所以按 (announcement_id, code) 去重，合计可能略少于总数；
# 差额写进 WARNINGS 和回执，不当作失败（2026-10-18 DATA 新增）。
TRADES = ("农、林、牧、渔业", "采矿业", "制造业", "电力、热力、燃气及水生产和供应业", "建筑业", "批发和零售业",
          "交通运输、仓储和邮政业", "住宿和餐饮业", "信息传输、软件和信息技术服务业", "金融业", "房地产业",
          "租赁和商务服务业", "科学研究和技术服务业", "水利、环境和公共设施管理业", "居民服务、修理和其他服务业",
          "教育", "卫生和社会工作", "文化、体育和娱乐业", "综合")
CATEGORIES = ("category_ndbg_szsh", "category_bndbg_szsh", "category_yjdbg_szsh", "category_sjdbg_szsh",
              "category_yjygjxz_szsh", "category_qyfpxzcs_szsh", "category_dshgg_szsh", "category_jshgg_szsh",
              "category_gddh_szsh", "category_rcjy_szsh", "category_gszl_szsh", "category_zj_szsh",
              "category_sf_szsh", "category_zf_szsh", "category_gqjl_szsh", "category_pg_szsh", "category_jj_szsh",
              "category_gszq_szsh", "category_kzzq_szsh", "category_qtrz_szsh", "category_gqbd_szsh",
              "category_bcgz_szsh", "category_cqdq_szsh", "category_fxts_szsh", "category_tbclts_szsh",
              "category_tszlq_szsh")


def _payload(page, stock, se_date, searchkey="", plate="", category="", trade=""):
    return {"pageNum": str(page), "pageSize": "30", "column": "szse", "tabName": "fulltext", "plate": plate,
            "stock": stock, "searchkey": searchkey, "secid": "", "category": category, "trade": trade, "seDate": se_date,
            "sortName": "", "sortType": "", "isHLtitle": "false"}


def query_pages(session, stock="", se_date="", searchkey="", plate="", category="", allow_partial=False, trade=""):
    """取一个查询的全部条目；总数超过 MAX_ITEMS 时抛 TooBig，由调用方拆分。
    allow_partial=True 时不抛 TooBig / Incomplete：能翻多少翻多少（最多 100 页），由调用方记差额。"""
    first = post(session, _payload(1, stock, se_date, searchkey, plate, category, trade))
    total = first.get("totalAnnouncement")
    if total is None:
        raise RuntimeError(f"响应缺少总数，不能确认完整：{stock or se_date}")
    total = int(total)
    if total > MAX_ITEMS and not allow_partial:
        raise TooBig(total)
    items, seen, page, d, dup_retry = [], set(), 1, first, 0
    while True:
        got = d.get("announcements") or []
        fresh = 0
        for it in got:
            key = (it.get("announcementId"), it.get("secCode"))   # 联合公告同一个 id 会挂在多只股票下
            if key not in seen:
                seen.add(key)
                items.append(it)
                fresh += 1
        if got and not fresh:
            if dup_retry < 2:
                dup_retry += 1
                time.sleep(DUP_RETRY_SLEEP * dup_retry)
                d = post(session, _payload(page, stock, se_date, searchkey, plate, category, trade))
                continue
            if allow_partial:
                break
            raise RuntimeError(f"第 {page} 页全是重复条目（疑似被限流）：{stock or se_date}")
        if not d.get("hasMore") or not got:
            break
        page += 1
        if page > 100:
            if allow_partial:
                break
            raise RuntimeError(f"分页超过 100 页但总数 {total} 未超限：{stock or se_date}")
        time.sleep(PACE)
        d = post(session, _payload(page, stock, se_date, searchkey, plate, category, trade))
    if len(items) != total and not allow_partial:
        raise Incomplete(items, total)
    return items


def split_by_category(session, se_date, stock, searchkey, plate, total, trade="", notes=None):
    """（板块 × 行业门类）单日仍超限时按分类拆取，去重合并；超限的分类能翻多少翻多少，记入 notes。"""
    items, seen = [], set()
    notes = notes if notes is not None else []
    for cat in CATEGORIES:
        try:
            got = query_pages(session, stock=stock, se_date=se_date, searchkey=searchkey, plate=plate, category=cat, trade=trade)
        except TooBig as big:
            notes.append(f"{trade or '全行业'}/{cat} 超限 {big.args[0]}")
            got = query_pages(session, stock=stock, se_date=se_date, searchkey=searchkey, plate=plate, category=cat,
                              trade=trade, allow_partial=True)
        except Incomplete as inc:
            got = inc.args[0]
        for it in got:
            key = (it.get("announcementId"), it.get("secCode"))
            if key not in seen:
                seen.add(key)
                items.append(it)
        time.sleep(PACE)
    return items


def split_by_trade(session, se_date, stock, searchkey, plate, total):
    """单个板块单日超限时按行业门类拆（精确划分）；某门类仍超限再按分类拆。与总数的差额记入 WARNINGS。"""
    items, seen, notes = [], set(), []
    for tr in TRADES:
        try:
            got = query_pages(session, stock=stock, se_date=se_date, searchkey=searchkey, plate=plate, trade=tr)
        except TooBig as big:
            notes.append(f"{tr} 超限 {big.args[0]}，按分类拆")
            got = split_by_category(session, se_date, stock, searchkey, plate, big.args[0], trade=tr, notes=notes)
        except Incomplete as inc:
            got = inc.args[0]
        for it in got:
            key = (it.get("announcementId"), it.get("secCode"))
            if key not in seen:
                seen.add(key)
                items.append(it)
        time.sleep(PACE)
    if len(items) != total or notes:
        WARNINGS.append(f"{se_date} {plate}: 单日超限（{total} 条），按行业门类拆取 {len(items)} 条"
                        + (f"；{'; '.join(notes)}" if notes else ""))
    return items


class TooBig(Exception):
    pass


class Incomplete(Exception):
    """翻页拿到的条数与总数不符（巨潮按时间排序时同一时刻的条目翻页可能重复或漏掉）。"""


WARNINGS = []   # 单日仍对不上总数时接受已取到的条目，并在这里留痕


def fetch_range(session, start: date, end: date, stock="", searchkey="", plate=""):
    """取 [start, end] 的全部条目：超限先按日期对半拆，单日仍超限再按板块拆；拆开后合计必须等于总数。"""
    se = f"{start.isoformat()}~{end.isoformat()}"
    try:
        return query_pages(session, stock=stock, se_date=se, searchkey=searchkey, plate=plate)
    except TooBig as big:
        total = big.args[0]
    except Incomplete as inc:
        got, total = inc.args
        if start < end:   # 拆小再取，通常就对上了
            mid = start + (end - start) // 2
            return (fetch_range(session, start, mid, stock, searchkey, plate)
                    + fetch_range(session, mid + timedelta(days=1), end, stock, searchkey, plate))
        WARNINGS.append(f"{stock or searchkey or 'all'} {start}: 取到 {len(got)} 条，巨潮报 {total} 条")
        return got
    if start < end:
        mid = start + (end - start) // 2
        left = fetch_range(session, start, mid, stock, searchkey, plate)
        right = fetch_range(session, mid + timedelta(days=1), end, stock, searchkey, plate)
        return left + right
    if plate:
        return split_by_trade(session, se, stock, searchkey, plate, total)
    items, split = [], False
    for pl in PLATES:
        try:
            items += query_pages(session, stock=stock, se_date=se, searchkey=searchkey, plate=pl)
        except TooBig as big:
            split = True
            items += split_by_trade(session, se, stock, searchkey, pl, big.args[0])
        except Incomplete as inc:
            got, n = inc.args
            WARNINGS.append(f"{start} {pl}: 取到 {len(got)} 条，巨潮报 {n} 条")
            items += got
    if len(items) != total and not split:
        WARNINGS.append(f"{start} 按板块拆分后合计 {len(items)} ≠ 总数 {total}")
    return items


def to_frame(items, day=None):
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for it in items:
        ms = it.get("announcementTime")
        if day is not None:
            d = day
        elif ms is not None:
            d = datetime.fromtimestamp(int(ms) / 1000, CST).date()
        else:
            d = None
        rows.append({"date": d, "code": it.get("secCode"), "name": it.get("secName"), "org_id": it.get("orgId"),
                     "announcement_id": it.get("announcementId"), "title": it.get("announcementTitle"),
                     "type": it.get("announcementTypeName"), "category_codes": it.get("announcementType"),
                     "announcement_time_ms": ms, "column_id": it.get("columnId"),
                     "adjunct_url": it.get("adjunctUrl"), "fetched_at": now})
    return pd.DataFrame(rows, columns=COLUMNS)


def write_atomic(frame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def resolve_orgid(session, code, cache):
    if code in cache:
        return cache[code]
    d = post(session, {"keyWord": code, "maxNum": "10"}, url=TOP)
    hits = [x for x in d if x.get("code") == code and x.get("category") == "A股"] if isinstance(d, list) else []
    delisted = [x for x in hits if str(x.get("delisted")).lower() == "true"]
    pick = (delisted or hits or [None])[0]
    cache[code] = pick.get("orgId") if pick else None
    return cache[code]


def cmd_delisted(args):
    started = time.time()
    codes = sorted(p.stem.split("_", 1)[1] for p in DELISTED_SRC.glob("*.parquet"))
    out_dir = BASE / "scope=delisted"
    cache_path = BASE / "_orgids.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    session = requests.Session()
    done = skipped = 0
    failed, missing = [], []
    for code in codes:
        if time.time() - started > args.max_seconds:
            log("达到时间上限，停止")
            break
        path = out_dir / f"{code}.parquet"
        if path.exists() and not args.refresh:
            skipped += 1
            continue
        try:
            org = resolve_orgid(session, code, cache)
            if not org:
                missing.append(code)
                continue
            items = fetch_range(session, date.fromisoformat(args.start), date.fromisoformat(args.end), stock=f"{code},{org}")
            items = [x for x in items if x.get("secCode") == code]
            write_atomic(to_frame(items), path)
            done += 1
            log(f"{code} {len(items)} 条")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{code}: {exc}")
            log(f"{code} 失败 {exc}")
        time.sleep(PACE)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=0))
    print(json.dumps({"codes": len(codes), "done": done, "skipped": skipped, "no_orgid": missing,
                      "failed": failed, "elapsed_s": round(time.time() - started)}, ensure_ascii=False))
    return 1 if failed else 0


def fetch_day(day: date):
    session = requests.Session()
    items = fetch_range(session, day, day)
    frame = to_frame(items, day=day)
    write_atomic(frame, BASE / f"date={day.isoformat()}.parquet")
    return day, len(frame)


def cmd_days(args):
    started = time.time()
    end, start = date.fromisoformat(args.end), date.fromisoformat(args.start)
    todo, d = [], end
    while d >= start:
        if args.refresh or not (BASE / f"date={d.isoformat()}.parquet").exists():
            todo.append(d)
        d -= timedelta(days=1)
    log(f"待补 {len(todo)} 天，线程 {args.workers}")
    done = rows = 0
    failed = []
    it = iter(todo)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {}
        def submit_next():
            if time.time() - started > args.max_seconds:
                return False
            try:
                day = next(it)
            except StopIteration:
                return False
            pending[pool.submit(fetch_day, day)] = day
            return True
        for _ in range(args.workers):
            submit_next()
        while pending:
            for fut in as_completed(list(pending)):
                day = pending.pop(fut)
                try:
                    _, n = fut.result()
                    done += 1
                    rows += n
                    if done % 20 == 0:
                        log(f"{day} 已完成 {done}/{len(todo)}，累计 {rows} 行")
                except Exception as exc:  # noqa: BLE001
                    failed.append(f"{day}: {exc}")
                    log(f"{day} 失败 {exc}")
                submit_next()
                break
    summary = {"mode": "days", "start": args.start, "end": args.end, "requested": len(todo), "done": done, "rows": rows,
               "failed": failed, "warnings": WARNINGS, "elapsed_s": round(time.time() - started),
               "finished_at": datetime.now(CST).isoformat()}
    rdir = BASE / "_receipts"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / f"days_{args.start}_{args.end}_{datetime.now(CST).strftime('%Y%m%dT%H%M%S')}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if failed else 0


KEYWORDS = ("立案", "调查通知", "风险警示", "退市", "终止上市", "暂停上市", "保留意见", "否定意见", "无法表示意见",
            "问询函", "关注函", "监管函", "警示函", "诉讼", "仲裁", "处罚决定")


def cmd_keywords(args):
    started = time.time()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    session = requests.Session()
    done = skipped = rows = 0
    failed = []
    for kw in (args.keyword or KEYWORDS):
        for year in range(start.year, end.year + 1):
            if time.time() - started > args.max_seconds:
                log("达到时间上限，停止")
                print(json.dumps({"done": done, "skipped": skipped, "rows": rows, "failed": failed,
                                  "stopped": "max-seconds", "elapsed_s": round(time.time() - started)}, ensure_ascii=False))
                return 1 if failed else 0
            path = BASE / "scope=keyword" / kw / f"year={year}.parquet"
            if path.exists() and not args.refresh:
                skipped += 1
                continue
            lo, hi = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            try:
                items = fetch_range(session, lo, hi, searchkey=kw)
                frame = to_frame(items)
                frame.insert(1, "searchkey", kw)
                write_atomic(frame, path)
                done += 1
                rows += len(frame)
                log(f"{kw} {year} {len(frame)} 条")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{kw} {year}: {exc}")
                log(f"{kw} {year} 失败 {exc}")
            time.sleep(PACE)
    print(json.dumps({"done": done, "skipped": skipped, "rows": rows, "failed": failed, "warnings": WARNINGS,
                      "elapsed_s": round(time.time() - started)}, ensure_ascii=False))
    return 1 if failed else 0


def cmd_status(args):
    import duckdb
    out = {}
    days = sorted(BASE.glob("date=*.parquet"))
    if days:
        r = duckdb.sql(f"select count(*), count(distinct announcement_id), min(date), max(date) from read_parquet('{BASE}/date=*.parquet')").fetchone()
        out["days"] = {"files": len(days), "rows": r[0], "distinct_ids": r[1], "min": str(r[2]), "max": str(r[3])}
    dl = sorted((BASE / "scope=delisted").glob("*.parquet"))
    if dl:
        r = duckdb.sql(f"select count(*), count(distinct announcement_id), min(date), max(date) from read_parquet('{BASE}/scope=delisted/*.parquet')").fetchone()
        out["delisted"] = {"files": len(dl), "rows": r[0], "distinct_ids": r[1], "min": str(r[2]), "max": str(r[3])}
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main():
    global PACE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("delisted", "days", "keywords"):
        p = sub.add_parser(name)
        p.add_argument("--start", default="2010-01-01")
        p.add_argument("--end", default="2026-09-16")
        p.add_argument("--max-seconds", type=int, default=3000)
        p.add_argument("--refresh", action="store_true")
        p.add_argument("--pace", type=float, default=PACE, help="两次请求之间的间隔秒数（默认 %(default)s；被限流时调大）")
        if name == "days":
            p.add_argument("--workers", type=int, default=2)
        if name == "keywords":
            p.add_argument("--keyword", action="append")
    sub.add_parser("status")
    args = ap.parse_args()
    if getattr(args, "pace", None) is not None:
        PACE = args.pace
    return {"delisted": cmd_delisted, "days": cmd_days, "keywords": cmd_keywords, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
