"""DATA Provider: on-demand research lookups for CODE (nothing is persisted).

This is the DATA-owned gateway for the question/answer side of the product.  CODE
calls these methods; it never talks to iwencai, Eastmoney, cninfo or Sina itself.
Which vendor sits behind each method, its URL, headers, key, throttle and field
mapping are DATA's business and may change without CODE changes.

Contract (same for every method):

* returns a :class:`ProviderResult`; ``rows`` is a tuple of plain dicts whose keys
  are documented in ``docs/reference/data-catalog.md`` (section "API");
* ``status == "empty"`` means the vendor answered correctly and has no rows;
* any transport, HTTP, JSON or response-shape problem raises
  :class:`DataProviderError` -- it is never turned into an empty result;
* bad arguments (unknown channel, malformed code, unsupported exchange) raise
  :class:`InvalidRequest`;
* a missing credential raises :class:`ProviderNotConfigured`;
* requests are serial per vendor with a minimum interval (Eastmoney 1.5 s, others
  1 s) so interactive use cannot get the shared egress IP banned;
* results are research context only: not Strict PIT, not a MarketSnapshot, and
  never an authorisation to trade.

    from quantlab.data.research_provider import ResearchDataProvider
    provider = ResearchDataProvider.from_env()
    provider.research_search("宁德时代 储能", channel="report", size=10)
    provider.financial_statements("300750", statement="income", periods=4)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

PROVIDER_VERSION = "research-provider-v1"
CN_TZ = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MIN_INTERVAL = {"eastmoney": 1.5, "cninfo": 1.0, "sina": 1.0, "iwencai": 1.0}
IWENCAI_DEFAULT_BASE = "https://openapi.iwencai.com"
IWENCAI_CHANNELS = ("report", "news", "announcement")
STATEMENTS = {"income": "lrb", "balance": "fzb", "cashflow": "llb"}
REPO_ROOT = Path(__file__).resolve().parents[3]


class DataProviderError(RuntimeError):
    """Technical failure talking to a vendor.  Never means "no data"."""

    def __init__(self, dataset: str, message: str):
        super().__init__(f"{dataset}: {message}")
        self.dataset = dataset


class ProviderNotConfigured(DataProviderError):
    """A credential the method needs is not configured."""


class InvalidRequest(ValueError):
    """The caller asked for something the method does not support."""


@dataclass(frozen=True)
class ProviderResult:
    dataset: str
    source: str
    request: Mapping[str, Any]
    rows: tuple
    fetched_at: str
    total: int | None = None
    truncated: bool = False
    provider_version: str = PROVIDER_VERSION

    @property
    def status(self) -> str:
        return "ok" if self.rows else "empty"

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset, "source": self.source, "status": self.status,
            "request": dict(self.request), "rows": [dict(r) for r in self.rows],
            "total": self.total, "truncated": self.truncated,
            "fetched_at": self.fetched_at, "provider_version": self.provider_version,
        }


# ---------------------------------------------------------------- helpers

@dataclass(frozen=True)
class Security:
    code: str       # six digits
    exchange: str   # SH / SZ / BJ


_CODE = re.compile(r"^(?:(SH|SZ|BJ)[.]?)?(\d{6})(?:[.](SH|SZ|BJ))?$")


def parse_security(value: str) -> Security:
    """Accept ``300750``, ``SZ300750``, ``sz.300750`` or ``300750.SZ`` (A shares only)."""
    text = str(value or "").strip().upper()
    match = _CODE.match(text)
    if not match or (match.group(1) and match.group(3) and match.group(1) != match.group(3)):
        raise InvalidRequest(f"not an A-share code: {value!r}")
    code = match.group(2)
    exchange = match.group(1) or match.group(3) or _infer_exchange(code)
    return Security(code, exchange)


def _infer_exchange(code: str) -> str:
    if code.startswith(("920", "4", "8")):
        return "BJ"
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("0", "2", "3")):
        return "SZ"
    raise InvalidRequest(f"cannot tell the exchange of {code}; pass e.g. {code}.SH")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _float(value) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cn_time(ms) -> str | None:
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _strip_tags(text) -> str:
    return re.sub(r"<[^>]+>", "", str(text or ""))


def _check_range(name: str, value: int, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise InvalidRequest(f"{name} must be an integer in [{low}, {high}], got {value!r}")
    return value


def read_dotenv(path: Path) -> dict:
    """Minimal ``KEY=VALUE`` reader for the git-ignored project ``.env``."""
    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        values[key] = value.strip().strip("'\"")
    return values


class _Throttle:
    def __init__(self, intervals: Mapping[str, float]):
        self._intervals = dict(intervals)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, vendor: str) -> None:
        with self._lock:
            gap = self._intervals.get(vendor, 1.0) - (time.monotonic() - self._last.get(vendor, -1e9))
            if gap > 0:
                time.sleep(gap)
            self._last[vendor] = time.monotonic()


# ---------------------------------------------------------------- provider

@dataclass
class ResearchDataProvider:
    iwencai_key: str = ""
    iwencai_base: str = IWENCAI_DEFAULT_BASE
    timeout: float = 30.0
    session: Any = None
    intervals: Mapping[str, float] = field(default_factory=lambda: dict(MIN_INTERVAL))

    def __post_init__(self):
        if self.session is None:
            import requests
            self.session = requests.Session()
        self._throttle = _Throttle(self.intervals)
        self._cninfo_org: dict[str, str] = {}
        self._cninfo_org_day: str | None = None
        self._org_lock = threading.Lock()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, dotenv: Path | None = None, **kwargs):
        """Read ``IWENCAI_API_KEY`` / ``IWENCAI_BASE_URL`` from the environment; if
        the key is absent, fall back to the project ``.env`` (git-ignored)."""
        env = dict(os.environ if env is None else env)
        if not env.get("IWENCAI_API_KEY"):
            for key, value in read_dotenv(dotenv or REPO_ROOT / ".env").items():
                env.setdefault(key, value)
        return cls(iwencai_key=env.get("IWENCAI_API_KEY", ""),
                   iwencai_base=(env.get("IWENCAI_BASE_URL") or IWENCAI_DEFAULT_BASE).rstrip("/"),
                   **kwargs)

    # -- transport

    def _call(self, dataset: str, vendor: str, method: str, url: str, **kwargs):
        self._throttle.wait(vendor)
        headers = {"User-Agent": UA, **kwargs.pop("headers", {})}
        try:
            response = self.session.request(method, url, headers=headers,
                                            timeout=self.timeout, **kwargs)
        except Exception as exc:  # transport errors from requests or a test double
            raise DataProviderError(dataset, f"{vendor} request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise DataProviderError(dataset, f"{vendor} HTTP {response.status_code}")
        return response

    def _json(self, dataset: str, vendor: str, method: str, url: str, **kwargs) -> dict:
        response = self._call(dataset, vendor, method, url, **kwargs)
        try:
            body = response.json()
        except ValueError as exc:
            raise DataProviderError(dataset, f"{vendor} returned non-JSON") from exc
        if not isinstance(body, dict):
            raise DataProviderError(dataset, f"{vendor} returned {type(body).__name__}, expected object")
        return body

    @staticmethod
    def _result(dataset, source, request, rows, total=None, truncated=False) -> ProviderResult:
        return ProviderResult(dataset=dataset, source=source, request=request, rows=tuple(rows),
                              fetched_at=_now_iso(), total=total, truncated=truncated)

    # -- 1. iwencai semantic search (reports / news / announcements)

    def research_search(self, query: str, channel: str = "report", size: int = 20) -> ProviderResult:
        dataset = "research_search"
        query = str(query or "").strip()
        if not query:
            raise InvalidRequest("query must be non-empty")
        if channel not in IWENCAI_CHANNELS:
            raise InvalidRequest(f"channel must be one of {IWENCAI_CHANNELS}")
        _check_range("size", size, 1, 50)
        if not self.iwencai_key:
            raise ProviderNotConfigured(dataset, "IWENCAI_API_KEY is not set (environment or project .env)")
        headers = {
            "Authorization": f"Bearer {self.iwencai_key}", "Content-Type": "application/json",
            "X-Claw-Call-Type": "normal", "X-Claw-Skill-Id": "report-search",
            "X-Claw-Skill-Version": "2.0.0", "X-Claw-Plugin-Id": "none",
            "X-Claw-Plugin-Version": "none", "X-Claw-Trace-Id": secrets.token_hex(32),
        }
        body = self._json(dataset, "iwencai", "POST", f"{self.iwencai_base}/v1/comprehensive/search",
                          headers=headers,
                          json={"channels": [channel], "app_id": "AIME_SKILL", "query": query, "size": size})
        if body.get("status_code") != 0:
            raise DataProviderError(dataset, f"iwencai status {body.get('status_code')}: "
                                             f"{str(body.get('status_msg', ''))[:120]}")
        items = body.get("data")
        if items is None:
            items = []
        if not isinstance(items, list):
            raise DataProviderError(dataset, "iwencai data is not a list")
        rows = []
        for item in items:
            extra = item.get("extra") or {}
            publish = item.get("publish_date")
            if not publish and isinstance(item.get("publish_time"), (int, float)) and item["publish_time"] > 0:
                publish = datetime.fromtimestamp(item["publish_time"], CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
            rows.append({
                "channel": item.get("channel") or channel,
                "title": _strip_tags(item.get("title")),
                "summary": str(item.get("summary") or ""),
                "url": item.get("url") or None,
                "publish_time": publish or None,
                "source": extra.get("organization") or extra.get("real_publish_source")
                          or extra.get("publish_source") or None,
                "author": extra.get("author") or extra.get("author_name") or None,
                "rating": extra.get("rating") or None,
                "score": _float(item.get("score")),
                "doc_id": item.get("uid") or item.get("id"),
            })
        total = body.get("total") if isinstance(body.get("total"), int) else None
        return self._result(dataset, "iwencai", {"query": query, "channel": channel, "size": size},
                            rows, total=total)

    # -- 2. per-stock sell-side research report list (Eastmoney)

    def stock_research_reports(self, code: str, limit: int = 50) -> ProviderResult:
        dataset = "stock_research_reports"
        sec = parse_security(code)
        _check_range("limit", limit, 1, 500)
        if sec.code.startswith(("43", "83", "87")):
            raise InvalidRequest(f"{sec.code} is a retired BSE code; use the current 920xxx code")
        rows, total, page, pages = [], None, 1, 1
        while len(rows) < limit and page <= pages:
            body = self._json(dataset, "eastmoney", "GET", "https://reportapi.eastmoney.com/report/list",
                              headers={"Referer": "https://data.eastmoney.com/"},
                              params={"industryCode": "*", "pageSize": str(min(limit, 100)), "industry": "*",
                                      "rating": "*", "ratingChange": "*", "beginTime": "2000-01-01",
                                      "endTime": "2099-12-31", "pageNo": str(page), "fields": "",
                                      "qType": "0", "orgCode": "", "code": sec.code, "rcode": ""})
            if "hits" not in body or "data" not in body:
                raise DataProviderError(dataset, "eastmoney report list without hits/data")
            total = body.get("hits")
            pages = int(body.get("TotalPage") or 0)
            for item in body.get("data") or []:
                info = item.get("infoCode")
                rows.append({
                    "publish_date": str(item.get("publishDate") or "")[:10] or None,
                    "title": item.get("title"),
                    "org": item.get("orgSName") or item.get("orgName"),
                    "authors": [str(a).split(".", 1)[-1] for a in item.get("author") or []],
                    "rating": item.get("emRatingName") or None,
                    "last_rating": item.get("lastEmRatingName") or None,
                    "eps_this_year": _float(item.get("predictThisYearEps")),
                    "eps_next_year": _float(item.get("predictNextYearEps")),
                    "eps_next_two_year": _float(item.get("predictNextTwoYearEps")),
                    "pe_this_year": _float(item.get("predictThisYearPe")),
                    "industry": item.get("indvInduName") or None,
                    "info_code": info,
                    "pdf_url": f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf" if info else None,
                })
            page += 1
        truncated = isinstance(total, int) and total > limit
        return self._result(dataset, "eastmoney", {"code": sec.code, "limit": limit},
                            rows[:limit], total=total, truncated=truncated)

    # -- 3. per-stock news (Eastmoney keyword search)

    def stock_news(self, code: str, limit: int = 20) -> ProviderResult:
        dataset = "stock_news"
        sec = parse_security(code)
        _check_range("limit", limit, 1, 100)
        inner = json.dumps({
            "uid": "", "keyword": sec.code, "type": ["cmsArticleWebOld"], "client": "web",
            "clientType": "web", "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default", "pageIndex": 1,
                                           "pageSize": limit, "preTag": "", "postTag": ""}},
        }, separators=(",", ":"), ensure_ascii=False)
        response = self._call(dataset, "eastmoney", "GET", "https://search-api-web.eastmoney.com/search/jsonp",
                              headers={"Referer": "https://so.eastmoney.com/"},
                              params={"cb": "jQuery_news", "param": inner})
        text = response.text
        try:
            body = json.loads(text[text.index("(") + 1: text.rindex(")")])
        except ValueError as exc:
            raise DataProviderError(dataset, "eastmoney news returned an unparseable JSONP body") from exc
        if body.get("code") != 0 or not isinstance(body.get("result"), dict):
            raise DataProviderError(dataset, f"eastmoney news code {body.get('code')}")
        items = body["result"].get("cmsArticleWebOld") or []
        rows = [{
            "publish_time": item.get("date") or None,
            "title": _strip_tags(item.get("title")),
            "snippet": _strip_tags(item.get("content")),
            "media": item.get("mediaName") or None,
            "url": item.get("url") or None,
        } for item in items]
        total = body.get("hitsTotal") if isinstance(body.get("hitsTotal"), int) else None
        return self._result(dataset, "eastmoney", {"code": sec.code, "limit": limit}, rows,
                            total=total, truncated=isinstance(total, int) and total > len(rows))

    # -- 4. per-stock announcements (cninfo)

    def _cninfo_org_id(self, dataset: str, code: str) -> str:
        today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
        with self._org_lock:
            if self._cninfo_org_day != today:
                body = self._json(dataset, "cninfo", "GET", "https://www.cninfo.com.cn/new/data/szse_stock.json")
                stocks = body.get("stockList")
                if not isinstance(stocks, list) or len(stocks) < 1000:
                    raise DataProviderError(dataset, "cninfo security list is missing or too short")
                self._cninfo_org = {s.get("code"): s.get("orgId") for s in stocks if s.get("orgId")}
                self._cninfo_org_day = today
            org = self._cninfo_org.get(code)
        if not org:
            raise InvalidRequest(f"{code} is not in the cninfo security list")
        return org

    def stock_announcements(self, code: str, start: str | None = None, end: str | None = None,
                            limit: int = 30) -> ProviderResult:
        dataset = "stock_announcements"
        sec = parse_security(code)
        _check_range("limit", limit, 1, 300)
        for name, value in (("start", start), ("end", end)):
            if value is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(value)):
                raise InvalidRequest(f"{name} must be YYYY-MM-DD")
        se_date = f"{start or '2000-01-01'}~{end or '2099-12-31'}" if (start or end) else ""
        org = self._cninfo_org_id(dataset, sec.code)
        rows, total, page = [], None, 1
        while len(rows) < limit:
            body = self._json(dataset, "cninfo", "POST", "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                              headers={"Content-Type": "application/x-www-form-urlencoded",
                                       "Referer": "https://www.cninfo.com.cn/new/disclosure",
                                       "Origin": "https://www.cninfo.com.cn"},
                              data={"stock": f"{sec.code},{org}", "tabName": "fulltext", "pageSize": "30",
                                    "pageNum": str(page), "column": "", "category": "", "plate": "",
                                    "seDate": se_date, "searchkey": "", "secid": "", "sortName": "",
                                    "sortType": "", "isHLtitle": "true"})
            if "totalAnnouncement" not in body:
                raise DataProviderError(dataset, "cninfo response without totalAnnouncement")
            total = body.get("totalAnnouncement")
            items = body.get("announcements") or []
            for item in items:
                adjunct = item.get("adjunctUrl")
                stamp = _cn_time(item.get("announcementTime"))
                rows.append({
                    "publish_date": stamp[:10] if stamp else None,
                    "publish_time": stamp,
                    "title": _strip_tags(item.get("announcementTitle")),
                    "announcement_id": item.get("announcementId"),
                    "pdf_url": f"https://static.cninfo.com.cn/{adjunct}" if adjunct else None,
                    "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail?annoId="
                                  f"{item.get('announcementId', '')}",
                })
            if not items or not body.get("hasMore"):
                break
            page += 1
        return self._result(dataset, "cninfo",
                            {"code": sec.code, "start": start, "end": end, "limit": limit},
                            rows[:limit], total=total, truncated=isinstance(total, int) and total > limit)

    # -- 5. financial statements (Sina), long format

    def financial_statements(self, code: str, statement: str = "income", periods: int = 8) -> ProviderResult:
        dataset = "financial_statements"
        sec = parse_security(code)
        if statement not in STATEMENTS:
            raise InvalidRequest(f"statement must be one of {tuple(STATEMENTS)}")
        _check_range("periods", periods, 1, 40)
        body = self._json(dataset, "sina", "GET",
                          "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022",
                          params={"paperCode": f"{sec.exchange.lower()}{sec.code}",
                                  "source": STATEMENTS[statement], "type": "0", "page": "1", "num": str(periods)})
        result = body.get("result")
        if not isinstance(result, dict) or (result.get("status") or {}).get("code") != 0:
            raise DataProviderError(dataset, "sina finance response without status code 0")
        data = result.get("data") or {}
        reports = data.get("report_list") or {}
        if not isinstance(reports, dict):
            raise DataProviderError(dataset, "sina report_list is not an object")
        rows = []
        for period in sorted(reports, reverse=True)[:periods]:
            report = reports[period] or {}
            publish = str(report.get("publish_date") or "")
            for item in report.get("data") or []:
                value = _float(item.get("item_value"))
                if value is None:
                    continue
                rows.append({
                    "report_date": f"{period[:4]}-{period[4:6]}-{period[6:8]}",
                    "publish_date": f"{publish[:4]}-{publish[4:6]}-{publish[6:8]}" if len(publish) == 8 else None,
                    "statement": statement,
                    "report_type": report.get("rType") or None,
                    "audited": report.get("is_audit") or None,
                    "currency": report.get("rCurrency") or None,
                    "item_field": item.get("item_field"),
                    "item_title": item.get("item_title"),
                    "value": value,
                    "yoy": _float(item.get("item_tongbi")),
                })
        count = data.get("report_count")
        total = int(count) if str(count or "").isdigit() else None
        return self._result(dataset, "sina", {"code": sec.code, "statement": statement, "periods": periods},
                            rows, total=total, truncated=isinstance(total, int) and total > periods)

    # -- 6. investor Q&A (cninfo interactive platform, Shenzhen-listed only)

    def investor_qa(self, code: str, limit: int = 30) -> ProviderResult:
        dataset = "investor_qa"
        sec = parse_security(code)
        _check_range("limit", limit, 1, 100)
        if sec.exchange != "SZ":
            raise InvalidRequest("investor_qa covers Shenzhen-listed companies only (cninfo 互动易)")
        first = self._json(dataset, "cninfo", "POST", "https://irm.cninfo.com.cn/newircs/index/queryKeyboardInfo",
                           data={"keyWord": sec.code})
        if first.get("statusCode") != 200 or not isinstance(first.get("data"), list):
            raise DataProviderError(dataset, "cninfo irm lookup without statusCode 200")
        matches = [d for d in first["data"] if d.get("stockCode") == sec.code]
        if not matches:
            raise InvalidRequest(f"{sec.code} is not on cninfo 互动易")
        body = self._json(dataset, "cninfo", "POST", "https://irm.cninfo.com.cn/newircs/company/question",
                          params={"_t": 1, "stockcode": sec.code, "orgId": matches[0].get("secid"),
                                  "pageSize": limit, "pageNum": 1, "keyWord": "", "startDay": "", "endDay": ""})
        if "rows" not in body:
            raise DataProviderError(dataset, "cninfo irm response without rows")
        rows = [{
            "ask_time": _cn_time(item.get("pubDate")),
            "question": item.get("mainContent"),
            "answer": item.get("attachedContent"),
            "answer_time": _cn_time(item.get("attachedPubDate")),
            "answerer": item.get("attachedAuthor"),
            "answered": item.get("attachedContent") not in (None, ""),
        } for item in body.get("rows") or []]
        total = body.get("total") if isinstance(body.get("total"), int) else None
        return self._result(dataset, "cninfo", {"code": sec.code, "limit": limit}, rows,
                            total=total, truncated=isinstance(total, int) and total > len(rows))

    # -- 7. daily fund flow by order size (Eastmoney)

    def stock_fund_flow_daily(self, code: str, days: int = 120) -> ProviderResult:
        dataset = "stock_fund_flow_daily"
        sec = parse_security(code)
        _check_range("days", days, 1, 120)
        market = "1" if sec.exchange == "SH" else "0"
        body = self._json(dataset, "eastmoney", "GET", "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                          headers={"Referer": "https://quote.eastmoney.com/"},
                          params={"secid": f"{market}.{sec.code}", "fields1": "f1,f2,f3,f7",
                                  "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
                                  "lmt": str(days)})
        if body.get("rc") != 0 or not isinstance(body.get("data"), dict):
            raise InvalidRequest(f"eastmoney has no fund-flow series for {sec.code}.{sec.exchange} (rc={body.get('rc')})")
        rows = []
        for line in body["data"].get("klines") or []:
            parts = str(line).split(",")
            if len(parts) < 13:
                raise DataProviderError(dataset, "eastmoney fund-flow line has fewer than 13 fields")
            rows.append({
                "date": parts[0],
                "main_net": _float(parts[1]), "small_net": _float(parts[2]), "mid_net": _float(parts[3]),
                "large_net": _float(parts[4]), "super_net": _float(parts[5]),
                "main_pct": _float(parts[6]), "small_pct": _float(parts[7]), "mid_pct": _float(parts[8]),
                "large_pct": _float(parts[9]), "super_pct": _float(parts[10]),
                "close": _float(parts[11]), "pct_change": _float(parts[12]),
            })
        return self._result(dataset, "eastmoney", {"code": sec.code, "days": days}, rows)


__all__ = [
    "DataProviderError", "InvalidRequest", "ProviderNotConfigured", "ProviderResult",
    "ResearchDataProvider", "Security", "parse_security", "read_dotenv",
]
