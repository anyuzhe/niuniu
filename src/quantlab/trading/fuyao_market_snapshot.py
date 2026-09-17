"""Fuyao-backed ad-hoc quotes with public-web cross-validation."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re

from quantlab.agent.fuyao_mcp import FuyaoMCPClient
from quantlab.storage.codec import digest
from quantlab.trading.decision import SYMBOL
from quantlab.trading.public_web_market_snapshot import PublicWebConsensusProvider


TZ = ZoneInfo("Asia/Shanghai")
PROVIDER_ID = "fuyao-with-public-cross-validation-v1"
MAX_SYMBOLS = 100


def _symbols(values):
    if not isinstance(values, list) or not values or len(values) > MAX_SYMBOLS:
        raise ValueError("symbols须为1–100只证券")
    result = []
    for value in values:
        if not isinstance(value, str) or not SYMBOL.fullmatch(value.lower()):
            raise ValueError("symbol须为sh/sz/bj.XXXXXX")
        value = value.lower()
        if value not in result:
            result.append(value)
    return result


def _thscode(symbol):
    exchange, ticker = symbol.split(".")
    return ticker + "." + exchange.upper()


def _symbol(thscode):
    match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", str(thscode).upper())
    return match.group(2).lower() + "." + match.group(1) if match else ""


def _timestamp(value):
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).astimezone(TZ)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


class FuyaoQuoteProvider:
    def __init__(self, client, *, now_fn=None):
        self.client = client
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._calendar = None
        self._calendar_date = None

    def capabilities(self):
        return {"format": "niuniu-market-snapshot-provider-v1", "provider_id": "fuyao-mcp-v1",
            "provider": "Fuyao MCP", "implemented": self.client.available, "live_channel": True,
            "network": True, "frames": ["AUCTION", "R1", "R2", "R3"], "full_snapshot": True,
            "source_hash_required": True, "credentials_required": True, "automatic_capture": True,
            "strict_pit_source_verified": False,
            "scope": "External current quote evidence; no exchange-feed SLA, official rules, or Strict PIT."}

    def _now(self):
        value = self.now_fn()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("provider now_fn必须返回带时区datetime")
        return value.astimezone(TZ)

    def _trading_days(self, current_date):
        if self._calendar is None or self._calendar_date != current_date:
            call = self.client.call("a-share", "get_a_share_calendar_trading_days", {})
            self._calendar = {str(row.get("date", "")) for row in call["data"].get("item", [])}
            self._calendar_date = current_date
        return self._calendar

    def capture(self, trading_day, frame, symbols):
        if frame not in ("AUCTION", "R1", "R2", "R3"):
            raise ValueError("live provider frame无效")
        symbols = _symbols(symbols)
        now = self._now()
        date_token = trading_day.replace("-", "")
        if date_token not in self._trading_days(now.date()):
            raise ValueError("扶摇交易日历不包含请求日期")
        if trading_day == now.date().isoformat() and now.time() < datetime.strptime("09:15", "%H:%M").time():
            raise ValueError("当前交易日尚未进入集合竞价")
        thscodes = [_thscode(value) for value in symbols]
        if frame == "AUCTION":
            stage = "live" if trading_day == now.date().isoformat() and now.time() < datetime.strptime("09:30", "%H:%M").time() else "final"
            call = self.client.call("a-share", "get_a_share_auction_snapshot",
                {"thscodes": ",".join(thscodes), "stage": stage})
        else:
            call = self.client.call("a-share", "get_a_share_prices_snapshot", {"thscodes": ",".join(thscodes)})
        observed = _timestamp(call.get("response_timestamp"))
        if observed is None or observed.date().isoformat() != trading_day:
            raise ValueError("扶摇快照时间与请求交易日不一致")
        requested = set(symbols)
        instruments = []
        for row in call["data"].get("item", []):
            symbol = _symbol(row.get("thscode"))
            if symbol not in requested:
                continue
            previous = row.get("pre_close_price", row.get("prev_price"))
            item = {"symbol": symbol, "name": str(row.get("name") or ""), "previous_close": previous,
                "tradable": bool(row.get("auction_price", row.get("last_price"))),
                "execution_profile": "UNKNOWN", "metrics": {"agreement_sources": ["fuyao"],
                    "source_times": {"fuyao": observed.isoformat()}, "bid1": None, "ask1": None,
                    "request_id": call.get("request_id"), "response_timestamp": call.get("response_timestamp"),
                    "captured_at": call.get("captured_at"), "source_hash": call.get("source_hash"),
                    "timestamp_semantics": "fuyao_data_ready_time_latest_upstream_valid_time"}}
            if frame == "AUCTION":
                item["auction_price"] = row.get("auction_price", row.get("last_price"))
                item["volume"] = row.get("auction_volume")
                item["amount"] = row.get("auction_amount")
            else:
                item.update(last=row.get("last_price"), open=row.get("open_price"), high=row.get("high_price"),
                    low=row.get("low_price"), volume=row.get("volume"), amount=row.get("turnover"))
            instruments.append(item)
        if not instruments:
            raise ValueError("扶摇未返回请求证券的有效快照")
        complete = len(instruments) == len(symbols)
        return {"trading_day": trading_day, "frame": frame, "as_of": observed.isoformat(),
            "provider": "fuyao-mcp-v1", "provider_ref": "fuyao:a-share/" + call["tool"],
            "source_hash": call["source_hash"], "completeness": "FULL" if complete else "PARTIAL",
            "strict_pit_source_verified": False, "instruments": instruments,
            "market_metrics": {"requested_symbols": len(symbols), "fuyao_symbols": len(instruments),
                "source_health": {"fuyao": {"accepted": len(instruments), "request_id": call.get("request_id"),
                    "captured_at": call.get("captured_at"), "response_timestamp": call.get("response_timestamp"),
                    "source_hash": call.get("source_hash")}}, "consensus_issues": []},
            "notes": "扶摇外部当前行情；timestamp 是响应就绪时间，不认证交易所逐笔时点或 Strict PIT。"}


def _price(item, frame):
    return item.get("auction_price") if frame == "AUCTION" else item.get("last")


def _agrees(first, second, key):
    try:
        left = float(first.get(key)); right = float(second.get(key))
    except (TypeError, ValueError):
        return False
    tolerance = max(.011, min(.03, abs((left + right) / 2) * .0002))
    return abs(left - right) <= tolerance


class FuyaoAugmentedQuoteProvider:
    """Prefer Fuyao while treating the existing two-source consensus as validation/fallback."""

    def __init__(self, fuyao, public=None):
        self.fuyao = fuyao
        self.public = public or PublicWebConsensusProvider(now_fn=fuyao.now_fn)

    def capabilities(self):
        result = self.fuyao.capabilities()
        return {**result, "provider_id": PROVIDER_ID, "provider": "Fuyao + public web cross-validation",
            "source_roles": {"fuyao": "primary", "public-web-consensus": "cross_validation_and_fallback"}}

    def capture(self, trading_day, frame, symbols):
        primary = validation = None
        primary_error = validation_error = None
        try:
            primary = self.fuyao.capture(trading_day, frame, symbols)
        except Exception as error:
            primary_error = type(error).__name__ + ": " + str(error)[:160]
        try:
            validation = self.public.capture(trading_day, frame, symbols)
        except Exception as error:
            validation_error = type(error).__name__ + ": " + str(error)[:160]
        if primary is None and validation is None:
            raise ValueError("扶摇与公开网页校验源均不可用：" + str(primary_error) + " | " + str(validation_error))
        if primary is None:
            metrics = dict(validation.get("market_metrics") or {})
            metrics["fuyao_primary_error"] = primary_error
            return {**validation, "provider": PROVIDER_ID, "market_metrics": metrics,
                "notes": str(validation.get("notes") or "") + " 扶摇主源失败，本次使用公开网页共识回退。"}
        metrics = dict(primary.get("market_metrics") or {})
        metrics["public_validation_error"] = validation_error
        if validation is None:
            return {**primary, "provider": PROVIDER_ID, "market_metrics": metrics,
                "notes": str(primary.get("notes") or "") + " 公开网页交叉校验不可用，本次仅保留扶摇主源并显式标记。"}
        public_by_symbol = {item.get("symbol"): item for item in validation.get("instruments", [])}
        issues = list(metrics.get("consensus_issues") or [])
        for item in primary.get("instruments", []):
            other = public_by_symbol.get(item.get("symbol"))
            if other is None:
                issues.append({"symbol": item.get("symbol"), "reason": "public_validation_missing"})
                continue
            current_key = "auction_price" if frame == "AUCTION" else "last"
            if not _agrees(item, other, current_key) or not _agrees(item, other, "previous_close"):
                issues.append({"symbol": item.get("symbol"), "reason": "fuyao_public_price_mismatch",
                    "fuyao": {current_key: item.get(current_key), "previous_close": item.get("previous_close")},
                    "public": {current_key: other.get(current_key), "previous_close": other.get("previous_close")}})
                continue
            item_metrics = item.setdefault("metrics", {})
            public_metrics = other.get("metrics") or {}
            item_metrics["agreement_sources"] = ["fuyao", *public_metrics.get("agreement_sources", [])]
            item_metrics["source_times"] = {**item_metrics.get("source_times", {}),
                **public_metrics.get("source_times", {})}
            item_metrics["public_source_last"] = public_metrics.get("source_last", {})
            item_metrics["bid1"] = public_metrics.get("bid1")
            item_metrics["ask1"] = public_metrics.get("ask1")
        metrics["consensus_issues"] = issues
        metrics["public_validation"] = validation.get("market_metrics", {}).get("source_health", {})
        complete = primary.get("completeness") == "FULL" and validation.get("completeness") == "FULL" and not issues
        return {**primary, "provider": PROVIDER_ID,
            "provider_ref": primary.get("provider_ref") + " | " + str(validation.get("provider_ref")),
            "source_hash": digest({"fuyao": primary.get("source_hash"), "public": validation.get("source_hash"),
                "issues": issues}), "completeness": "FULL" if complete else "PARTIAL", "market_metrics": metrics,
            "notes": str(primary.get("notes") or "") + " 已用腾讯/东方财富/新浪两源共识做交叉校验；不认证 Strict PIT。"}


def build_live_quote_provider(client=None, *, now_fn=None, public=None):
    client = client if client is not None else FuyaoMCPClient(now_fn=now_fn)
    if not client.available:
        return public or PublicWebConsensusProvider(now_fn=now_fn)
    fuyao = FuyaoQuoteProvider(client, now_fn=now_fn)
    return FuyaoAugmentedQuoteProvider(fuyao, public=public)


__all__ = ["FuyaoAugmentedQuoteProvider", "FuyaoQuoteProvider", "PROVIDER_ID", "build_live_quote_provider"]
