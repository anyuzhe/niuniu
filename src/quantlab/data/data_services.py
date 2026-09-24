"""DATA services for the data-centre page: status, preview / trial query, update jobs.

Three classes, all built with ``data_root`` (default ``NIUNIU_DATA_ROOT`` or
``/Volumes/Lexar/niuniu-data``); every return value is a JSON-serialisable dict with
Beijing-time ISO timestamps; errors are ``InvalidRequest`` (bad arguments) or
``DataProviderError`` (everything else) with Chinese messages.

* ``DataStatusService.list_status()``  reads only the status index
  (``catalog/dataset_status.json``, rebuilt at the end of every update job), seal
  manifests and today's recorder receipts -- no data-file scan.
* ``DataPreviewService``  ``preview`` for READY files, ``query_schema`` / ``query`` for
  READY query APIs.
* ``DataUpdateJobs``  ``list_jobs / plan / run / status / log / cancel / list_runs``.
  ``run`` starts ``scripts/collect/job_runner.py`` as a detached process; runs live in
  ``catalog/jobs/runs/<run_id>/`` so they survive closing niuniu.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.data import day_seals
from quantlab.data.research_provider import DataProviderError, InvalidRequest

TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_DATA_ROOT = "/Volumes/Lexar/niuniu-data"
REPO = Path(__file__).resolve().parents[3]
STATUS_INDEX = "catalog/dataset_status.json"
JOBS = "catalog/jobs"
PLAN_TTL = timedelta(minutes=30)


def _root(data_root) -> Path:
    return Path(data_root or os.environ.get("NIUNIU_DATA_ROOT") or DEFAULT_DATA_ROOT)


def _now() -> datetime:
    return datetime.now(TZ).replace(microsecond=0)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, TZ).replace(microsecond=0).isoformat()
    return str(value)


def _jsonable(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        try:
            if getattr(value, "tzinfo", None) is not None:
                return value.astimezone(TZ).isoformat()
        except (TypeError, ValueError):
            pass
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


# ================================================================== dataset layout (DATA-owned)
# dataset_id -> (dir relative to data root, layout, cadence)
#   layout: per_symbol | partition | day_dir | day_file | snapshot | api
#   cadence: close (trading day, after 18:00) | intraday (trading day, after 09:30)
#            t_plus_1 (previous trading day) | next_day (previous calendar day) | none
LAYOUT = {
    "bars_daily_baostock_raw": ("lake/bronze/provider=baostock/stock_kline_daily", "per_symbol", "close"),
    "bars_min5_baostock_raw": ("lake/bronze/provider=baostock/stock_kline_min5", "per_symbol", "close"),
    "security_status_baostock_v2": ("lake/bronze/provider=baostock/daily_status_v2", "per_symbol", "close"),
    "qfq_published_f24": ("lake/silver/qfq_kline_daily_v2", "per_symbol", "close"),
    "reference_snapshot_baostock": ("lake/bronze/provider=baostock/reference_snapshots", "snapshot", "close"),
    "sector_board_intraday": ("lake/bronze/provider=fuyao/sector_board_intraday", "day_dir", "intraday"),
    "stock_intraday_snapshot": ("lake/bronze/provider=fuyao/stock_intraday_snapshot", "day_dir", "intraday"),
    "sector_board_constituents": ("lake/bronze/provider=fuyao/sector_board_constituents", "day_file", "close"),
}
for _dataset_id, (_dir, _layout, _kind, _src) in day_seals.PUBLIC.items():
    LAYOUT[_dataset_id] = (_dir, "partition",
                           "t_plus_1" if _dataset_id == "margin_detail_exchange" else
                           "next_day" if _dataset_id == "announcements_cninfo" else
                           "none" if _dataset_id in ("lockup_expiry_em", "sw_industry_history") else "close")
# catalog ids that name one fixed snapshot of a layout above
ALIASES = {"reference_snapshot_baostock_20260923": "reference_snapshot_baostock"}


def _layout(dataset_id: str):
    return LAYOUT.get(ALIASES.get(dataset_id, dataset_id))


def _catalog_entries() -> list[dict]:
    from quantlab.data.dataset_catalog import read_data_catalog
    try:
        return read_data_catalog()["entries"]
    except Exception as error:
        raise DataProviderError("data_catalog", f"读取数据清单失败：{error}") from error


# ================================================================== trading calendar (offline)
class _Calendar:
    def __init__(self, data_root: Path):
        self.days: list[str] = []
        self.end = None
        self.snapshot = None  # date of the reference snapshot the calendar was read from
        base = data_root / "lake/bronze/provider=baostock/reference_snapshots"
        try:
            snaps = sorted(p for p in base.glob("snapshot=*") if (p / "trade_calendar.parquet").is_file())
            if snaps:
                import pandas as pd
                cal = pd.read_parquet(snaps[-1] / "trade_calendar.parquet")
                mask = cal["is_trading_day"].astype(str).isin({"1", "1.0", "True", "true"})
                self.days = sorted(str(v)[:10] for v in cal.loc[mask, "calendar_date"])
                self.end = max(str(v)[:10] for v in cal["calendar_date"])
                self.snapshot = snaps[-1].name.split("=", 1)[1]
        except Exception:
            self.days = []
        if not self.days:
            self.end = self.snapshot = None
        self._set = set(self.days)

    def snapshot_covering(self, day: str) -> str | None:
        """The snapshot whose trade calendar reaches ``day`` (collectors read that exact file)."""
        return self.snapshot if self.end and day <= self.end else None

    def is_trading(self, day: str) -> tuple[bool, bool]:
        """(is_trading_day, inferred): beyond the calendar, weekdays are assumed trading."""
        if self.end and day <= self.end:
            return day in self._set, False
        return date.fromisoformat(day).weekday() < 5, True

    def previous(self, day: str) -> str:
        cursor = date.fromisoformat(day) - timedelta(days=1)
        for _ in range(30):
            if self.is_trading(cursor.isoformat())[0]:
                return cursor.isoformat()
            cursor -= timedelta(days=1)
        return cursor.isoformat()



# ================================================================== status index
def _latest_partition(directory: Path, layout: str) -> tuple[str | None, list[Path]]:
    if layout == "partition":
        files = [p for p in directory.glob("*.parquet") if not p.name.startswith("._")]
        empties = [p for p in (directory / "_empty").glob("*.json")] if (directory / "_empty").is_dir() else []
        stems = sorted({p.stem for p in files} | {p.stem for p in empties})
        return (stems[-1] if stems else None), files
    if layout == "day_dir":
        days = sorted(p.name.split("=", 1)[1] for p in directory.glob("date=*") if p.is_dir())
        files = [f for d in directory.glob("date=*") for f in d.glob("*.parquet")]
        return (days[-1] if days else None), files
    if layout == "day_file":
        files = sorted(p for p in directory.glob("date=*.parquet") if not p.name.startswith("._"))
        return (files[-1].stem.split("=", 1)[1] if files else None), files
    if layout == "snapshot":
        snaps = sorted(p for p in directory.glob("snapshot=*") if (p / "manifest.json").is_file())
        return (snaps[-1].name.split("=", 1)[1] if snaps else None), [f for s in snaps for f in s.glob("*.parquet")]
    return None, []


def refresh_status_index(data_root=None, *, datasets=None, log=print) -> dict:
    """Rebuild (reads Parquet footers); run at the end of update jobs, not by the page.

    ``datasets`` limits the rebuild to some ids and merges into the existing index."""
    import pyarrow.parquet as pq
    data_root = _root(data_root)
    index_path = data_root / STATUS_INDEX
    index = {"datasets": {}}
    if datasets and index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    index["built_at"] = _now().isoformat()
    for dataset_id, (rel, layout, _cadence) in LAYOUT.items():
        if datasets and dataset_id not in datasets:
            continue
        directory = data_root / rel
        if not directory.is_dir():
            continue
        started = time.monotonic()
        entry = {"latest_date": None, "rows": None, "files": 0, "last_success_at": None, "errors": []}
        try:
            if layout == "per_symbol":
                files = [p for p in directory.glob("*.parquet") if not p.name.startswith("._")]
                rows, latest = 0, None
                for data_file in files:
                    meta = pq.read_metadata(data_file)
                    rows += meta.num_rows
                    # the 'date' column max from row-group statistics (no data read)
                    names = meta.schema.names
                    if "date" in names:
                        col = names.index("date")
                        for g in range(meta.num_row_groups):
                            stats = meta.row_group(g).column(col).statistics
                            if stats is not None and stats.has_min_max:
                                value = str(stats.max)[:10]
                                latest = value if latest is None or value > latest else latest
                entry.update(rows=rows, files=len(files), latest_date=latest,
                             last_success_at=_iso(max((p.stat().st_mtime for p in files), default=None)))
            else:
                latest, files = _latest_partition(directory, layout)
                rows = sum(pq.read_metadata(p).num_rows for p in files)
                entry.update(rows=rows, files=len(files), latest_date=latest,
                             last_success_at=_iso(max((p.stat().st_mtime for p in files), default=None)))
        except Exception as error:
            entry["errors"].append(f"{type(error).__name__}: {error}"[:200])
        index["datasets"][dataset_id] = entry
        log(f"状态索引 {dataset_id}：{entry['latest_date']} {entry['rows']} 行，{round(time.monotonic() - started, 1)} 秒")
    if index_path.parent.resolve() != (data_root / "catalog").resolve():
        raise DataProviderError("data_status_service", "状态索引路径异常，拒绝写入")
    tmp = index_path.with_name(index_path.name + ".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, index_path)
    return index


# ================================================================== A. status
class DataStatusService:
    def __init__(self, data_root=None, *, now_fn=None):
        self.data_root = _root(data_root)
        self.now_fn = now_fn or _now

    def _expected(self, cadence: str, now: datetime, calendar: _Calendar) -> tuple[str | None, bool | None]:
        today = now.date().isoformat()
        trading, _ = calendar.is_trading(today)
        if cadence == "close":
            return (today if trading and now.hour >= 18 else calendar.previous(today)), trading
        if cadence == "intraday":
            return (today if trading and now.strftime("%H:%M") >= "09:30" else calendar.previous(today)), trading
        if cadence == "t_plus_1":
            return calendar.previous(today), trading
        if cadence == "next_day":
            return (now.date() - timedelta(days=1)).isoformat(), True
        return None, None

    def list_status(self) -> dict:
        if not (self.data_root / "catalog").is_dir():
            raise DataProviderError("data_status_service", f"数据盘未连接：找不到 {self.data_root}")
        now = self.now_fn()
        calendar = _Calendar(self.data_root)
        index_path = self.data_root / STATUS_INDEX
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {"datasets": {}}
        seen = set()
        rows = []
        for entry in _catalog_entries():
            dataset_id = entry["dataset_id"]
            seen.add(dataset_id)
            rows.append(self._row(dataset_id, entry, index, now, calendar))
        for extra in ("stock_intraday_snapshot",):
            if extra not in seen:
                rows.append(self._row(extra, {"status": "NOT_LISTED", "delivery": "FILE"}, index, now, calendar))
        return {"as_of": now.isoformat(), "status_index_built_at": index.get("built_at"),
                "calendar_through": calendar.end, "datasets": rows, "seals": day_seals.recent(self.data_root, 30)}

    def _row(self, dataset_id, entry, index, now, calendar) -> dict:
        row = {"dataset_id": dataset_id, "catalog_status": entry.get("status"), "latest_date": None,
               "last_success_at": None, "rows": None, "files": None, "health": "unknown", "health_reason": None,
               "expected_today": None, "updated_today": None,
               "sealed_through": day_seals.sealed_through(self.data_root, ALIASES.get(dataset_id, dataset_id))}
        layout = _layout(dataset_id)
        if entry.get("delivery") in ("API", "STREAM") or layout is None:
            row["health_reason"] = "查询接口或非日更数据，不按日期更新" if entry.get("delivery") in ("API", "STREAM") \
                else "DATA 未登记更新状态（旧数据或内部数据）"
            return row
        rel, kind, cadence = layout
        if dataset_id in ALIASES:
            row.update(latest_date=dataset_id.rsplit("_", 1)[-1][:4] + "-" + dataset_id[-4:-2] + "-" + dataset_id[-2:],
                       health="ok", health_reason="固定日期的快照，不再更新")
            return row
        stats = index.get("datasets", {}).get(ALIASES.get(dataset_id, dataset_id))
        if stats:
            row.update(latest_date=stats["latest_date"], last_success_at=stats["last_success_at"],
                       rows=stats["rows"], files=stats["files"])
        # live overlay for today's intraday recorders (receipts only)
        if cadence == "intraday":
            receipt = self.data_root / rel / "_receipts" / f"{now.date().isoformat()}.json"
            if receipt.is_file():
                try:
                    samples = json.loads(receipt.read_text(encoding="utf-8")).get("samples", [])
                except ValueError:
                    samples = []
                ok = [s for s in samples if s.get("status") == "ok"]
                if ok:
                    row.update(latest_date=now.date().isoformat(), last_success_at=ok[-1]["sampled_at"])
                    row["last_record_at"] = ok[-1]["sampled_at"]
                    row["records_today"] = len(ok)
                    row["failures_today"] = len(samples) - len(ok)
        expected, expected_today = self._expected(cadence, now, calendar)
        row["expected_today"] = expected_today
        row["updated_today"] = bool(row["last_success_at"] and str(row["last_success_at"])[:10] == now.date().isoformat())
        if stats and stats.get("errors"):
            row.update(health="error", health_reason="状态统计出错：" + stats["errors"][0])
        elif row["latest_date"] is None:
            row.update(health="unknown", health_reason="还没有状态记录，等下一次更新任务结束后生成")
        elif expected and row["latest_date"] < expected:
            row.update(health="lagging", health_reason=f"最新日期 {row['latest_date']}，应到 {expected}")
        else:
            row.update(health="ok")
        if calendar.end and now.date().isoformat() > calendar.end:
            row["health_reason"] = ((row["health_reason"] + "；") if row["health_reason"] else "") + \
                f"交易日历只到 {calendar.end}，之后按工作日推断"
        return row


# ================================================================== B. preview / trial query
COLUMN_NOTES = {
    "date": "交易日或分区日期", "code": "证券代码", "symbol": "证券代码（sh.600000）", "name": "名称",
    "open": "开盘价（元）", "high": "最高价（元）", "low": "最低价（元）", "close": "收盘价（元）",
    "last": "现价（元）", "previous_close": "昨收（元）", "volume": "成交量（股）", "amount": "成交额（元）",
    "change_pct": "涨跌幅（%）", "factor": "前复权因子", "tradestatus": "1 交易 0 停牌", "isST": "1 为 ST",
    "time": "时间 YYYYMMDDHHMMSSmmm", "_observed_at": "采集时间（UTC）", "as_of": "数据时间",
}
CODE_COLUMNS = ("code", "symbol", "SECURITY_CODE")


def _preview_code(value) -> str:
    """``600519`` / ``sh600519`` / ``sh.600519`` -> ``sh.600519``; anything else is rejected."""
    match = re.fullmatch(r"(?:(sh|sz|bj)[._]?)?(\d{6})", str(value).strip().lower())
    if not match:
        raise InvalidRequest("code 应为 6 位代码，可带 sh/sz/bj 前缀，例如 600519 或 sz.300750")
    exchange, code = match.groups()
    if exchange is None:
        # 920xxx and 4xxxxx/8xxxxx are Beijing; 6xxxxx and 900xxx B shares Shanghai; the rest Shenzhen
        exchange = "bj" if code.startswith(("920", "4", "8")) else "sh" if code.startswith(("6", "9")) else "sz"
    return f"{exchange}.{code}"


def _inside(path: Path, base: Path) -> Path:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        raise InvalidRequest("过滤条件指向数据集目录之外") from None
    return path


def _type_name(dtype) -> str:
    text = str(dtype)
    if "int" in text:
        return "integer"
    if "float" in text or "decimal" in text:
        return "number"
    if "date" in text or "timestamp" in text:
        return "date"
    if "bool" in text:
        return "boolean"
    return "string"


class DataPreviewService:
    MAX_LIMIT = 200

    def __init__(self, data_root=None, *, research_provider=None, quote_service=None, sector_provider=None):
        self.data_root = _root(data_root)
        self._research = research_provider
        self._quotes = quote_service
        self._sectors = sector_provider
        self._lock = threading.Lock()
        self._last_query = 0.0

    # ---------------- preview
    def _entry(self, dataset_id: str) -> dict:
        for entry in _catalog_entries():
            if entry["dataset_id"] == dataset_id:
                return entry
        raise InvalidRequest(f"数据清单里没有 {dataset_id}")

    def preview(self, dataset_id: str, limit: int = 20, filters=None) -> dict:
        import pandas as pd
        import pyarrow.parquet as pq
        entry = self._entry(dataset_id)
        if entry["status"] != "READY":
            raise InvalidRequest(f"{dataset_id} 在数据清单里是 {entry['status']}，不提供预览")
        if entry["delivery"] not in ("FILE",):
            raise InvalidRequest(f"{dataset_id} 是 {entry['delivery']}，请用 query_schema / query 试查")
        layout = _layout(dataset_id)
        if layout is None:
            raise InvalidRequest(f"{dataset_id} 由产品已有的 Store 读取，DATA 不提供逐文件预览")
        if not isinstance(limit, int) or not 1 <= limit <= self.MAX_LIMIT:
            raise InvalidRequest("limit 须为 1–200 的整数")
        filters = {k: v for k, v in dict(filters or {}).items() if v not in (None, "")}
        unknown = set(filters) - {"code", "date"}
        if unknown:
            raise InvalidRequest(f"不支持的过滤条件：{sorted(unknown)}；允许 code、date")
        if "date" in filters:
            try:
                filters["date"] = date.fromisoformat(str(filters["date"]).strip()).isoformat()
            except ValueError:
                raise InvalidRequest("date 格式应为 YYYY-MM-DD") from None
        if "code" in filters:
            filters["code"] = _preview_code(filters["code"])
        rel, kind, _ = layout
        base = self.data_root / rel
        if not base.is_dir():
            raise DataProviderError(dataset_id, f"数据盘未连接或目录不存在：{base}")
        allowed = [{"name": "code", "type": "string", "example": "600519"},
                   {"name": "date", "type": "date", "example": "2026-09-24"}]
        if kind == "per_symbol":
            code = filters.get("code") or "sh.600000"
            path = _inside(base / (code.replace(".", "_", 1) + ".parquet"), base)
            if not path.is_file():
                raise InvalidRequest(f"{dataset_id} 没有 {code} 的文件")
            paths, code_filter = [path], None
        else:
            day = filters.get("date")
            if dataset_id in ALIASES:
                day = ALIASES_DAY.get(dataset_id)
            if kind == "partition":
                latest, _ = _latest_partition(base, kind)
                day = day or latest
                paths = [base / f"{day}.parquet"]
            elif kind == "day_file":
                latest, _ = _latest_partition(base, kind)
                paths = [base / f"date={day or latest}.parquet"]
            elif kind == "day_dir":
                latest, _ = _latest_partition(base, kind)
                paths = sorted((base / f"date={day or latest}").glob("*.parquet"))[-1:]
            else:
                latest, _ = _latest_partition(base, kind)
                snap = base / f"snapshot={day or latest}"
                paths = [snap / "stock_basic.parquet"]
            paths = [p for p in paths if _inside(p, base).is_file()]
            if not paths:
                empty = _inside(base / "_empty" / f"{day}.json", base)
                if empty.is_file():
                    return {"dataset_id": dataset_id, "columns": [], "rows": [], "total_rows": 0, "truncated": False,
                            "filters_allowed": allowed, "note": f"{day} 供应商确认无数据"}
                raise InvalidRequest(f"{dataset_id} 没有 {day or '最新'} 的数据")
            code_filter = filters.get("code")
        frame = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
        if code_filter:
            column = next((c for c in CODE_COLUMNS if c in frame.columns), None)
            if column is None:
                raise InvalidRequest(f"{dataset_id} 没有证券代码列，不能按 code 过滤")
            wanted = code_filter.split(".")[-1]
            frame = frame[frame[column].astype(str).str.lower().str[-6:] == wanted]
        if kind == "per_symbol" and filters.get("date") and "date" in frame.columns:
            frame = frame[frame["date"].astype(str).str[:10] == filters["date"]]
        total = int(len(frame))
        # per-symbol files without a date: the latest rows first; total_rows still counts the whole file
        view = frame.tail(limit).iloc[::-1] if kind == "per_symbol" and not filters.get("date") else frame.head(limit)
        columns = [{"name": str(c), "type": _type_name(view[c].dtype), "description": COLUMN_NOTES.get(str(c), "")}
                   for c in view.columns]
        rows = [_jsonable(r) for r in view.to_dict(orient="records")]
        return {"dataset_id": dataset_id, "columns": columns, "rows": rows, "total_rows": total,
                "truncated": total > len(rows), "filters_allowed": allowed,
                "source_files": [str(p.relative_to(self.data_root)) for p in paths]}

    # ---------------- query APIs
    QUERY = {
        "research_search": ("问财", [
            {"name": "query", "type": "string", "required": True, "example": "宁德时代 储能", "description": "自然语言检索词"},
            {"name": "channel", "type": "string", "required": False, "enum": ["report", "news", "announcement"],
             "example": "report", "description": "研报 / 新闻 / 公告"},
            {"name": "size", "type": "integer", "required": False, "min": 1, "max": 50}]),
        "stock_research_reports": ("东财研报", [
            {"name": "code", "type": "string", "required": True, "example": "600519", "description": "6 位代码"},
            {"name": "limit", "type": "integer", "required": False, "min": 1, "max": 50}]),
        "stock_news": ("东财资讯", [
            {"name": "code", "type": "string", "required": True, "example": "300750", "description": "6 位代码"},
            {"name": "limit", "type": "integer", "required": False, "min": 1, "max": 50}]),
        "stock_announcements": ("巨潮", [
            {"name": "code", "type": "string", "required": True, "example": "601318", "description": "6 位代码"},
            {"name": "start", "type": "date", "required": False, "example": "2026-09-01"},
            {"name": "end", "type": "date", "required": False, "example": "2026-09-24"},
            {"name": "limit", "type": "integer", "required": False, "min": 1, "max": 50}]),
        "financial_statements": ("新浪财报", [
            {"name": "code", "type": "string", "required": True, "example": "600519", "description": "6 位代码"},
            {"name": "statement", "type": "string", "required": False, "enum": ["income", "balance", "cashflow"],
             "example": "income"},
            {"name": "periods", "type": "integer", "required": False, "min": 1, "max": 8}]),
        "investor_qa": ("巨潮互动易", [
            {"name": "code", "type": "string", "required": True, "example": "300750", "description": "深市 6 位代码"},
            {"name": "limit", "type": "integer", "required": False, "min": 1, "max": 50}]),
        "realtime_quote": ("扶摇 + 腾讯/东财/新浪", [
            {"name": "text", "type": "string", "required": True, "example": "600519 宁德时代",
             "description": "代码或名称，最多 10 只"}]),
        "sector_board_snapshot": ("扶摇（同花顺板块）", [
            {"name": "types", "type": "string", "required": False, "enum": ["concept", "industry", "concept,industry"],
             "example": "concept,industry"}]),
        "sector_board_members": ("扶摇（同花顺板块）+ 腾讯/新浪核对", [
            {"name": "code", "type": "string", "required": True, "example": "885431.TI", "description": "板块代码"}]),
    }

    def query_schema(self, dataset_id: str) -> dict:
        entry = self._entry(dataset_id)
        if entry["delivery"] != "API":
            raise InvalidRequest(f"{dataset_id} 不是查询接口，请用 preview")
        if dataset_id not in self.QUERY:
            raise InvalidRequest(f"{dataset_id} 暂不提供页面试查（{entry['status']}）")
        source, params = self.QUERY[dataset_id]
        return {"dataset_id": dataset_id, "catalog_status": entry["status"], "params": params, "source": source,
                "rate_limit": "同一实例串行，至少间隔 1 秒；东财相关接口 1.5 秒"}

    def _validate(self, dataset_id: str, params) -> dict:
        schema = {p["name"]: p for p in self.QUERY[dataset_id][1]}
        params = dict(params or {})
        unknown = set(params) - set(schema)
        if unknown:
            raise InvalidRequest(f"未知参数：{sorted(unknown)}")
        for name, spec in schema.items():
            if spec.get("required") and params.get(name) in (None, ""):
                raise InvalidRequest(f"缺少参数 {name}")
            if name in params and spec["type"] == "integer":
                try:
                    params[name] = int(params[name])
                except (TypeError, ValueError):
                    raise InvalidRequest(f"{name} 须为整数") from None
                if not spec.get("min", -1e18) <= params[name] <= spec.get("max", 1e18):
                    raise InvalidRequest(f"{name} 须在 {spec.get('min')}–{spec.get('max')} 之间")
            if name in params and spec.get("enum") and params[name] not in spec["enum"]:
                raise InvalidRequest(f"{name} 只能是 {spec['enum']}")
        return params

    def query(self, dataset_id: str, params=None) -> dict:
        entry = self._entry(dataset_id)
        if entry["status"] != "READY":
            raise InvalidRequest(f"{dataset_id} 在数据清单里是 {entry['status']}，不能试查")
        if dataset_id not in self.QUERY:
            raise InvalidRequest(f"{dataset_id} 暂不提供页面试查")
        params = self._validate(dataset_id, params)
        with self._lock:
            gap = 1.0 - (time.monotonic() - self._last_query)
            if gap > 0:
                time.sleep(gap)
            try:
                rows, as_of, warnings = self._call(dataset_id, params)
            finally:
                self._last_query = time.monotonic()
        columns = []
        if rows:
            for key, value in rows[0].items():
                kind = ("number" if isinstance(value, float) else "integer" if isinstance(value, int)
                        and not isinstance(value, bool) else "boolean" if isinstance(value, bool) else "string")
                columns.append({"name": key, "type": kind, "description": COLUMN_NOTES.get(key, "")})
        return {"dataset_id": dataset_id, "columns": columns, "rows": [_jsonable(r) for r in rows[:200]],
                "as_of": as_of or _now().isoformat(), "source": self.QUERY[dataset_id][0], "warnings": warnings}

    def _call(self, dataset_id, params):
        if dataset_id in ("research_search", "stock_research_reports", "stock_news", "stock_announcements",
                          "financial_statements", "investor_qa"):
            if self._research is None:
                from quantlab.data.research_provider import ResearchDataProvider
                self._research = ResearchDataProvider.from_env()
            result = getattr(self._research, dataset_id)(**params)
            warnings = ["只返回了一部分，共 %s 条" % result.total] if result.truncated else []
            return [dict(r) for r in result.rows], result.fetched_at, warnings
        if dataset_id == "realtime_quote":
            if self._quotes is None:
                from quantlab.agent.fuyao_mcp import FuyaoMCPClient
                from quantlab.agent.live_stock_quote import LiveStockQuoteService
                from quantlab.trading.fuyao_market_snapshot import build_live_quote_provider
                self._quotes = LiveStockQuoteService(self.data_root, provider=build_live_quote_provider(FuyaoMCPClient()))
            value = self._quotes.query(params["text"])
            if value is None:
                raise InvalidRequest("没有识别出证券代码或名称")
            if value.get("status") != "OK":
                raise DataProviderError(dataset_id, str(value.get("message") or value.get("status")))
            warnings = [f"{i['symbol']}：{i['reason']}" for i in value.get("consensus_issues", [])]
            return value["quotes"], value.get("as_of"), warnings
        if self._sectors is None:
            from quantlab.data.sector_intraday import SectorIntradayProvider
            self._sectors = SectorIntradayProvider(data_root=self.data_root)
        if dataset_id == "sector_board_snapshot":
            types = [t for t in str(params.get("types") or "concept,industry").split(",") if t]
            value = self._sectors.board_snapshot(types)
            return value["boards"], value["as_of"], ([value.get("stale_reason")] if value.get("stale") else [])
        value = self._sectors.board_members(params["code"])
        return value["members"], value["as_of"], ([value.get("stale_reason")] if value.get("stale") else [])


ALIASES_DAY = {"reference_snapshot_baostock_20260923": "2026-09-23"}


# ================================================================== C. update jobs
SAME_DAY_PUBLIC = ("em_monitor", "em_anomaly", "index_weights", "holder_count", "northbound_minute",
                   "earnings_forecast", "share_buyback", "equity_pledge", "ipo_calendar", "ths_hot_rank", "em_hot_rank")
DATED_PUBLIC = ("ths_limit_up", "block_trades", "institution_survey", "holder_trades")
PUBLIC_IDS = {"sw_industry_history": "sw_industry_history", "cninfo_announcements": "announcements_cninfo",
              "ths_limit_up": "limit_up_pool_ths", "em_monitor": "monitor_pool_em", "em_anomaly": "price_anomaly_em",
              "index_weights": "index_weights_csindex", "margin_official": "margin_detail_exchange",
              "block_trades": "block_trades_em", "lockup_expiry": "lockup_expiry_em", "holder_count": "holder_count_em",
              "northbound_minute": "northbound_minute_ths", "earnings_forecast": "earnings_forecast_em",
              "institution_survey": "institution_survey_em", "holder_trades": "holder_trades_em",
              "share_buyback": "share_buyback_em", "equity_pledge": "equity_pledge_em",
              "ipo_calendar": "ipo_calendar_em", "ths_hot_rank": "hot_rank_ths", "em_hot_rank": "hot_rank_em"}

JOBS_SPEC = [
    {"job_id": "daily_close_update", "name": "收盘后日常更新",
     "description": "参考快照、公开数据（含热度榜）、板块成分、日状态、日K、5 分钟、前复权，最后封存当天并刷新状态。"
                    "只能当天观察的数据只在当天执行时采集。",
     "params": [{"name": "date", "type": "date", "required": False, "default": "today", "description": "交易日"}],
     "estimated_seconds": 6 * 3600, "needs_data_disk": True, "uses_network": True,
     "writes": ["reference_snapshot_baostock", "bars_daily_baostock_raw", "bars_min5_baostock_raw",
                "security_status_baostock_v2", "qfq_published_f24", "sector_board_constituents",
                *sorted(set(PUBLIC_IDS.values()) - {"sw_industry_history", "lockup_expiry_em"})]},
    {"job_id": "sector_recorder_start", "name": "启动盘中记录器",
     "description": "先刷新板块成分，然后交易时间每分钟记录全部板块，并在 09:25/10:00/11:30/14:00/14:57/15:00 记录全市场个股快照，15:25 自动结束。",
     "params": [], "estimated_seconds": 7 * 3600, "needs_data_disk": True, "uses_network": True,
     "writes": ["sector_board_constituents", "sector_board_intraday", "stock_intraday_snapshot"]},
    {"job_id": "sector_recorder_stop", "name": "停止盘中记录器", "description": "停止正在运行的盘中记录器。",
     "params": [], "estimated_seconds": 30, "needs_data_disk": True, "uses_network": False, "writes": []},
    {"job_id": "backfill_day", "name": "补某一天",
     "description": "按收盘后日常更新在这一天的范围补缺的按日期分区公开数据（涨停池、大宗交易、机构调研、股东增减持，"
                    "上一交易日到前一天的公告目录，前一交易日的融资融券），已有的跳过。"
                    "只能当天观察的数据过后补不回来；日K/5 分钟/日状态的中间缺口不在此任务内。",
     "params": [{"name": "date", "type": "date", "required": True, "description": "要补的日期"}],
     "estimated_seconds": 600, "needs_data_disk": True, "uses_network": True,
     "writes": ["limit_up_pool_ths", "block_trades_em", "institution_survey_em", "holder_trades_em",
                "announcements_cninfo", "margin_detail_exchange"]},
    {"job_id": "seal_day", "name": "封存某一天",
     "description": "把这一天所有按日期分区的数据汇总成封存清单 catalog/seals/YYYY-MM-DD.json 并立即核对。"
                    "次日才发布的公告目录、融资融券等标为待封存，补采后再封存一次即可加入。",
     "params": [{"name": "date", "type": "date", "required": True, "description": "日期"}],
     "estimated_seconds": 120, "needs_data_disk": True, "uses_network": False, "writes": []},
    {"job_id": "verify_seal", "name": "核对封存", "description": "按封存清单重算校验码，列出被改动、缺失或事后新增的文件。",
     "params": [{"name": "date", "type": "date", "required": True, "description": "开始日期"},
                {"name": "end", "type": "date", "required": False, "description": "结束日期（可选，核对一段）"}],
     "estimated_seconds": 120, "needs_data_disk": True, "uses_network": False, "writes": []},
    {"job_id": "revoke_seal", "name": "撤销封存",
     "description": "撤销某一天的封存以便重采：封存清单和已封存的文件整份移到 catalog/seals/_revoked/，不删除。必须写明原因。",
     "params": [{"name": "date", "type": "date", "required": True, "description": "日期"},
                {"name": "reason", "type": "string", "required": True, "description": "为什么要撤销"}],
     "estimated_seconds": 60, "needs_data_disk": True, "uses_network": False, "writes": []},
]


LIVE = ("queued", "running")
QUEUED_WITHOUT_PROCESS = timedelta(minutes=5)
JOBS_LOCK = ".lock"            # under catalog/jobs: serialises "is it running?" + starting a run
RUNNER_LOCK = "runner.lock"    # in a run directory: held by job_runner.py for as long as it lives


def _write_json(path: Path, body) -> None:
    """Atomic replace; the temporary name is per writer, so concurrent writers never share one."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def _exclusive(path: Path):
    """Exclusive advisory lock for the ``with`` body (the job system itself is POSIX-only)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:
        fcntl = None
    with open(path, "a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def runner_alive(run_dir: Path, state: dict) -> bool:
    """Whether the runner of this run is still running.

    A running runner holds ``runner.lock``, so a free lock means it is gone even when the
    system has since given its pid to another process (after a restart).  Queued runs, whose
    runner has not taken the lock yet, and runs from before the lock fall back to the pid.
    """
    lock = run_dir / RUNNER_LOCK
    if state.get("state") != "running" or not lock.is_file():
        return pid_alive(state.get("pid"))
    try:
        import fcntl
    except ImportError:
        return pid_alive(state.get("pid"))
    try:
        with open(lock, "a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
    except OSError:
        return pid_alive(state.get("pid"))


def signal_runner(run_dir: Path, state: dict, sig=signal.SIGTERM) -> bool:
    """Signal a live runner's process group; a pid that no longer belongs to the runner is left alone."""
    pid = state.get("pid")
    if not pid or not runner_alive(run_dir, state):
        return False
    try:
        os.killpg(int(pid), sig)  # the runner leads its own session (start_new_session)
    except ProcessLookupError:
        return False
    return True


