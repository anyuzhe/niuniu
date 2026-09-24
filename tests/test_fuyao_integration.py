import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.agent.fuyao_mcp import ENV_KEY, FuyaoMCPClient, FuyaoMCPError, load_api_key
from quantlab.agent.fuyao_tools import FuyaoResearchAPI
from quantlab.agent.chat_runtime import ChatRuntime, SYSTEM
from quantlab.trading.fuyao_market_snapshot import FuyaoAugmentedQuoteProvider, FuyaoQuoteProvider


TZ = ZoneInfo("Asia/Shanghai")


class InnerAPI:
    def schemas(self):
        return [{"name": "get_capabilities", "parameters": {"type": "object", "properties": {}, "required": []}}]

    def call(self, name, arguments):
        if name == "get_capabilities":
            return {"ok": True, "tool": name, "data": {"limitations": []}, "evidence": [], "warnings": [], "error": None}
        return {"ok": True, "tool": name, "data": {"delegated": True}, "evidence": [], "warnings": [], "error": None}


class FakeFuyaoClient:
    available = True

    def __init__(self):
        self.calls = []

    def call(self, service, tool, arguments):
        self.calls.append((service, tool, dict(arguments)))
        data = {"timestamp": 1789600800000, "item": []}
        if tool == "get_meta_tickers_search":
            data["item"] = [{"thscode": "301396.SZ", "name": "宏景科技", "asset_type": "a-share"}]
        elif tool == "get_a_share_prices_snapshot":
            data["item"] = [{"thscode": code, "last_price": 31.5, "prev_price": 30.0,
                "open_price": 30.2, "high_price": 32.0, "low_price": 29.9,
                "volume": 120000, "turnover": 3720000} for code in arguments["thscodes"].split(",")]
        elif tool == "get_a_share_prices_historical":
            data["item"] = [{"date_ms": index, "open_price": 29 + index, "high_price": 31 + index,
                "low_price": 28 + index, "close_price": 30 + index, "volume": 100 + index}
                for index in range(8)]
        elif tool == "get_a_share_index_catalog_ths_index_list":
            data["item"] = ([{"thscode": "886001.TI", "name": "人工智能"}]
                if arguments["tag"] == "cn_concept" else [])
        elif tool == "get_a_share_index_constituents_ths_stock_list":
            data["item"] = [{"thscode": "301396.SZ", "name": "宏景科技"}]
        elif tool == "get_a_share_index_prices_snapshot":
            data["item"] = [{"thscode": "886001.TI", "last_price": 1234, "price_change_ratio_pct": 1.2}]
        elif tool == "get_a_share_financials_indicators":
            data = {"timestamp": 1789600800000, "thscode": "301396.SZ", "report": arguments["report"],
                "abilities": [{"ability": "growth", "indicators": [{"index_id": "revenue_growth", "value": "10"}]}]}
        elif tool == "get_a_share_valuations_snapshot":
            data["item"] = [{"thscode": "301396.SZ", "pe_ttm": 40.2, "pb_mrq": 4.1}]
        elif tool == "get_a_share_calendar_trading_days":
            data["item"] = [{"date": "20260917", "date_ms": 1789574400000}]
        elif tool == "get_a_share_auction_snapshot":
            data["item"] = [{"thscode": "301396.SZ", "name": "宏景科技", "auction_price": 31.5,
                "pre_close_price": 30.0, "auction_volume": 1000, "auction_amount": 31500}]
        elif tool == "get_a_share_special_data_hot_stock_rank_trend":
            data["item"] = [{"thscode": "301396.SZ", "date": "2026-09-17", "rank": 12}]
        elif tool == "get_a_share_special_data_limit_up_pool":
            data.update(pagination={"total": 1}); data["item"] = [{"thscode": "301396.SZ", "name": "宏景科技"}]
        elif tool in ("get_a_share_special_data_limit_down_pool", "get_a_share_special_data_limit_break_pool"):
            data.update(pagination={"total": 0})
        elif tool == "get_a_share_special_data_limit_up_ladder":
            data["matrix"] = [{"stocks": [{"thscode": "301396.SZ", "board": 2}]}]
        elif tool == "get_a_share_special_data_dragon_tiger_list":
            data.update(stock_count=1, stock_items=[{"thscode": "301396.SZ", "net_value": 100}])
        elif tool == "get_a_share_auction_short_term_benchmark":
            data["item"] = [{"thscode": "301396.SZ", "auction_pct": 2.1}]
        elif tool == "get_a_share_special_data_anomaly_analysis_stock":
            data["item"] = [{"thscode": "301396.SZ", "tag_name": "大涨"}]
        return {"service": service, "tool": tool, "request_id": "request-" + str(len(self.calls)),
            "data": data, "response_timestamp": data.get("timestamp"),
            "captured_at": "2026-09-17T02:00:01+00:00", "source_hash": (str(len(self.calls)) * 64)[:64]}


