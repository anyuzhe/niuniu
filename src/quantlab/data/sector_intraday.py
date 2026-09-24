"""DATA Provider: intraday THS sector boards and their constituents (for CODE).

Two read-only calls, both backed by Fuyao (THS concept / industry indices):

* ``board_snapshot(types)``  every board of the requested types with its quote;
* ``board_members(code)``    one board's current constituents with quotes, limit-up /
  limit-down / broken-limit status and a public-web cross-check.

Refresh contract: CODE may call as often as it likes.  A call inside the minimum
interval (boards 10 s, members 5 s) returns the cached result with ``cache.hit`` and
``age_seconds``; the vendor is not asked again.  A failed refresh falls back to the
last good result marked ``stale=True`` (or raises ``DataProviderError`` when there
is none).  Results are research context: not Strict PIT, not a MarketSnapshot, no
trading authorisation.  Membership is the vendor's *current* membership.

Every snapshot is also appended to an in-process sample series so a page can draw
the session's intraday line (``board_series``); nothing is persisted here -- the
separate recorder script persists one-minute samples.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from quantlab.data.research_provider import DataProviderError, InvalidRequest

PROVIDER_VERSION = "sector-intraday-v1"
TZ = ZoneInfo("Asia/Shanghai")
BOARD_TYPES = {"concept": "cn_concept", "industry": "industry"}
MIN_INTERVAL_BOARDS = 10.0
MIN_INTERVAL_MEMBERS = 5.0
CROSS_CHECK_INTERVAL = 30.0
FUYAO_BATCH = 300
PUBLIC_BATCH = 150
CROSS_CHECK_MAX = 300      # symbols re-checked against public quotes per members call
SERIES_MAX = 3000          # samples kept per board in memory (~8 h at 10 s)
DEFAULT_DATA_ROOT = "/Volumes/Lexar/niuniu-data"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _positive(value):
    number = _float(value)
    return number if number is not None and number > 0 else None


def _round_price(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def niuniu_symbol(thscode: str) -> str:
    code, _, exchange = str(thscode).upper().partition(".")
    if exchange not in ("SH", "SZ", "BJ") or len(code) != 6 or not code.isdigit():
        return ""
    return exchange.lower() + "." + code


def market_status(now: datetime, trading_day: bool) -> str:
    """PREOPEN / OPENING_AUCTION / TRADING / MIDDAY_BREAK / CLOSING_AUCTION / CLOSED / NON_TRADING_DAY."""
    if not trading_day:
        return "NON_TRADING_DAY"
    hm = now.astimezone(TZ).strftime("%H:%M")
    if hm < "09:15":
        return "PREOPEN"
    if hm < "09:30":
        return "OPENING_AUCTION"
    if hm < "11:30":
        return "TRADING"
    if hm < "13:00":
        return "MIDDAY_BREAK"
    if hm < "14:57":
        return "TRADING"
    if hm < "15:00":
        return "CLOSING_AUCTION"
    return "CLOSED"


def limit_ratio(symbol: str, name: str) -> float:
    """Daily price-limit ratio by board; ST on the main board is 5 %."""
    code = symbol.split(".")[-1]
    if symbol.startswith("bj."):
        return 0.30
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if "ST" in str(name).upper().replace(" ", ""):
        return 0.05
    return 0.10


def limit_prices(symbol: str, name: str, previous_close: float) -> tuple[float, float]:
    ratio = limit_ratio(symbol, name)
    return _round_price(previous_close * (1 + ratio)), _round_price(previous_close * (1 - ratio))


# ------------------------------------------------------------------ board classification
# DATA-owned rule for concept boards that are market-wide labels rather than themes.
# Each entry: (reason, exact names, name prefixes, name regex).
import re as _re
_MARKET_LABELS = (
    ("trading_access", {"融资融券", "沪股通", "深股通"}, (), None),
    ("holder_label", {"证金持股", "国家大基金持股"}, (), None),
    ("index_selection", {"高股息精选", "中国AI50"}, ("同花顺",), None),
    ("status_label", {"ST板块", "摘帽"}, (), None),
    ("listing_age", {"新股与次新股", "注册制次新股", "科创次新股"}, (), None),
    ("earnings_label", set(), (), _re.compile(r"^20\d{2}(一季报|中报|三季报|年报)(预增|预减|扭亏|预盈|预亏)$")),
)
BOARD_CLASS_VERSION = "board-class-v1"


def classify_board(name: str, kind: str) -> tuple[str, str | None]:
    """``(board_class, label_reason)``: ``industry`` / ``theme`` / ``market_label``."""
    if kind == "industry":
        return "industry", None
    text = str(name or "").strip()
    for reason, names, prefixes, pattern in _MARKET_LABELS:
        if text in names or text.startswith(prefixes) or (pattern is not None and pattern.match(text)):
            return "market_label", reason
    return "theme", None


def load_constituent_counts(data_root: Path) -> tuple[str | None, dict[str, int]]:
    """Counts from the latest complete daily constituents file (``sector_constituents.py``)."""
    base = data_root / "lake/bronze/provider=fuyao/sector_board_constituents"
    try:
        files = sorted(p for p in base.glob("date=*.parquet") if not p.name.startswith("._"))
    except OSError:
        files = []
    if not files:
        return None, {}
    latest = files[-1]
    try:
        import pandas as pd
        frame = pd.read_parquet(latest, columns=["board_code", "symbol"])
    except Exception:
        return None, {}
    counts = frame.groupby("board_code")["symbol"].nunique().to_dict()
    return latest.stem.split("=", 1)[1], {str(k): int(v) for k, v in counts.items()}


class _Reference:
    """Listing dates and the trading calendar from DATA's latest reference snapshot."""

    def __init__(self, data_root: Path):
        self.data_root = data_root
        self._loaded = False
        self.ipo: dict[str, str] = {}
        self.calendar: list[str] = []

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        base = self.data_root / "lake/bronze/provider=baostock/reference_snapshots"
        try:
            snapshots = sorted(p for p in base.glob("snapshot=*") if p.is_dir())
        except OSError:
            snapshots = []
        if not snapshots:
            return
        latest = snapshots[-1]
        try:
            import pandas as pd
            basic = pd.read_parquet(latest / "stock_basic.parquet", columns=["code", "ipoDate"])
            self.ipo = {str(c).lower(): str(d)[:10] for c, d in zip(basic["code"], basic["ipoDate"]) if d}
            cal = pd.read_parquet(latest / "trade_calendar.parquet")
            mask = cal["is_trading_day"].astype(str).isin({"1", "1.0", "True", "true"})
            self.calendar = sorted(str(v)[:10] for v in cal.loc[mask, "calendar_date"])
        except Exception:  # reference is an enrichment; missing files leave it empty
            self.ipo, self.calendar = {}, []

    def no_limit_new_listing(self, symbol: str, today: str) -> bool | None:
        """True inside the first five trading days (no price limit); None when unknown."""
        self.load()
        ipo = self.ipo.get(symbol)
        if not ipo:
            # Baostock's list has no BSE stocks; BSE limits apply from day 2, so treat as limited.
            return False if symbol.startswith("bj.") else None
        if not self.calendar:
            return None
        count = sum(1 for d in self.calendar if ipo <= d <= today)
        if today > self.calendar[-1]:
            day = date.fromisoformat(self.calendar[-1]) + timedelta(days=1)
            while day.isoformat() <= today:
                count += day.weekday() < 5
                day += timedelta(days=1)
        return count <= 5


