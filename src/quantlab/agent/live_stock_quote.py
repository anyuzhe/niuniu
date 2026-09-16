"""Turn-scoped read-only live quotes for explicitly named A-share questions.

This service is intentionally separate from MarketSnapshotStore.  A user naming a
stock in a chat turn authorizes one bounded quote lookup for those explicit
symbols only; the result is conversation evidence, not a frozen trading input.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import re

import polars as pl

from quantlab.trading.decision import SYMBOL
from quantlab.trading.public_web_market_snapshot import PublicWebConsensusProvider

TZ = ZoneInfo("Asia/Shanghai")
FORMAT = "niuniu-ad-hoc-live-stock-quote-v1"
MAX_EXPLICIT_SYMBOLS = 10
_STOCK_BASIC = Path("lake/bronze/provider=baostock/stock_basic/stock_basic.parquet")
_PREFIXED = re.compile(r"(?i)(sh|sz|bj)[.\s_-]?(\d{6})")
_BARE_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_CONTEXT_REFERENCE = re.compile(r"这只股票|这只股|该股|它现在|它的|现在呢|走势呢|价格呢|能买吗|能不能买|要不要卖")


def _inferred_symbol(code: str) -> str | None:
    if code.startswith(("60", "68", "51", "52", "56", "58")):
        value = "sh." + code
    elif code.startswith(("00", "01", "02", "03", "12", "15", "16", "18", "30")):
        value = "sz." + code
    elif code.startswith(("43", "82", "83", "87", "88", "89", "92")):
        value = "bj." + code
    else:
        return None
    return value if SYMBOL.fullmatch(value) else None


def _market_status(now: datetime, session: str, age_seconds: float | None) -> str:
    if session != now.date().isoformat():
        return "LAST_AVAILABLE_SESSION"
    clock = now.time()
    if clock < datetime.strptime("09:15", "%H:%M").time():
        status = "PREOPEN"
    elif clock < datetime.strptime("09:30", "%H:%M").time():
        status = "OPENING_AUCTION"
    elif clock < datetime.strptime("11:30", "%H:%M").time():
        status = "TRADING"
    elif clock < datetime.strptime("13:00", "%H:%M").time():
        status = "MIDDAY_BREAK"
    elif clock < datetime.strptime("15:00", "%H:%M").time():
        status = "TRADING"
    else:
        status = "CLOSED"
    if status == "TRADING" and (age_seconds is None or age_seconds > 180):
        return "STALE_OR_SUSPENDED"
    return status


def _frame(now: datetime) -> str:
    clock = now.time()
    if clock < datetime.strptime("09:30", "%H:%M").time():
        return "AUCTION"
    if clock < datetime.strptime("11:30", "%H:%M").time():
        return "R1"
    if clock < datetime.strptime("15:00", "%H:%M").time():
        return "R2"
    return "R3"


def _session_candidates(now: datetime) -> list[str]:
    values: list[str] = []
    for offset in range(8):
        day = (now - timedelta(days=offset)).date()
        if day.weekday() < 5:
            values.append(day.isoformat())
    return values


class LiveStockQuoteService:
    """Resolve explicit user symbols and perform one bounded, non-persistent lookup."""

    def __init__(self, data_root=None, *, provider=None, now_fn=None):
        self.data_root = Path(data_root).resolve() if data_root else None
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.provider = provider or PublicWebConsensusProvider(now_fn=self.now_fn)
        self._reference: tuple[dict[str, str], list[tuple[str, str]]] | None = None

    def _reference_data(self) -> tuple[dict[str, str], list[tuple[str, str]]]:
        if self._reference is not None:
            return self._reference
        code_map: dict[str, str] = {}
        names: list[tuple[str, str]] = []
        path = self.data_root / _STOCK_BASIC if self.data_root else None
        if path and path.is_file() and not path.is_symlink():
            try:
                frame = pl.read_parquet(path, columns=["code", "code_name", "outDate", "status"])
                if frame.height <= 20_000:
                    rows = sorted(frame.to_dicts(), key=lambda row: (bool(row.get("outDate")), str(row.get("code"))))
                    seen_names: set[tuple[str, str]] = set()
                    for row in rows:
                        symbol = str(row.get("code") or "").lower()
                        code = symbol.split(".")[-1]
                        name = str(row.get("code_name") or "").strip()
                        if SYMBOL.fullmatch(symbol):
                            code_map.setdefault(code, symbol)
                            if len(name) >= 2 and (name, symbol) not in seen_names:
                                names.append((name, symbol));seen_names.add((name, symbol))
            except (OSError, ValueError, TypeError, pl.exceptions.PolarsError):
                pass
        names.sort(key=lambda item: (-len(item[0]), item[0], item[1]))
        self._reference = code_map, names
        return self._reference

    def resolve(self, text: str) -> list[str]:
        if not isinstance(text, str) or not text.strip():
            return []
        code_map, names = self._reference_data()
        found: list[tuple[int, str]] = []
        occupied: list[tuple[int, int]] = []
        for match in _PREFIXED.finditer(text):
            symbol = match.group(1).lower() + "." + match.group(2)
            if SYMBOL.fullmatch(symbol):
                found.append((match.start(), symbol));occupied.append(match.span())
        for match in _BARE_CODE.finditer(text):
            if any(start <= match.start() < end for start, end in occupied):
                continue
            code = match.group(1);symbol = code_map.get(code) or _inferred_symbol(code)
            if symbol:
                found.append((match.start(), symbol))
        for name, symbol in names:
            start = text.find(name)
            if start >= 0:
                found.append((start, symbol))
        result: list[str] = []
        for _, symbol in sorted(found, key=lambda item: item[0]):
            if symbol not in result:
                result.append(symbol)
        return result

    def query(self, text: str, *, context_texts=()):
        symbols = self.resolve(text)
        query_mode = "EXPLICIT_USER_STOCK_QUESTION_READ_ONLY"
        ambiguous = []
        if not symbols and _CONTEXT_REFERENCE.search(text):
            for prior in context_texts:
                prior_symbols = self.resolve(prior)
                if len(prior_symbols) == 1:
                    symbols = prior_symbols;query_mode = "CONTEXTUAL_USER_STOCK_FOLLOWUP_READ_ONLY";break
                if len(prior_symbols) > 1:
                    ambiguous = prior_symbols;break
        if not symbols and not ambiguous:
            return None
        now = self.now_fn()
        if not isinstance(now, datetime) or now.tzinfo is None:
            now = datetime.now(timezone.utc)
        now = now.astimezone(TZ)
        base = {
            "format": FORMAT,
            "query_mode": query_mode,
            "requested_at": now.isoformat(),
            "requested_symbols": (symbols or ambiguous)[:MAX_EXPLICIT_SYMBOLS],
            "stored_as_market_snapshot": False,
            "creates_decision": False,
            "strict_pit_source_verified": False,
        }
        if ambiguous:
            return {**base, "status": "AMBIGUOUS_REFERENCE",
                "message": "上一轮同时涉及多只股票，无法判断本轮指代；未执行联网查询。"}
        if len(symbols) > MAX_EXPLICIT_SYMBOLS:
            return {**base, "status": "SCOPE_TOO_LARGE", "requested_symbol_count": len(symbols),
                "message": f"单轮明确股票超过 {MAX_EXPLICIT_SYMBOLS} 只，未执行联网查询。"}
        attempts = []
        snapshot = None
        frame = _frame(now)
        for session in _session_candidates(now):
            try:
                snapshot = self.provider.capture(session, frame, symbols)
                break
            except Exception as error:  # Endpoint failures are data, not instructions or permission changes.
                attempts.append({"session": session, "error": type(error).__name__ + ": " + str(error)[:160]})
        if snapshot is None:
            return {**base, "status": "UNAVAILABLE", "attempts": attempts,
                "message": "公开行情源未形成两源一致结果；不得据此声称当前价格。"}
        as_of = snapshot.get("as_of")
        try:
            observed = datetime.fromisoformat(str(as_of)).astimezone(TZ)
            age_seconds = max(0.0, (now - observed).total_seconds())
        except (TypeError, ValueError):
            observed = None;age_seconds = None
        quotes = []
        for item in snapshot.get("instruments", []):
            last = item.get("last", item.get("auction_price"))
            previous_close = item.get("previous_close")
            change = change_pct = None
            if isinstance(last, (int, float)) and isinstance(previous_close, (int, float)) and previous_close > 0:
                change = float(last) - float(previous_close)
                change_pct = change / float(previous_close) * 100
            quotes.append({
                "symbol": item.get("symbol"), "name": item.get("name"),
                "last": last, "change": change, "change_pct": change_pct,
                "previous_close": previous_close, "open": item.get("open"),
                "high": item.get("high"), "low": item.get("low"),
                "volume": item.get("volume"), "amount": item.get("amount"),
                "tradable_observed": item.get("tradable"),
                "bid1": (item.get("metrics") or {}).get("bid1"),
                "ask1": (item.get("metrics") or {}).get("ask1"),
                "agreement_sources": (item.get("metrics") or {}).get("agreement_sources", []),
                "source_times": (item.get("metrics") or {}).get("source_times", {}),
            })
        return {**base, "status": "OK", "trading_day": snapshot.get("trading_day"),
            "as_of": as_of, "captured_at": now.isoformat(),
            "age_seconds": age_seconds,
            "market_status": _market_status(now, str(snapshot.get("trading_day")), age_seconds),
            "provider": snapshot.get("provider"), "provider_ref": snapshot.get("provider_ref"),
            "source_hash": snapshot.get("source_hash"), "completeness": snapshot.get("completeness"),
            "quotes": quotes, "source_health": (snapshot.get("market_metrics") or {}).get("source_health", {}),
            "consensus_issues": (snapshot.get("market_metrics") or {}).get("consensus_issues", []),
            "attempts_before_success": attempts,
            "limitations": [
                "公开网页行情仅用于当前问答，不具交易所行情 SLA。",
                "本结果未写入 MarketSnapshotStore，不能替代正式冻结行情、SecurityStatus 或 MarketRules。",
            ]}

    @staticmethod
    def tool_result(value):
        if value is None:
            return None
        ok = value.get("status") == "OK"
        evidence = []
        if ok:
            evidence = [{"kind": "live_stock_quote", "symbol": quote.get("symbol"),
                "trading_day": value.get("trading_day"), "as_of": value.get("as_of"),
                "provider": value.get("provider"), "source_hash": value.get("source_hash")}
                for quote in value.get("quotes", [])]
        return {"ok": ok, "tool": "get_live_stock_quote", "data": value, "evidence": evidence,
            "warnings": ["用户本轮明确股票只授权一次只读实时报价；未创建正式MarketSnapshot、Decision或订单。"],
            "error": None if ok else {"code": "LIVE_QUOTE_" + str(value.get("status")),
                "message": str(value.get("message") or "实时行情查询未完成")[:240]}}


__all__ = ["FORMAT", "MAX_EXPLICIT_SYMBOLS", "LiveStockQuoteService"]