class PublicProvider:
    def __init__(self, last=31.5, error=None):
        self.last = last; self.error = error

    def capture(self, trading_day, frame, symbols):
        if self.error:
            raise ValueError(self.error)
        return {"trading_day": trading_day, "frame": frame, "as_of": trading_day + "T10:00:00+08:00",
            "provider": "public-web-consensus-v1", "provider_ref": "fixture", "source_hash": "p" * 64,
            "completeness": "FULL", "strict_pit_source_verified": False,
            "instruments": [{"symbol": symbol, "previous_close": 30.0, "last": self.last,
                "metrics": {"agreement_sources": ["tencent", "sina"],
                    "source_times": {"tencent": trading_day + "T10:00:00+08:00"}}} for symbol in symbols],
            "market_metrics": {"source_health": {"tencent": {"accepted": len(symbols)}}, "consensus_issues": []}}


class FuyaoIntegrationTests(unittest.TestCase):
    def test_streamable_mcp_handshake_business_envelope_and_allowlist(self):
        requests = []

        def post(url, headers, body, timeout):
            payload = json.loads(body); requests.append((url, dict(headers), payload))
            if payload["method"] == "initialize":
                return 200, {"Mcp-Session-Id": "session-1"}, json.dumps({"jsonrpc": "2.0", "id": payload["id"],
                    "result": {"protocolVersion": "2025-03-26", "capabilities": {}}}).encode()
            if payload["method"] == "notifications/initialized":
                return 202, {}, b""
            if payload["method"] == "tools/list":
                return 200, {}, json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": [
                    {"name": "get_meta_tickers_search", "inputSchema": {"type": "object"}}]}}).encode()
            if payload.get("params", {}).get("arguments", {}).get("q") == "error":
                result = {"isError": True, "content": [{"type": "text", "text": "bad secret-fixture"}]}
                return 200, {}, json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result}).encode()
            envelope = {"code": 0, "message": "success", "request_id": "abc", "data": {
                "timestamp": 1789600800000, "item": [{"thscode": "301396.SZ"}]}}
            result = {"structuredContent": envelope, "content": []}
            return 200, {}, json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result}).encode()

        client = FuyaoMCPClient("secret-fixture", http_post=post,
            now_fn=lambda: datetime(2026, 9, 17, 10, 0, tzinfo=TZ))
        value = client.call("meta", "get_meta_tickers_search", {"q": "宏景科技", "asset_type": "a-share", "limit": 5})
        self.assertEqual(value["request_id"], "abc")
        self.assertEqual([item[2]["method"] for item in requests],
            ["initialize", "notifications/initialized", "tools/list", "tools/call"])
        self.assertEqual(requests[-1][1]["Mcp-Session-Id"], "session-1")
        self.assertNotIn("secret-fixture", json.dumps(value, ensure_ascii=False))
        with self.assertRaises(FuyaoMCPError) as caught:
            client.call("meta", "get_meta_tickers_search", {"q": "error", "asset_type": "a-share", "limit": 1})
        self.assertNotIn("secret-fixture", str(caught.exception))
        with self.assertRaises(FuyaoMCPError):
            client.call("meta", "unlisted_tool", {})

    def test_environment_credential_wins_without_keychain_lookup(self):
        called = []
        value = load_api_key({ENV_KEY: "env-secret"}, keychain_runner=lambda *a, **k: called.append(True))
        self.assertEqual(value, "env-secret"); self.assertEqual(called, [])

    def test_five_aggregate_tools_are_bounded_and_keep_existing_api(self):
        client = FakeFuyaoClient(); api = FuyaoResearchAPI(InnerAPI(), client,
            now_fn=lambda: datetime(2026, 9, 17, 10, 0, tzinfo=TZ))
        names = {item["name"] for item in api.schemas()}
        self.assertTrue({"get_capabilities", "resolve_fuyao_security", "get_fuyao_stock_context",
            "get_fuyao_sector_context", "get_fuyao_short_term_context",
            "get_fuyao_fundamental_context"}.issubset(names))
        calls = [
            ("resolve_fuyao_security", {"query": "宏景科技", "asset_type": "a-share", "limit": 5}),
            ("get_fuyao_stock_context", {"thscode": "301396.SZ", "history_days": 5, "adjust": "forward"}),
            ("get_fuyao_sector_context", {"thscode": "301396.SZ", "queries": "人工智能", "max_matches": 3}),
            ("get_fuyao_short_term_context", {"thscode": "301396.SZ", "date": "2026-09-17", "trend_days": 10}),
            ("get_fuyao_fundamental_context", {"thscode": "301396.SZ", "report": "2026-2"}),
        ]
        results = {name: api.call(name, args) for name, args in calls}
        self.assertTrue(all(result["ok"] for result in results.values()))
        self.assertTrue(results["get_fuyao_sector_context"]["data"]["matches"][0]["contains_target"])
        self.assertEqual(results["get_fuyao_stock_context"]["data"]["summary"]["bars"], 5)
        self.assertTrue(results["get_fuyao_short_term_context"]["data"]["dragon_tiger"]["target_records"])
        self.assertFalse(api.call("get_capabilities", {})["data"]["fuyao"]["strict_pit_source_verified"])

    def test_chat_runtime_registers_fuyao_only_when_data_catalog_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            def catalog(status):
                path=Path(tmp)/('data-catalog-'+status+'.md')
                path.write_text('# DATA → CODE 数据清单\n\n## 3. 可供 CODE 使用的数据（READY）\n\n'
                    '| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |\n'
                    '|---|---|---|---|---|---|---|---|\n'
                    f'| `fuyao_context` | API | context | `FuyaoContextService` | call | research_only | `{status}` | gated |\n',encoding='utf-8')
                return path
            runtime = ChatRuntime(tmp, tmp, fuyao_client=FakeFuyaoClient(),data_catalog_path=catalog('READY'))
            names = {item["name"] for item in runtime.api.schemas()}
            fuyao_names={"resolve_fuyao_security", "get_fuyao_stock_context",
                "get_fuyao_sector_context", "get_fuyao_short_term_context",
                "get_fuyao_fundamental_context"}
            self.assertTrue(fuyao_names.issubset(names))
            self.assertNotIn("get_a_share_prices_snapshot", names)
            self.assertTrue(hasattr(runtime.api, "proposals"))
            self.assertIn("不可调用宿主未注册的其他 MCP", SYSTEM)
            blocked=ChatRuntime(tmp, tmp, fuyao_client=FakeFuyaoClient(),data_catalog_path=catalog('REVIEW_REQUIRED'))
            self.assertTrue(fuyao_names.isdisjoint({item["name"] for item in blocked.api.schemas()}))

    def test_quote_provider_maps_fuyao_and_marks_cross_source_mismatch(self):
        client = FakeFuyaoClient()
        fuyao = FuyaoQuoteProvider(client,
            now_fn=lambda: datetime(2026, 9, 17, 10, 0, 1, tzinfo=TZ))
        # DATA 2026-09-24: a Fuyao quote that disagrees with the public consensus is withheld,
        # not passed on; with no agreeing symbol left the capture fails closed.
        with self.assertRaisesRegex(ValueError, "fuyao_public_price_mismatch"):
            FuyaoAugmentedQuoteProvider(fuyao, PublicProvider(last=35.0)).capture(
                "2026-09-17", "R1", ["sz.301396"])
        result = FuyaoAugmentedQuoteProvider(fuyao, PublicProvider(last=31.5)).capture(
            "2026-09-17", "R1", ["sz.301396"])
        self.assertEqual(result["provider"], "fuyao-with-public-cross-validation-v1")
        self.assertEqual(result["instruments"][0]["last"], 31.5)

    def test_public_consensus_is_retained_when_fuyao_primary_fails(self):
        class FailedFuyao:
            now_fn = lambda self: datetime(2026, 9, 17, 10, 0, tzinfo=TZ)
            def capabilities(self): return {"implemented": True}
            def capture(self, trading_day, frame, symbols): raise ValueError("fixture failure")
        result = FuyaoAugmentedQuoteProvider(FailedFuyao(), PublicProvider()).capture(
            "2026-09-17", "R1", ["sz.301396"])
        self.assertEqual(result["provider"], "fuyao-with-public-cross-validation-v1")
        self.assertIn("fixture failure", result["market_metrics"]["fuyao_primary_error"])


if __name__ == "__main__":
    unittest.main()