def _days_between(start: str, end: str) -> list[str]:
    """Calendar days strictly after ``start`` and strictly before ``end``."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(first + timedelta(days=i)).isoformat() for i in range(1, (last - first).days)]


def _date_param(params, name, *, required, default_today=False, today: str | None = None) -> str | None:
    value = params.get(name)
    today = today or _now().date().isoformat()
    if value == "today":
        return today
    if value in (None, ""):
        if required and not default_today:
            raise InvalidRequest(f"缺少参数 {name}")
        return today if default_today else None
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise InvalidRequest(f"{name} 格式应为 YYYY-MM-DD") from None


class DataUpdateJobs:
    def __init__(self, data_root=None, *, python=None, now_fn=None):
        self.data_root = _root(data_root)
        self.python = python or sys.executable
        self.now_fn = now_fn or _now
        self.base = self.data_root / JOBS

    # ---------------- helpers
    def _spec(self, job_id):
        spec = next((j for j in JOBS_SPEC if j["job_id"] == job_id), None)
        if spec is None:
            raise InvalidRequest(f"未知任务 {job_id}")
        return spec

    def _disk_ok(self) -> bool:
        return (self.data_root / "catalog/dataset_registry.json").is_file()

    def _runs(self) -> list[dict]:
        folder = self.base / "runs"
        if not folder.is_dir():
            return []
        rows = []
        for path in folder.glob("*/state.json"):
            try:
                rows.append(self._refresh(json.loads(path.read_text(encoding="utf-8")), path))
            except (OSError, ValueError):
                continue
        return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)

    def _refresh(self, state: dict, path: Path) -> dict:
        if state.get("state") not in LIVE:
            return state
        if state.get("pid"):
            gone = not runner_alive(path.parent, state)
        else:  # run() records the pid right after starting the process; without one the start was cut short
            try:
                gone = self.now_fn() - datetime.fromisoformat(state["created_at"]) > QUEUED_WITHOUT_PROCESS
            except (KeyError, TypeError, ValueError):
                gone = False
        if gone:
            state.update(state="interrupted", finished_at=state.get("finished_at") or self.now_fn().isoformat(),
                         error=state.get("error") or "后台进程已不在（关机、拔盘或被强制结束）")
            _write_json(path, state)
        return state

    def _running(self, job_ids) -> dict | None:
        return next((r for r in self._runs() if r["job_id"] in job_ids and r["state"] in LIVE), None)

    def _partition_present(self, dataset_id: str, day: str) -> bool:
        rel = day_seals.SEALABLE[dataset_id][0]
        base = self.data_root / rel
        return (base / f"{day}.parquet").is_file() or (base / "_empty" / f"{day}.json").is_file()

    # ---------------- public API
    def list_jobs(self) -> dict:
        return {"jobs": [dict(j) for j in JOBS_SPEC]}

    def plan(self, job_id: str, params=None) -> dict:
        spec = self._spec(job_id)
        params = dict(params or {})
        allowed = {p["name"] for p in spec["params"]}
        if set(params) - allowed:
            raise InvalidRequest(f"{job_id} 不接受参数 {sorted(set(params) - allowed)}")
        now = self.now_fn()
        today = now.date().isoformat()
        steps, warnings, blocked = [], [], None
        calendar = _Calendar(self.data_root) if self._disk_ok() else None
        if not self._disk_ok():
            blocked = "数据盘未连接：找不到数据根的注册表"
        elif job_id != "sector_recorder_stop":
            running = self._running({job_id} | ({"sector_recorder_start"} if job_id == "sector_recorder_start" else set()))
            if running:
                blocked = f"同一任务正在运行（{running['run_id']}）"
        build = getattr(self, "_plan_" + job_id)
        if blocked is None:
            steps, warnings, blocked, params = build(params, today, calendar, warnings)
        body = {"plan_id": None, "job_id": job_id, "params": params, "data_root": str(self.data_root),
                "created_at": now.isoformat(), "expires_at": (now + PLAN_TTL).isoformat(),
                "steps": steps, "estimated_seconds": spec["estimated_seconds"] if steps else 0,
                "warnings": warnings, "blocked_reason": blocked}
        body["plan_id"] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:32]
        folder = self.base / "plans"
        folder.mkdir(parents=True, exist_ok=True)
        # atomic: two launchers planning in the same second get the same plan_id and file name
        _write_json(folder / f"{body['plan_id']}.json", body)
        return {k: v for k, v in body.items() if k != "data_root"}

    @staticmethod
    def _step(name, action, datasets, dates, kind, *, overwrites=False, note=None, weight=1, **extra):
        return {"name": name, "action": action, "datasets": datasets, "dates": dates, "overwrites": overwrites,
                "note": note, "kind": kind, "weight": weight, **extra}

    def _public_steps(self, day, today, calendar, *, calendar_snapshot):
        """(steps, warnings) for public-source partitions of ``day``.

        ``calendar_snapshot`` names the reference snapshot whose trade calendar the collectors
        read.  On a trading day the announcement-dated sources also cover the calendar days since
        the previous trading day, because nobody runs the close update on weekends and holidays.
        """
        steps, warnings = [], []
        if day == today:
            import importlib.util
            fetch = [n for n in SAME_DAY_PUBLIC if not self._partition_present(PUBLIC_IDS[n], day)]
            if "index_weights" in fetch and not (importlib.util.find_spec("openpyxl") and importlib.util.find_spec("xlrd")):
                warnings.append("指数权重需要 openpyxl 和 xlrd，当前 Python 没装，这一项会失败；"
                                "安装：/Volumes/Lexar/niuniu/.venv/bin/pip install openpyxl xlrd")
            skip = [n for n in SAME_DAY_PUBLIC if n not in fetch]
            if fetch:
                steps.append(self._step("当天观察的公开数据", "fetch", [PUBLIC_IDS[n] for n in fetch], [day], "public",
                                        public=[[n, PUBLIC_IDS[n], None, None] for n in fetch],
                                        calendar=calendar_snapshot, weight=3, note="只能当天采集"))
            if skip:
                steps.append(self._step("当天观察的公开数据（已有）", "skip_existing", [PUBLIC_IDS[n] for n in skip],
                                        [day], "public", note="今天已采"))
        else:
            warnings.append("异动监控、回购、质押等只能当天观察的数据，不是当天执行就采不到，本次不采。")
        trading = calendar.is_trading(day)[0]
        prev_trading = calendar.previous(day)
        dated = []
        if trading:
            gap = _days_between(prev_trading, day)  # weekends and holidays before this trading day
            dated += [[n, PUBLIC_IDS[n], day, day] for n in DATED_PUBLIC]
            dated += [[n, PUBLIC_IDS[n], d, d] for d in gap for n in ("institution_survey", "holder_trades")]
            announcement_days = [prev_trading, *gap]
        else:
            dated += [[n, PUBLIC_IDS[n], day, day] for n in ("institution_survey", "holder_trades")]
            announcement_days = [(date.fromisoformat(day) - timedelta(days=1)).isoformat()]
        dated += [["cninfo_announcements", "announcements_cninfo", d, d] for d in announcement_days]
        dated.append(["margin_official", "margin_detail_exchange", prev_trading, prev_trading])
        fetch = [d for d in dated if not self._partition_present(d[1], d[2])
                 and not day_seals.is_sealed(self.data_root, d[1], d[2])]
        skip = [d for d in dated if d not in fetch]
        if fetch:
            steps.append(self._step("按日期的公开数据", "fetch", list(dict.fromkeys(d[1] for d in fetch)),
                                    sorted({d[2] for d in fetch}), "public", public=fetch,
                                    calendar=calendar_snapshot, weight=2,
                                    note="公告目录补上一交易日到前一天的每个自然日（含周末、节假日），"
                                         "融资融券补前一交易日（都是次日发布）"))
        if skip:
            steps.append(self._step("按日期的公开数据（已有或已封存）", "skip_existing",
                                    list(dict.fromkeys(d[1] for d in skip)), sorted({d[2] for d in skip}), "public"))
        return steps, warnings

    def _plan_daily_close_update(self, params, today, calendar, warnings):
        day = _date_param(params, "date", required=False, default_today=True, today=today)
        params = {"date": day}
        trading, inferred = calendar.is_trading(day)
        if inferred:
            warnings.append(f"交易日历只到 {calendar.end}，{day} 按工作日推断为{'交易日' if trading else '非交易日'}")
        if not trading:
            return [], warnings, f"{day} 不是交易日", params
        if day > today:
            return [], warnings, "不能更新未来的日期", params
        if day == today and self.now_fn().hour < 16:
            return [], warnings, "还没收盘结算，16:00 后再执行（公开数据一般 18:00 后更完整）", params
        if day_seals.load_manifest(self.data_root, day) and not day_seals.plan(self.data_root, day)["pending"]:
            return [], warnings, "这一天已封存，采集只读", params
        steps = []
        ref = self.data_root / f"lake/bronze/provider=baostock/reference_snapshots/snapshot={day}/manifest.json"
        steps.append(self._step("参考快照", "skip_existing" if ref.is_file() else "fetch",
                                ["reference_snapshot_baostock"], [day], "reference"))
        # step 1 takes (or already has) this day's reference snapshot, so the collectors read its calendar
        public, notes = self._public_steps(day, today, calendar, calendar_snapshot=day)
        steps += public
        warnings += notes
        if day == today:
            cons = self.data_root / f"lake/bronze/provider=fuyao/sector_board_constituents/date={day}.parquet"
            steps.append(self._step("板块成分快照", "skip_existing" if cons.is_file() else "fetch",
                                    ["sector_board_constituents"], [day], "constituents", weight=2))
        steps.append(self._step("日状态、日K、5 分钟", "fetch",
                                ["security_status_baostock_v2", "bars_daily_baostock_raw", "bars_min5_baostock_raw"],
                                [day], "bars", weight=60, note="只补缺的证券和尾部交易日，已有的日期不重写"))
        steps.append(self._step("前复权重建", "fetch", ["qfq_published_f24"], [day], "qfq", overwrites=True, weight=15,
                                note="按两源一致的公司行动整体重算，qfq 文件会被新版本替换"))
        prev = calendar.previous(day)
        steps.append(self._step("封存", "seal", ["*"], [prev, day], "seal", trading_day=True,
                                note=f"封存 {day}；同时把 {prev} 待封存的次日数据补封"))
        steps.append(self._step("刷新状态", "verify", ["*"], [day], "status_index", weight=2))
        return steps, warnings, None, params

    def _plan_sector_recorder_start(self, params, today, calendar, warnings):
        trading, inferred = calendar.is_trading(today)
        if inferred:
            warnings.append(f"交易日历只到 {calendar.end}，今天按工作日推断；非交易日记录器会自动退出")
        if not trading:
            return [], warnings, "今天不是交易日", {}
        if self.now_fn().strftime("%H:%M") >= "15:25":
            return [], warnings, "今天已收盘", {}
        if day_seals.is_sealed(self.data_root, "sector_board_intraday", today):
            return [], warnings, "今天的盘中记录已封存，只读", {}
        return [self._step("盘中记录器", "start", ["sector_board_constituents", "sector_board_intraday",
                                                  "stock_intraday_snapshot"], [today], "recorder", weight=1,
                           note="09:15–15:01 每分钟记录板块，固定时点记录全市场个股")], warnings, None, {}

    def _plan_sector_recorder_stop(self, params, today, calendar, warnings):
        running = self._running({"sector_recorder_start"})
        if not running:
            return [], warnings, "盘中记录器没有在运行", {}
        return [self._step("停止盘中记录器", "stop", ["sector_board_intraday"], [today], "stop",
                           target_run=running["run_id"])], warnings, None, {}

    def _plan_backfill_day(self, params, today, calendar, warnings):
        day = _date_param(params, "date", required=True, today=today)
        params = {"date": day}
        if day > today:
            return [], warnings, "不能补未来的日期", params
        snapshot = calendar.snapshot_covering(day)
        if snapshot is None:
            return [], warnings, (f"没有覆盖 {day} 的交易日历（最新参考快照只到 {calendar.end or '—'}），"
                                  "先执行“收盘后日常更新”取得参考快照"), params
        steps, notes = self._public_steps(day, today, calendar, calendar_snapshot=snapshot)
        steps = [s for s in steps if s["kind"] == "public"]
        warnings += notes + ["日K、5 分钟、日状态的中间缺口不在此任务内；尾部缺口由收盘后日常更新补齐。"]
        if not any(s["action"] == "fetch" for s in steps):
            sealed = day_seals.load_manifest(self.data_root, day) is not None
            return steps, warnings, ("这一天已封存，采集只读" if sealed else "这一天没有缺的数据"), params
        return steps, warnings, None, params

    def _plan_seal_day(self, params, today, calendar, warnings):
        day = _date_param(params, "date", required=True, today=today)
        params = {"date": day}
        trading, _ = calendar.is_trading(day)
        preview = day_seals.plan(self.data_root, day, trading_day=trading, today=today)
        if not preview["seal_now"] and preview["already_sealed"]:
            return [], warnings, "这一天已封存，没有新的数据需要封存", params
        if not preview["seal_now"]:
            return [], warnings, "这一天没有可以封存的数据", params
        if preview["pending"]:
            warnings.append("待封存（之后补采再封存）：" + "、".join(p["dataset_id"] for p in preview["pending"]))
        if preview["missing"]:
            warnings.append("当天没有采到、无法补回：" + "、".join(p["dataset_id"] for p in preview["missing"]))
        return [self._step("封存并核对", "seal", [s["dataset_id"] for s in preview["seal_now"]], [day], "seal",
                           trading_day=trading, note=f"第 {preview['revision']} 版；已封存的条目不改")], \
            warnings, None, params

    def _plan_verify_seal(self, params, today, calendar, warnings):
        start = _date_param(params, "date", required=True, today=today)
        end = _date_param(params, "end", required=False, today=today) or start
        if end < start:
            raise InvalidRequest("end 不能早于 date")
        days, cursor = [], date.fromisoformat(start)
        while cursor.isoformat() <= end:
            if day_seals.load_manifest(self.data_root, cursor.isoformat()):
                days.append(cursor.isoformat())
            cursor += timedelta(days=1)
        params = {"date": start, "end": end}
        if not days:
            return [], warnings, "这个范围内没有封存记录", params
        return [self._step("核对封存", "verify", ["*"], days, "verify")], warnings, None, params

    def _plan_revoke_seal(self, params, today, calendar, warnings):
        day = _date_param(params, "date", required=True, today=today)
        reason = str(params.get("reason") or "").strip()
        params = {"date": day, "reason": reason}
        if not reason:
            return [], warnings, "撤销封存必须写明原因", params
        manifest = day_seals.load_manifest(self.data_root, day)
        if manifest is None:
            return [], warnings, "这一天没有封存记录", params
        warnings.append(f"会把第 {manifest['revision']} 版封存清单和 {manifest['totals']['files']} 个文件移到 "
                        "catalog/seals/_revoked/，之后这一天需要重新采集和封存")
        return [self._step("撤销封存", "seal", ["*"], [day], "revoke", overwrites=False, note=reason)], \
            warnings, None, params

    def run(self, plan_id: str, *, trigger: str = "user") -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", str(plan_id or "")):
            raise InvalidRequest("plan_id 无效")
        path = self.base / "plans" / f"{plan_id}.json"
        if not path.is_file():
            raise InvalidRequest("找不到这个计划，请重新生成")
        plan = json.loads(path.read_text(encoding="utf-8"))
        if plan.get("blocked_reason"):
            raise InvalidRequest("计划被阻止：" + plan["blocked_reason"])
        if datetime.fromisoformat(plan["expires_at"]) < self.now_fn():
            raise InvalidRequest("计划已过期，请重新生成")
        # the "already running" check and the new run's state file are one step for every process
        # (the desktop page, and autostart from both launchers opened at once)
        with _exclusive(self.base / JOBS_LOCK):
            running = self._running({plan["job_id"]})
            if running:
                raise InvalidRequest(f"同一任务正在运行（{running['run_id']}）")
            run_id = self.now_fn().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
            run_dir = self.base / "runs" / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n",
                                               encoding="utf-8")
            state = {"run_id": run_id, "job_id": plan["job_id"], "plan_id": plan_id, "params": plan["params"],
                     "trigger": trigger, "state": "queued", "progress": 0.0, "step": None,
                     "created_at": self.now_fn().isoformat(),
                     "started_at": None, "finished_at": None,
                     "result": {"datasets": [], "seal": None}, "error": None, "pid": None}
            _write_json(run_dir / "state.json", state)
            try:
                with (run_dir / "log.txt").open("a", encoding="utf-8") as log:
                    proc = subprocess.Popen([self.python, str(REPO / "scripts/collect/job_runner.py"),
                                             "--run-dir", str(run_dir)],
                                            cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, start_new_session=True,
                                            env={**os.environ, "NIUNIU_DATA_ROOT": str(self.data_root)})
            except OSError as error:  # a queued run without a process would block this job for good
                state.update(state="failed", finished_at=self.now_fn().isoformat(),
                             error=f"后台进程没有启动：{type(error).__name__}: {error}"[:500])
                _write_json(run_dir / "state.json", state)
                raise DataProviderError("data_update_jobs", state["error"]) from error
            current = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            if current.get("pid") is None:
                current["pid"] = proc.pid
                _write_json(run_dir / "state.json", current)
        return {"run_id": run_id}

    # Jobs the user has authorised to start by themselves when niuniu opens (2026-09-25).
    AUTOSTART = ("sector_recorder_start",)

    def autostart(self, job_id: str = "sector_recorder_start") -> dict:
        """Start ``job_id`` without a confirmation step when its plan is not blocked.

        Only jobs in ``AUTOSTART`` may be started this way (the user authorised the
        intraday recorder to start whenever niuniu opens).  A blocked plan (non-trading
        day, after the close, already running, sealed, data disk missing) is not an
        error: nothing is started and the reason is returned.
        """
        if job_id not in self.AUTOSTART:
            raise InvalidRequest(f"{job_id} 不允许自动启动")
        today = self.now_fn().date().isoformat()
        earlier = [r for r in self._runs() if r["job_id"] == job_id and str(r.get("created_at", ""))[:10] == today]
        if earlier and earlier[0]["state"] in ("succeeded", "cancelled"):
            reason = ("今天已手动停止过，不再自动启动" if earlier[0]["state"] == "cancelled"
                      else "今天已运行结束，不再自动启动")
            return {"started": False, "job_id": job_id, "reason": reason, "run_id": None}
        plan = self.plan(job_id, {})
        if plan["blocked_reason"]:
            return {"started": False, "job_id": job_id, "reason": plan["blocked_reason"], "run_id": None}
        try:
            run = self.run(plan["plan_id"], trigger="autostart")
        except InvalidRequest as error:  # e.g. the other launcher started it a moment ago
            return {"started": False, "job_id": job_id, "reason": str(error), "run_id": None}
        return {"started": True, "job_id": job_id, "reason": None, "run_id": run["run_id"]}

    def _state_path(self, run_id: str) -> Path:
        if not run_id or "/" in run_id or ".." in run_id:
            raise InvalidRequest("run_id 无效")
        path = self.base / "runs" / run_id / "state.json"
        if not path.is_file():
            raise InvalidRequest(f"找不到运行 {run_id}")
        return path

    def status(self, run_id: str) -> dict:
        path = self._state_path(run_id)
        state = self._refresh(json.loads(path.read_text(encoding="utf-8")), path)
        return {k: v for k, v in state.items() if k not in ("pid",)}

    def log(self, run_id: str, offset: int = 0) -> dict:
        path = self._state_path(run_id).with_name("log.txt")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
        offset = max(0, int(offset or 0))
        chunk = lines[offset:offset + 2000]
        return {"lines": chunk, "next_offset": offset + len(chunk)}

    def cancel(self, run_id: str) -> dict:
        """Stop a queued or running run; returns the state the run actually ended in."""
        path = self._state_path(run_id)
        state = self._refresh(json.loads(path.read_text(encoding="utf-8")), path)
        if state["state"] not in LIVE:
            return {"state": state["state"]}
        signal_runner(path.parent, state)
        for _ in range(20):
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["state"] not in LIVE:
                return {"state": state["state"]}  # the runner wrote how it ended
            if state.get("pid") and not runner_alive(path.parent, state):
                break  # stopped before it could write its own final state
            time.sleep(0.5)
        # a runner still busy checks for cancellation between steps; the request is recorded now
        state.update(state="cancelled", finished_at=self.now_fn().isoformat())
        _write_json(path, state)
        return {"state": "cancelled"}

    def list_runs(self, limit: int = 20) -> dict:
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise InvalidRequest("limit 须为 1–200 的整数")
        return {"runs": [{k: v for k, v in r.items() if k != "pid"} for r in self._runs()[:limit]]}


__all__ = ["DataPreviewService", "DataStatusService", "DataUpdateJobs", "JOBS_SPEC", "RUNNER_LOCK", "pid_alive",
           "refresh_status_index", "runner_alive", "signal_runner"]
