"""Bounded host tools that summarize Fuyao MCP data for the research model."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import re

from quantlab.agent.catalog import compact, schema
from quantlab.agent.fuyao_mcp import FuyaoMCPClient, FuyaoMCPError
from quantlab.storage.codec import encode


TZ = ZoneInfo("Asia/Shanghai")
THSCODE = re.compile(r"\d{6}\.(?:SH|SZ|BJ)")
REPORT = re.compile(r"20\d{2}-[1-4]")
DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")
EXTERNAL_WARNING = (
    "扶摇是当前/回顾性外部数据源：不具 Strict PIT、官方 MarketRules 或交易所行情 SLA，"
    "本结果不能单独构成交易信号、Decision 或订单。"
)

TEXT = {"type": "string", "maxLength": 200}
TOOLS = [
    schema("resolve_fuyao_security", "用扶摇元信息解析证券、指数或板块名称；先消歧再查询。", {
        "query": TEXT,
        "asset_type": {"type": "string", "enum": ["a-share", "a-share-index"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
    }),
    schema("get_fuyao_stock_context", "查询单只 A 股当前快照与近期日 K 摘要。", {
        "thscode": {"type": "string", "pattern": "^[0-9]{6}\\.(SH|SZ|BJ)$"},
        "history_days": {"type": "integer", "minimum": 5, "maximum": 250},
        "adjust": {"type": "string", "enum": ["none", "forward", "backward"]},
    }),
    schema("get_fuyao_sector_context", "查询指定概念/行业/特色板块行情，并核验目标股票是否为当前成分股。", {
        "thscode": {"type": "string", "pattern": "^[0-9]{6}\\.(SH|SZ|BJ)$"},
        "queries": {"type": "string", "minLength": 1, "maxLength": 200},
        "max_matches": {"type": "integer", "minimum": 1, "maximum": 6},
    }),
    schema("get_fuyao_short_term_context", "查询个股热度、异动、竞价、龙虎榜及涨跌停情绪的有界摘要。", {
        "thscode": {"type": "string", "pattern": "^[0-9]{6}\\.(SH|SZ|BJ)$"},
        "date": {"type": "string", "pattern": "^20[0-9]{2}-[0-9]{2}-[0-9]{2}$"},
        "trend_days": {"type": "integer", "minimum": 3, "maximum": 30},
    }),
    schema("get_fuyao_fundamental_context", "查询单只 A 股当前估值和指定报告期五类财务指标。", {
        "thscode": {"type": "string", "pattern": "^[0-9]{6}\\.(SH|SZ|BJ)$"},
        "report": {"type": "string", "pattern": "^20[0-9]{2}-[1-4]$"},
    }),
]
TOOL_NAMES = {item["name"] for item in TOOLS}


def _items(call):
    value = call.get("data", {}).get("item", [])
    return value if isinstance(value, list) else []


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _milliseconds(value: datetime):
    return int(value.timestamp() * 1000)


def _evidence(call):
    return {"kind": "fuyao", "service": call.get("service"), "tool": call.get("tool"),
        "request_id": call.get("request_id"), "source_hash": call.get("source_hash"),
        "captured_at": call.get("captured_at"), "response_timestamp": call.get("response_timestamp")}


def _target_rows(value, thscode):
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_target_rows(item, thscode))
        return result
    if isinstance(value, dict):
        result = [value] if str(value.get("thscode", "")).upper() == thscode else []
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                result.extend(_target_rows(nested, thscode))
        return result
    return []


class FuyaoContextService:
    def __init__(self, client, *, now_fn=None):
        self.client = client
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._catalog = {}

    def _now(self):
        value = self.now_fn()
        if not isinstance(value, datetime) or value.tzinfo is None:
            value = datetime.now(timezone.utc)
        return value.astimezone(TZ)

    def resolve(self, args):
        call = self.client.call("meta", "get_meta_tickers_search", {"q": args["query"],
            "asset_type": args["asset_type"], "limit": args["limit"]})
        rows = _items(call)[:args["limit"]]
        return {"query": args["query"], "asset_type": args["asset_type"], "matches": rows,
            "total_returned": len(rows)}, [_evidence(call)], []

    def stock(self, args):
        now = self._now()
        start = now - timedelta(days=max(args["history_days"] * 2, args["history_days"] + 10))
        snapshot = self.client.call("a-share", "get_a_share_prices_snapshot", {"thscodes": args["thscode"]})
        history = self.client.call("a-share", "get_a_share_prices_historical", {
            "thscode": args["thscode"], "interval": "1d", "start": _milliseconds(start),
            "end": _milliseconds(now), "adjust": args["adjust"]})
        bars = _items(history)[-args["history_days"]:]
        closes = [_number(row.get("close_price")) for row in bars]
        closes = [value for value in closes if value is not None]
        highs = [_number(row.get("high_price")) for row in bars]
        lows = [_number(row.get("low_price")) for row in bars]
        volumes = [_number(row.get("volume")) for row in bars]
        valid_volumes = [value for value in volumes if value is not None]
        summary = {"bars": len(bars), "period_return_pct": None, "period_high": max(
            (value for value in highs if value is not None), default=None), "period_low": min(
            (value for value in lows if value is not None), default=None), "average_volume": None,
            "latest_volume_ratio": None}
        if len(closes) >= 2 and closes[0] != 0:
            summary["period_return_pct"] = (closes[-1] / closes[0] - 1) * 100
        if valid_volumes:
            summary["average_volume"] = sum(valid_volumes) / len(valid_volumes)
            prior = valid_volumes[:-1]
            if prior and sum(prior) > 0:
                summary["latest_volume_ratio"] = valid_volumes[-1] / (sum(prior) / len(prior))
        data = {"thscode": args["thscode"], "snapshot": _items(snapshot), "history": bars[-30:],
            "history_adjust": args["adjust"], "summary": summary}
        return data, [_evidence(snapshot), _evidence(history)], []

    def _catalog_rows(self, tag):
        if tag not in self._catalog:
            call = self.client.call("a-share-index", "get_a_share_index_catalog_ths_index_list", {"tag": tag})
            self._catalog[tag] = (_items(call), _evidence(call))
        return self._catalog[tag]

    def sector(self, args):
        queries = [part.strip() for part in re.split(r"[,，、;；\s]+", args["queries"]) if part.strip()]
        if not queries:
            raise ValueError("INVALID_ARGUMENT：queries 至少包含一个板块词。")
        candidates = []
        evidence = []
        for tag in ("cn_concept", "industry", "tszs"):
            rows, ref = self._catalog_rows(tag)
            if ref not in evidence:
                evidence.append(ref)
            for query in queries:
                exact = [row for row in rows if str(row.get("name", "")).casefold() == query.casefold()]
                fuzzy = [row for row in rows if query.casefold() in str(row.get("name", "")).casefold()]
                for row in exact + fuzzy:
                    key = str(row.get("thscode", ""))
                    if key and all(str(item.get("thscode")) != key for item in candidates):
                        candidates.append({**row, "tag": tag, "matched_query": query})
        candidates = candidates[:args["max_matches"]]
        matches = []
        for candidate in candidates:
            constituents = self.client.call("a-share-index", "get_a_share_index_constituents_ths_stock_list",
                {"thscode": candidate["thscode"]})
            evidence.append(_evidence(constituents))
            rows = _items(constituents)
            matches.append({**candidate, "constituent_count": len(rows),
                "contains_target": any(str(row.get("thscode", "")).upper() == args["thscode"] for row in rows)})
        if matches:
            quote = self.client.call("a-share-index", "get_a_share_index_prices_snapshot",
                {"thscodes": ",".join(item["thscode"] for item in matches)})
            evidence.append(_evidence(quote))
            by_code = {str(row.get("thscode")): row for row in _items(quote)}
            for item in matches:
                item["snapshot"] = by_code.get(item["thscode"])
        warnings = [] if matches else ["未在概念、行业和特色指数目录中匹配到指定板块词。"]
        return {"target_thscode": args["thscode"], "queries": queries, "matches": matches,
            "membership_is_current_not_historical": True}, evidence, warnings

    def short_term(self, args):
        now = self._now()
        try:
            target_day = datetime.strptime(args["date"], "%Y-%m-%d").replace(tzinfo=TZ)
        except ValueError:
            raise ValueError("INVALID_ARGUMENT：date 必须是有效日期。") from None
        start_day = (target_day - timedelta(days=args["trend_days"] - 1)).date().isoformat()
        calls = {}
        calls["rank_trend"] = self.client.call("a-share", "get_a_share_special_data_hot_stock_rank_trend",
            {"thscode": args["thscode"], "start_date": start_day, "end_date": args["date"]})
        pool_specs = {
            "limit_up": ("get_a_share_special_data_limit_up_pool", "limit_up_time"),
            "limit_down": ("get_a_share_special_data_limit_down_pool", "last_limit_time"),
            "limit_break": ("get_a_share_special_data_limit_break_pool", "price_change_ratio_pct"),
        }
        date_ms = _milliseconds(target_day)
        for key, (tool, sort_field) in pool_specs.items():
            calls[key] = self.client.call("a-share", tool, {"date_ms": date_ms, "page": 1,
                "size": 200, "sort_field": sort_field, "sort_dir": "desc"})
        calls["ladder"] = self.client.call("a-share", "get_a_share_special_data_limit_up_ladder", {})
        calls["dragon_tiger"] = self.client.call("a-share", "get_a_share_special_data_dragon_tiger_list",
            {"board_type": "all", "date": args["date"]})
        calls["auction_benchmark"] = self.client.call("a-share", "get_a_share_auction_short_term_benchmark",
            {"date": args["date"]})
        if args["date"] == now.date().isoformat():
            calls["auction"] = self.client.call("a-share", "get_a_share_auction_snapshot",
                {"thscodes": args["thscode"], "stage": "live" if now.time() < datetime.strptime("09:30", "%H:%M").time() else "final"})
            calls["anomaly"] = self.client.call("a-share", "get_a_share_special_data_anomaly_analysis_stock",
                {"thscodes": args["thscode"]})
        pools = {}
        for key in pool_specs:
            data = calls[key]["data"]
            rows = _items(calls[key])
            pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
            pools[key] = {"market_total": pagination.get("total", len(rows)),
                "target_records": [row for row in rows if str(row.get("thscode", "")).upper() == args["thscode"]],
                "top_records": rows[:8]}
        dragon_data = calls["dragon_tiger"]["data"]
        dragon_rows = dragon_data.get("stock_items", dragon_data.get("item", []))
        if not isinstance(dragon_rows, list):
            dragon_rows = []
        data = {"thscode": args["thscode"], "date": args["date"],
            "hot_rank_trend": _items(calls["rank_trend"]), "limit_pools": pools,
            "ladder_target_records": _target_rows(calls["ladder"]["data"], args["thscode"]),
            "dragon_tiger": {"market_count": dragon_data.get("stock_count", len(dragon_rows)),
                "target_records": [row for row in dragon_rows if str(row.get("thscode", "")).upper() == args["thscode"]]},
            "auction_benchmark_target_records": _target_rows(calls["auction_benchmark"]["data"], args["thscode"])}
        if "auction" in calls:
            data["auction"] = _items(calls["auction"])
            data["anomaly"] = _items(calls["anomaly"])
        warnings = []
        if args["date"] != now.date().isoformat():
            warnings.append("竞价快照和个股异动只提供当日口径，本次历史日期未调用这两个当前态接口。")
        return data, [_evidence(call) for call in calls.values()], warnings

    def fundamental(self, args):
        valuation = self.client.call("a-share", "get_a_share_valuations_snapshot", {"thscodes": args["thscode"]})
        indicators = self.client.call("a-share", "get_a_share_financials_indicators",
            {"thscode": args["thscode"], "report": args["report"]})
        return {"thscode": args["thscode"], "report": args["report"], "valuation": _items(valuation),
            "financial_indicators": indicators["data"]}, [_evidence(valuation), _evidence(indicators)], []


class FuyaoResearchAPI:
    """Add five aggregate Fuyao tools while preserving the existing API chain."""

    def __init__(self, inner, client=None, *, now_fn=None):
        self.inner = inner
        self.client = client if client is not None else FuyaoMCPClient(now_fn=now_fn)
        self.service = FuyaoContextService(self.client, now_fn=now_fn)

    def __getattr__(self, name):
        # Preserve host-facing services exposed by the existing wrapper chain.
        return getattr(self.inner, name)

    def schemas(self):
        values = self.inner.schemas()
        return values + (json.loads(json.dumps(TOOLS, ensure_ascii=False)) if self.client.available else [])

    @staticmethod
    def _validate(name, args):
        definition = next(item for item in TOOLS if item["name"] == name)
        props = definition["parameters"]["properties"]
        if not isinstance(args, dict) or set(args) != set(props):
            raise ValueError("INVALID_ARGUMENT：字段必须与工具 Schema 一致。")
        if name == "resolve_fuyao_security":
            if not isinstance(args["query"], str) or not args["query"].strip() or len(args["query"]) > 200:
                raise ValueError("INVALID_ARGUMENT：query 无效。")
            if args["asset_type"] not in ("a-share", "a-share-index") or type(args["limit"]) is not int or not 1 <= args["limit"] <= 10:
                raise ValueError("INVALID_ARGUMENT：asset_type 或 limit 无效。")
            return
        if not isinstance(args["thscode"], str) or not THSCODE.fullmatch(args["thscode"]):
            raise ValueError("INVALID_ARGUMENT：thscode 必须是大写完整 A 股代码。")
        if name == "get_fuyao_stock_context":
            if type(args["history_days"]) is not int or not 5 <= args["history_days"] <= 250 or args["adjust"] not in ("none", "forward", "backward"):
                raise ValueError("INVALID_ARGUMENT：history_days 或 adjust 无效。")
        elif name == "get_fuyao_sector_context":
            if not isinstance(args["queries"], str) or not args["queries"].strip() or len(args["queries"]) > 200 or type(args["max_matches"]) is not int or not 1 <= args["max_matches"] <= 6:
                raise ValueError("INVALID_ARGUMENT：queries 或 max_matches 无效。")
        elif name == "get_fuyao_short_term_context":
            if not isinstance(args["date"], str) or not DATE.fullmatch(args["date"]) or type(args["trend_days"]) is not int or not 3 <= args["trend_days"] <= 30:
                raise ValueError("INVALID_ARGUMENT：date 或 trend_days 无效。")
        elif name == "get_fuyao_fundamental_context" and (not isinstance(args["report"], str) or not REPORT.fullmatch(args["report"])):
            raise ValueError("INVALID_ARGUMENT：report 格式应为 YYYY-[1-4]。")

    def call(self, name, arguments):
        if name == "get_capabilities":
            result = self.inner.call(name, arguments)
            if result.get("ok"):
                result["data"]["tools"] = [tool["name"] for tool in self.schemas()]
                result["data"]["fuyao"] = {"configured": self.client.available,
                    "access": "host_wrapped_read_only", "aggregate_tools": sorted(TOOL_NAMES) if self.client.available else [],
                    "strict_pit_source_verified": False}
                result["data"].setdefault("limitations", []).append("扶摇仅作为外部当前/回顾性数据源，不能替代官方 MarketRules 或 Strict PIT。")
            return result
        if name not in TOOL_NAMES:
            return self.inner.call(name, arguments)
        try:
            if not self.client.available:
                raise FuyaoMCPError("FUYAO_NOT_CONFIGURED", "扶摇数据源尚未配置凭证。")
            self._validate(name, arguments)
            method = {"resolve_fuyao_security": "resolve", "get_fuyao_stock_context": "stock",
                "get_fuyao_sector_context": "sector", "get_fuyao_short_term_context": "short_term",
                "get_fuyao_fundamental_context": "fundamental"}[name]
            data, evidence, warnings = getattr(self.service, method)(arguments)
            result = {"ok": True, "tool": name, "data": compact(data), "evidence": evidence[:30],
                "warnings": [EXTERNAL_WARNING, *warnings], "error": None}
            if len(encode(result)) > 24000:
                result["data"] = {"omitted": True, "reason": "result_size_limit"}
                result["warnings"].append("扶摇摘要超过模型工具预算；请缩小查询范围。")
            return json.loads(encode(result))
        except (FuyaoMCPError, ValueError, KeyError, TypeError, OSError) as error:
            code = error.code if isinstance(error, FuyaoMCPError) else (
                "INVALID_ARGUMENT" if str(error).startswith("INVALID_ARGUMENT") else "FUYAO_READ_FAILED")
            message = str(error)[:300] if code in ("INVALID_ARGUMENT", "FUYAO_NOT_CONFIGURED") or isinstance(error, FuyaoMCPError) else "扶摇数据读取失败：" + type(error).__name__
            request_id = error.request_id if isinstance(error, FuyaoMCPError) else ""
            return {"ok": False, "tool": name, "data": None, "evidence": [],
                "warnings": [EXTERNAL_WARNING], "error": {"code": code, "message": message,
                    **({"request_id": request_id} if request_id else {})}}


__all__ = ["FuyaoContextService", "FuyaoResearchAPI", "TOOLS"]