class SectorIntradayProvider:
    def __init__(self, client=None, *, public_loaders=None, now_fn: Callable[[], datetime] | None = None,
                 data_root: str | Path | None = None, min_interval_boards: float = MIN_INTERVAL_BOARDS,
                 min_interval_members: float = MIN_INTERVAL_MEMBERS,
                 cross_check_interval: float = CROSS_CHECK_INTERVAL, sleep=time.sleep):
        if client is None:
            from quantlab.agent.fuyao_mcp import FuyaoMCPClient
            client = FuyaoMCPClient()
        self.client = client
        if public_loaders is None:
            from quantlab.trading.public_web_market_snapshot import _http, _sina, _tencent
            public_loaders = {"tencent": lambda s: _tencent(s, _http)[0], "sina": lambda s: _sina(s, _http)[0]}
        self.public_loaders = public_loaders
        self.now_fn = now_fn or _now_utc
        self.sleep = sleep
        self.min_interval_boards = min_interval_boards
        self.min_interval_members = min_interval_members
        self.cross_check_interval = cross_check_interval
        root = data_root or os.environ.get("NIUNIU_DATA_ROOT") or DEFAULT_DATA_ROOT
        self.data_root = Path(root)
        self.reference = _Reference(self.data_root)
        self._counts: tuple[float, str | None, dict[str, int]] | None = None
        self._lock = threading.RLock()
        self._catalog: dict[str, tuple[str, list[dict]]] = {}
        self._calendar: tuple[str, set[str]] | None = None
        self._members_cache: dict[str, tuple[float, list[dict]]] = {}
        self._board_cache: dict[tuple, tuple[float, dict]] = {}
        self._member_quote_cache: dict[str, tuple[float, dict]] = {}
        self._pools: tuple[float, dict] | None = None
        self._checks: dict[str, tuple[float, dict]] = {}
        self._series: dict[str, list[dict]] = {}

    # ---------------------------------------------------------------- helpers

    def _now(self) -> datetime:
        value = self.now_fn()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("now_fn must return an aware datetime")
        return value

    def _call(self, dataset: str, service: str, tool: str, args: dict) -> dict:
        last = None
        for attempt in range(2):
            try:
                return self.client.call(service, tool, args)
            except Exception as error:  # FuyaoMCPError or transport error
                last = error
                if getattr(error, "code", "") in ("FUYAO_NOT_CONFIGURED", "FUYAO_TOOL_REJECTED",
                                                  "FUYAO_INVALID_ARGUMENT"):
                    break
                if attempt == 0:
                    self.sleep(1.0)
        code = getattr(last, "code", type(last).__name__)
        raise DataProviderError(dataset, f"fuyao {tool} failed: {code}")

    @staticmethod
    def _items(call: dict) -> list[dict]:
        rows = (call.get("data") or {}).get("item", [])
        return rows if isinstance(rows, list) else []

    def _trading_day(self, dataset: str, today: str) -> bool:
        if self._calendar is None or self._calendar[0] != today:
            call = self._call(dataset, "a-share", "get_a_share_calendar_trading_days", {})
            days = {str(row.get("date", "")) for row in self._items(call)}
            if not days:
                raise DataProviderError(dataset, "fuyao trading calendar is empty")
            self._calendar = (today, days)
        return today.replace("-", "") in self._calendar[1]

    def _catalog_rows(self, dataset: str, kind: str, today: str) -> list[dict]:
        cached = self._catalog.get(kind)
        if cached and cached[0] == today:
            return cached[1]
        call = self._call(dataset, "a-share-index", "get_a_share_index_catalog_ths_index_list",
                          {"tag": BOARD_TYPES[kind]})
        rows = [r for r in self._items(call) if str(r.get("thscode", "")).upper().endswith(".TI")]
        if not rows:
            raise DataProviderError(dataset, f"fuyao returned no {kind} boards")
        self._catalog[kind] = (today, rows)
        return rows

    @staticmethod
    def _stamp(call: dict) -> str | None:
        try:
            return datetime.fromtimestamp(int(call.get("response_timestamp")) / 1000, TZ).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    def _envelope(self, dataset: str, now: datetime, trading: bool, as_of: str | None, request: dict) -> dict:
        age = None
        if as_of:
            age = max(0.0, (now - datetime.fromisoformat(as_of)).total_seconds())
        return {"dataset": dataset, "provider_version": PROVIDER_VERSION, "source": "fuyao (THS indices)",
                "request": request, "as_of": as_of, "fetched_at": now.astimezone(timezone.utc).isoformat(),
                "age_seconds": age, "market_status": market_status(now, trading),
                "strict_pit": False, "membership_is_current_not_historical": True}

    def _cached(self, store: dict, key, interval: float, now_mono: float):
        entry = store.get(key)
        if entry and now_mono - entry[0] < interval:
            value = dict(entry[1])
            value["cache"] = {"hit": True, "age_seconds": round(now_mono - entry[0], 3)}
            return value
        return None

    def _stale(self, store: dict, key, now_mono: float, error: Exception):
        entry = store.get(key)
        if not entry:
            raise error
        value = dict(entry[1])
        value["stale"] = True
        value["stale_reason"] = str(error)[:200]
        value["cache"] = {"hit": True, "age_seconds": round(now_mono - entry[0], 3)}
        return value

    def _constituent_counts(self, mono: float) -> tuple[str | None, dict[str, int]]:
        if self._counts is None or mono - self._counts[0] > 600:
            day, counts = load_constituent_counts(self.data_root)
            self._counts = (mono, day, counts)
        return self._counts[1], self._counts[2]

    # ---------------------------------------------------------------- 1. boards

    def board_snapshot(self, types=("concept", "industry")) -> dict:
        dataset = "sector_board_snapshot"
        if isinstance(types, str):
            types = (types,)
        types = tuple(dict.fromkeys(types))
        if not types or any(t not in BOARD_TYPES for t in types):
            raise InvalidRequest(f"types must be a subset of {tuple(BOARD_TYPES)}")
        key = tuple(sorted(types))
        with self._lock:
            mono = time.monotonic()
            hit = self._cached(self._board_cache, key, self.min_interval_boards, mono)
            if hit:
                return hit
            try:
                value = self._fetch_boards(dataset, types)
            except (DataProviderError, InvalidRequest) as error:
                return self._stale(self._board_cache, key, mono, error)
            self._board_cache[key] = (mono, value)
            self._sample(value)
            return {**value, "cache": {"hit": False, "age_seconds": 0.0}}

    def _fetch_boards(self, dataset: str, types) -> dict:
        now = self._now()
        today = now.astimezone(TZ).date().isoformat()
        trading = self._trading_day(dataset, today)
        catalog = {}
        for kind in types:
            for row in self._catalog_rows(dataset, kind, today):
                catalog.setdefault(str(row["thscode"]).upper(), (kind, str(row.get("name") or "")))
        codes = list(catalog)
        quotes, stamps = {}, []
        for index in range(0, len(codes), FUYAO_BATCH):
            call = self._call(dataset, "a-share-index", "get_a_share_index_prices_snapshot",
                              {"thscodes": ",".join(codes[index:index + FUYAO_BATCH])})
            stamp = self._stamp(call)
            if stamp:
                stamps.append(stamp)
            for row in self._items(call):
                quotes[str(row.get("thscode", "")).upper()] = (row, stamp)
        counts_day, counts = self._constituent_counts(time.monotonic())
        boards, missing = [], []
        for code in codes:
            kind, name = catalog[code]
            board_class, label_reason = classify_board(name, kind)
            if code not in quotes:
                missing.append({"code": code, "name": name, "type": kind, "reason": "no_quote_returned"})
                continue
            row, stamp = quotes[code]
            last = _positive(row.get("last_price"))
            if last is None:
                missing.append({"code": code, "name": name, "type": kind, "reason": "no_price"})
                continue
            boards.append({
                "code": code, "name": name, "type": kind, "last": last,
                "change": _float(row.get("price_change")), "change_pct": _float(row.get("price_change_ratio_pct")),
                "amount": _float(row.get("turnover")), "volume": _float(row.get("volume")),
                "previous_close": _positive(row.get("prev_price")), "open": _positive(row.get("open_price")),
                "high": _positive(row.get("high_price")), "low": _positive(row.get("low_price")),
                "as_of": stamp, "constituent_count": counts.get(code),
                "board_class": board_class, "label_reason": label_reason})
        boards.sort(key=lambda b: (b["change_pct"] is None, -(b["change_pct"] or 0)))
        as_of = min(stamps) if stamps else None
        return {**self._envelope(dataset, now, trading, as_of, {"types": list(types)}),
                "completeness": "FULL" if not missing else "PARTIAL", "boards": boards, "missing": missing,
                "counts": {"requested": len(codes), "returned": len(boards)},
                "cross_check": "none: THS board indices have a single source (Fuyao)",
                "constituent_counts_date": counts_day, "board_class_version": BOARD_CLASS_VERSION,
                "units": {"amount": "yuan", "volume": "shares (vendor value)", "change_pct": "percent"}}

    def _sample(self, value: dict) -> None:
        for board in value.get("boards", []):
            series = self._series.setdefault(board["code"], [])
            point = {"as_of": board["as_of"], "last": board["last"], "change_pct": board["change_pct"],
                     "amount": board["amount"]}
            if not series or series[-1]["as_of"] != point["as_of"]:
                series.append(point)
                if len(series) > SERIES_MAX:
                    del series[:len(series) - SERIES_MAX]

    def board_series(self, code: str) -> dict:
        """Samples collected by this process today (one per non-cached board_snapshot call)."""
        code = str(code).upper()
        with self._lock:
            now = self._now()
            today = now.astimezone(TZ).date().isoformat()
            points = [p for p in self._series.get(code, []) if p["as_of"] and p["as_of"][:10] == today]
        return {"dataset": "sector_board_series", "code": code, "points": points,
                "sampling": "in-process samples of board_snapshot (>=10 s apart); not vendor minute bars",
                "provider_version": PROVIDER_VERSION}

    # ---------------------------------------------------------------- 2. members

    def board_members(self, code: str) -> dict:
        dataset = "sector_board_members"
        code = str(code or "").strip().upper()
        if not code.endswith(".TI") or not code[:-3].isdigit():
            raise InvalidRequest("board code must look like 885431.TI (from sector_board_snapshot)")
        with self._lock:
            mono = time.monotonic()
            hit = self._cached(self._member_quote_cache, code, self.min_interval_members, mono)
            if hit:
                return hit
            try:
                value = self._fetch_members(dataset, code, mono)
            except (DataProviderError, InvalidRequest) as error:
                return self._stale(self._member_quote_cache, code, mono, error)
            self._member_quote_cache[code] = (mono, value)
            return {**value, "cache": {"hit": False, "age_seconds": 0.0}}

    def _constituents(self, dataset: str, code: str, mono: float) -> list[dict]:
        cached = self._members_cache.get(code)
        if cached and mono - cached[0] < 1800:
            return cached[1]
        call = self._call(dataset, "a-share-index", "get_a_share_index_constituents_ths_stock_list",
                          {"thscode": code})
        rows = [r for r in self._items(call) if niuniu_symbol(r.get("thscode"))]
        if not rows:
            raise InvalidRequest(f"{code} has no constituents at Fuyao")
        self._members_cache[code] = (mono, rows)
        return rows

    def _limit_pools(self, dataset: str, now: datetime, mono: float) -> dict:
        if self._pools and mono - self._pools[0] < self.cross_check_interval:
            return self._pools[1]
        day = now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        ms = int(day.timestamp() * 1000)
        pools = {}
        for key, tool, sort in (("limit_up", "get_a_share_special_data_limit_up_pool", "limit_up_time"),
                                ("limit_down", "get_a_share_special_data_limit_down_pool", "last_limit_time"),
                                ("limit_break", "get_a_share_special_data_limit_break_pool", "price_change_ratio_pct")):
            rows, page = [], 1
            while page <= 10:
                call = self._call(dataset, "a-share", tool, {"date_ms": ms, "page": page, "size": 200,
                                                             "sort_field": sort, "sort_dir": "desc"})
                batch = self._items(call)
                rows.extend(batch)
                pagination = (call.get("data") or {}).get("pagination") or {}
                if page >= int(pagination.get("pages") or 1) or not batch:
                    break
                page += 1
            pools[key] = {niuniu_symbol(r.get("thscode")): r for r in rows}
        self._pools = (mono, pools)
        return pools

    def _public_check(self, symbols: list[str], mono: float) -> dict[str, dict]:
        """Tencent + Sina (both batch endpoints) at most every CROSS_CHECK_INTERVAL seconds."""
        due = [s for s in symbols if s not in self._checks or mono - self._checks[s][0] >= self.cross_check_interval]
        # Bound the extra latency of one refresh: check the oldest-checked CROSS_CHECK_MAX symbols per call,
        # so a 1,000-stock board is fully re-checked over a few refreshes instead of stalling one.
        due.sort(key=lambda s: self._checks.get(s, (-1.0,))[0])
        due = due[:CROSS_CHECK_MAX]
        if due:
            quotes: dict[str, dict[str, dict]] = {}
            for name, loader in self.public_loaders.items():
                for index in range(0, len(due), PUBLIC_BATCH):
                    try:
                        for symbol, row in loader(due[index:index + PUBLIC_BATCH]).items():
                            quotes.setdefault(symbol, {})[name] = row
                    except Exception:
                        continue
            for symbol in due:
                self._checks[symbol] = (mono, quotes.get(symbol, {}))
        return {s: self._checks[s][1] for s in symbols if s in self._checks}

    @staticmethod
    def _agrees(a, b) -> bool:
        if a is None or b is None:
            return False
        return abs(a - b) <= max(0.011, min(0.03, abs(a) * 0.0002))

    def _fetch_members(self, dataset: str, code: str, mono: float) -> dict:
        now = self._now()
        today = now.astimezone(TZ).date().isoformat()
        trading = self._trading_day(dataset, today)
        members = self._constituents(dataset, code, mono)
        names = {niuniu_symbol(r["thscode"]): str(r.get("name") or "") for r in members}
        thscodes = [str(r["thscode"]).upper() for r in members]
        quotes, stamps = {}, []
        for index in range(0, len(thscodes), FUYAO_BATCH):
            call = self._call(dataset, "a-share", "get_a_share_prices_snapshot",
                              {"thscodes": ",".join(thscodes[index:index + FUYAO_BATCH])})
            stamp = self._stamp(call)
            if stamp:
                stamps.append(stamp)
            for row in self._items(call):
                quotes[niuniu_symbol(row.get("thscode"))] = (row, stamp)
        pools = self._limit_pools(dataset, now, mono) if trading else {"limit_up": {}, "limit_down": {}, "limit_break": {}}
        symbols = list(names)
        checks = self._public_check(symbols, mono)
        rows, missing = [], []
        for symbol in symbols:
            name = names[symbol]
            if symbol not in quotes:
                missing.append({"symbol": symbol, "name": name, "reason": "no_quote_returned"})
                continue
            quote, stamp = quotes[symbol]
            last = _positive(quote.get("last_price"))
            prev = _positive(quote.get("prev_price"))
            volume = _float(quote.get("volume"))
            row = {"symbol": symbol, "name": name, "last": last, "change_pct": _float(quote.get("price_change_ratio_pct")),
                   "amount": _float(quote.get("turnover")), "volume": volume, "previous_close": prev,
                   "open": _positive(quote.get("open_price")), "high": _positive(quote.get("high_price")),
                   "low": _positive(quote.get("low_price")), "as_of": stamp, "status": "trading",
                   "limit_status": None, "limit_up_price": None, "limit_down_price": None, "limit_check": None,
                   "cross_check": "unchecked"}
            if last is None or not volume:
                row.update(status="no_trade_today", last=None, change_pct=None)
            # price limits
            new_listing = self.reference.no_limit_new_listing(symbol, today)
            if prev and new_listing is False:
                up, down = limit_prices(symbol, name, prev)
                row.update(limit_up_price=up, limit_down_price=down)
                computed = None
                if last is not None:
                    if last >= up - 0.001:
                        computed = "limit_up"
                    elif last <= down + 0.001:
                        computed = "limit_down"
                    elif row["high"] is not None and row["high"] >= up - 0.001:
                        computed = "limit_break"
                vendor = next((k for k in ("limit_up", "limit_down", "limit_break") if symbol in pools.get(k, {})), None)
                row["limit_status"] = computed or vendor
                row["limit_check"] = ("agree" if computed == vendor else
                                      "computed_only" if computed and not vendor else
                                      "vendor_only" if vendor and not computed else "differs")
                if computed is None and vendor is None:
                    row["limit_check"] = None
            elif new_listing:
                row["limit_status"] = "no_limit_new_listing"
            else:
                row["limit_check"] = "listing_date_unknown"
            # public cross-check (same moment only when the check was refreshed in this call)
            sources = checks.get(symbol) or {}
            agreeing = [n for n, q in sources.items()
                        if self._agrees(q.get("last"), last) and self._agrees(q.get("previous_close"), prev)]
            if row["status"] == "no_trade_today":
                row["cross_check"] = "not_applicable"
            elif len(agreeing) >= 1 and self._checks.get(symbol, (0,))[0] == mono:
                row["cross_check"] = "agree:" + "+".join(sorted(agreeing))
            elif sources and self._checks.get(symbol, (0,))[0] == mono:
                row.update(cross_check="mismatch", status="withheld_source_mismatch", last=None, change_pct=None,
                           public={n: {"last": q.get("last"), "previous_close": q.get("previous_close")}
                                   for n, q in sources.items()})
            elif sources:
                row["cross_check"] = "checked_" + str(round(mono - self._checks[symbol][0])) + "s_ago"
            rows.append(row)
        rows.sort(key=lambda r: (r["change_pct"] is None, -(r["change_pct"] or 0)))
        as_of = min(stamps) if stamps else None
        withheld = sum(1 for r in rows if r["status"] == "withheld_source_mismatch")
        return {**self._envelope(dataset, now, trading, as_of, {"code": code}),
                "completeness": "FULL" if not missing and not withheld else "PARTIAL",
                "members": rows, "missing": missing,
                "counts": {"constituents": len(symbols), "quoted": len(rows) - withheld, "withheld": withheld,
                           "limit_up": sum(r["limit_status"] == "limit_up" for r in rows),
                           "limit_down": sum(r["limit_status"] == "limit_down" for r in rows),
                           "limit_break": sum(r["limit_status"] == "limit_break" for r in rows)},
                "units": {"amount": "yuan", "volume": "shares", "change_pct": "percent", "symbol": "sh.600000"},
                "rules": {"limit_ratio": "main 10%, main-board ST 5%, ChiNext/STAR 20%, BSE 30%, "
                                         "no limit in the first 5 trading days after listing",
                          "cross_check": f"Tencent+Sina, each stock at most every {self.cross_check_interval:.0f}s and "
                                         f"at most {CROSS_CHECK_MAX} stocks per call; a price that disagrees at "
                                         "check time is withheld"}}


__all__ = ["SectorIntradayProvider", "classify_board", "load_constituent_counts", "limit_prices", "limit_ratio", "market_status", "niuniu_symbol",
           "MIN_INTERVAL_BOARDS", "MIN_INTERVAL_MEMBERS"]
