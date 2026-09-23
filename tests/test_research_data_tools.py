"""CODE wrappers for DATA-owned research APIs; no real network."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
from quantlab.agent.research_data_cli import main as cli_main
from quantlab.agent.research_data_tools import NAMES, ResearchDataAPI
from quantlab.data.research_provider import (
    DataProviderError, InvalidRequest, ProviderNotConfigured, ProviderResult,
)


HEADER = """# DATA → CODE 数据清单

## 3. 可供 CODE 使用的数据（READY）

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
{ready}

## 4. 尚不可用、待审查或只供 DATA 内部使用

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
{other}
"""


class Inner:
    def schemas(self):
        return []

    def call(self, name, args):
        if name == "get_capabilities":
            return {"ok": True, "tool": name, "data": {}, "evidence": [], "warnings": [], "error": None}
        raise ValueError("unsupported")


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.fail = None

    def _call(self, dataset, **kwargs):
        self.calls.append((dataset, kwargs))
        if self.fail == "not_configured":
            raise ProviderNotConfigured(dataset, "missing credential")
        if self.fail == "unavailable":
            raise DataProviderError(dataset, "vendor down")
        if self.fail == "invalid":
            raise InvalidRequest("bad request")
        return ProviderResult(
            dataset=dataset, source="fake-data-provider", request=kwargs,
            rows=({"dataset": dataset, "value": 1},),
            fetched_at="2026-09-23T11:00:00+00:00", total=1,
        )

    def research_search(self, query, channel="report", size=20):
        return self._call("research_search", query=query, channel=channel, size=size)

    def stock_research_reports(self, code, limit=50):
        return self._call("stock_research_reports", code=code, limit=limit)

    def stock_news(self, code, limit=20):
        return self._call("stock_news", code=code, limit=limit)

    def stock_announcements(self, code, start=None, end=None, limit=30):
        return self._call("stock_announcements", code=code, start=start, end=end, limit=limit)

    def financial_statements(self, code, statement="income", periods=8):
        return self._call("financial_statements", code=code, statement=statement, periods=periods)

    def investor_qa(self, code, limit=30):
        return self._call("investor_qa", code=code, limit=limit)


class Fixture:
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.catalog = self.root / "data-catalog.md"
        self.provider = FakeProvider()
        self.write_catalog()

    def write_catalog(self, blocked=()):
        ready, other = [], []
        for name in sorted(NAMES):
            row = f"| `{name}` | API | {name} | `ResearchDataProvider.{name}` | call | research_only | `{{status}}` | 统一Provider |"
            if name in blocked:
                other.append(row.format(status="REVIEW_REQUIRED"))
            else:
                ready.append(row.format(status="READY"))
        other.append("| `stock_fund_flow_daily` | API | flow | `ResearchDataProvider.stock_fund_flow_daily` | call | research_only | `REVIEW_REQUIRED` | 暂不使用 |")
        self.catalog.write_text(
            HEADER.format(ready="\n".join(ready), other="\n".join(other)), encoding="utf-8")


class ResearchDataToolTests(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        self.api = ResearchDataAPI(Inner(), provider=self.provider, data_catalog_path=self.catalog)

    def test_schemas_and_ready_call_use_data_provider_without_revalidation(self):
        schemas = {tool["name"]: tool for tool in self.api.schemas()}
        self.assertEqual(NAMES, set(schemas))
        result = self.api.call("stock_news", {"code": "300750", "limit": 5})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["data_authority"], "DATA")
        self.assertFalse(result["data"]["data_correctness_revalidated_by_code"])
        self.assertFalse(result["data"]["fallback_performed"])
        self.assertFalse(result["data"]["strict_pit"])
        self.assertEqual(self.provider.calls, [("stock_news", {"code": "300750", "limit": 5})])

    def test_review_required_blocks_before_provider_and_no_fallback(self):
        self.write_catalog(blocked={"stock_news"})
        blocked = ResearchDataAPI(Inner(), provider=self.provider, data_catalog_path=self.catalog)
        self.assertNotIn("stock_news", {tool["name"] for tool in blocked.schemas()})
        result = blocked.call("stock_news", {"code": "300750", "limit": 5})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "DATASET_NOT_READY")
        self.assertEqual(self.provider.calls, [])

    def test_provider_failures_are_explicit_and_not_empty(self):
        for mode, code in (
            ("not_configured", "DATA_PROVIDER_NOT_CONFIGURED"),
            ("unavailable", "DATA_PROVIDER_UNAVAILABLE"),
            ("invalid", "INVALID_ARGUMENT"),
        ):
            self.provider.fail = mode
            with self.subTest(mode=mode):
                result = self.api.call("stock_news", {"code": "300750", "limit": 5})
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], code)
                self.assertIsNone(result["data"])

    def test_announcements_empty_dates_become_none(self):
        result = self.api.call("stock_announcements", {
            "code": "300750", "start": "", "end": "", "limit": 5})
        self.assertTrue(result["ok"])
        self.assertEqual(
            self.provider.calls[-1],
            ("stock_announcements", {"code": "300750", "start": None, "end": None, "limit": 5}),
        )

    def test_chat_exposes_network_tools_only_outside_local_or_locked_mode(self):
        normal = ChatRuntime(
            self.output, local_data_only=False, research_data_provider=self.provider,
            data_catalog_path=self.catalog).api
        self.assertTrue(NAMES <= {tool["name"] for tool in normal.schemas()})

        local = ChatRuntime(
            self.output / "local", local_data_only=True, research_data_provider=self.provider,
            data_catalog_path=self.catalog).api
        self.assertTrue(NAMES.isdisjoint({tool["name"] for tool in local.schemas()}))

        from test_qm50_archived_inputs import ArchivedQM50Tests
        f = ArchivedQM50Tests()
        self.addCleanup(f.doCleanups)
        f.setUp()
        locked = ChatRuntime(
            f.output, research_spec=f.sid, spec_source_workspace=f.source,
            research_data_provider=self.provider, data_catalog_path=self.catalog).api
        self.assertTrue(NAMES.isdisjoint({tool["name"] for tool in locked.schemas()}))

    def test_cli_uses_same_wrapper(self):
        out = io.StringIO()
        with patch("quantlab.agent.research_data_tools.ResearchDataAPI._get_provider",
                   return_value=self.provider), contextlib.redirect_stdout(out):
            code = cli_main([
                "--catalog", str(self.catalog), "news", "--code", "300750", "--limit", "3"])
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "stock_news")


class ResearchDataMCPTests(Fixture, IsolatedAsyncioTestCase):
    async def test_inprocess_mcp_marks_network_tools_open_world(self):
        from mcp import Client

        api = build_mcp_api(
            self.output, data_catalog_path=self.catalog, research_data_provider=self.provider)
        expected = api.call("financial_statements", {
            "code": "300750", "statement": "income", "periods": 2})
        server = build_mcp_server(
            self.output, data_catalog_path=self.catalog, research_data_provider=self.provider)
        async with Client(server, read_timeout_seconds=30) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            for name in NAMES:
                self.assertTrue(tools[name].annotations.read_only_hint)
                self.assertTrue(tools[name].annotations.open_world_hint)
                self.assertFalse(tools[name].input_schema["additionalProperties"])
            got = await client.call_tool("financial_statements", {
                "code": "300750", "statement": "income", "periods": 2})
            self.assertFalse(got.is_error)
            self.assertEqual(json.loads(got.content[0].text), expected)

    async def test_stdio_mcp_loads_data_provider_but_invalid_request_never_networks(self):
        from mcp import Client, StdioServerParameters

        params = StdioServerParameters(
            command=sys.executable,
            args=["-B", "-m", "quantlab.agent.mcp_server", "--output", str(self.output),
                  "--data-catalog-path", str(self.catalog)],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        async with Client(params, read_timeout_seconds=30) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            self.assertTrue(tools["financial_statements"].annotations.read_only_hint)
            self.assertTrue(tools["financial_statements"].annotations.open_world_hint)
            got = await client.call_tool("financial_statements", {
                "code": "BAD", "statement": "income", "periods": 2})
            self.assertFalse(got.is_error)
            result = json.loads(got.content[0].text)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")


if __name__ == "__main__":
    import unittest
    unittest.main()
