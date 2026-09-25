"""DATA catalog consumer boundaries; synthetic catalog only."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase

from quantlab.agent.archived_data_tools import ArchivedMarketDataAPI
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.data_review_cli import main
from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
from quantlab.data.dataset_catalog import (
    DataCatalogError,
    get_ready_data_source,
    list_data_catalog,
    read_data_catalog,
)


HEADER = """# DATA → CODE 数据清单

## 3. 可供 CODE 使用的数据（READY）

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
{ready_rows}

## 4. 尚不可用、待审查或只供 DATA 内部使用

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
{other_rows}
"""

LEGACY_HEADER = """# DATA → CODE 数据清单

## 3. 可供 CODE 使用的数据（READY）

| 数据 ID | 数据内容 | 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|
| `legacy.file` | 旧格式日线 | `{ready_dir}` | parquet | research_only | `READY` | 直接读取 |

## 4. 尚不可用或只供 DATA 内部使用

| 数据 ID | 数据内容 | 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|
| `legacy.blocked` | 旧格式候选 | `{ready_dir}` | parquet | pending | `NOT_READY` | 不读取 |
"""


class Inner:
    def schemas(self):
        return []

    def call(self, name, args):
        if name == "get_capabilities":
            return {"ok": True, "tool": name, "data": {}, "evidence": [], "warnings": [], "error": None}
        raise ValueError("unsupported")


class CatalogFixture:
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.ready_dir = self.root / "ready"
        self.ready_dir.mkdir()
        self.catalog = self.root / "data-catalog.md"
        self.write()

    def write(self, *, duplicate=False, ready_status="READY"):
        ready = [
            f"| `ready.file` | FILE | 日线 | `{self.ready_dir}` | parquet | research_only | `{ready_status}` | 直接读取 |",
            "| `ready.api` | API | 实时报价 | `pkg.Service` | call | research_only | `READY` | 通过统一服务 |",
        ]
        if duplicate:
            ready.append(ready[0])
        other = [
            f"| `not.ready` | FILE | 未发布数据 | `{self.root / 'missing'}` | parquet | pending | `NOT_READY` | 不读取 |",
            f"| `old.file` | FILE | 旧数据 | `{self.ready_dir}` | parquet | legacy | `DEPRECATED` | 不读取 |",
        ]
        self.catalog.write_text(
            HEADER.format(ready_rows="\n".join(ready), other_rows="\n".join(other)),
            encoding="utf-8",
        )


class DataCatalogCoreTests(CatalogFixture, TestCase):
    def test_list_ready_and_resolve_only_ready(self):
        parsed = read_data_catalog(self.catalog)
        self.assertEqual(parsed["counts"]["READY"], 2)
        listed = list_data_catalog(self.catalog, status="READY", delivery="ALL", offset=0, limit=20)
        self.assertEqual([row["dataset_id"] for row in listed["rows"]], ["ready.file", "ready.api"])
        resolved = get_ready_data_source(self.catalog, dataset_id="ready.file")
        self.assertEqual(resolved["entry"]["status"], "READY")
        self.assertTrue(resolved["technical_check"]["checked"])
        self.assertTrue(resolved["technical_check"]["paths"][0]["readable"])
        self.assertFalse(resolved["data_correctness_revalidated_by_code"])
        self.assertFalse(resolved["fallback_performed"])

        self.catalog.write_text(LEGACY_HEADER.format(ready_dir=self.ready_dir), encoding="utf-8")
        legacy = list_data_catalog(self.catalog, status="READY", delivery="FILE", offset=0, limit=20)
        self.assertEqual([row["dataset_id"] for row in legacy["rows"]], ["legacy.file"])
        self.assertEqual(legacy["rows"][0]["delivery"], "LEGACY_PATH")
        legacy_ready = get_ready_data_source(self.catalog, dataset_id="legacy.file")
        self.assertTrue(legacy_ready["technical_check"]["paths"][0]["readable"])
        with self.assertRaises(DataCatalogError) as ctx:
            get_ready_data_source(self.catalog, dataset_id="legacy.blocked")
        self.assertEqual(ctx.exception.code, "DATASET_NOT_READY")

    def test_nonready_unknown_and_missing_ready_path_fail_without_fallback(self):
        with self.assertRaises(DataCatalogError) as ctx:
            get_ready_data_source(self.catalog, dataset_id="not.ready")
        self.assertEqual(ctx.exception.code, "DATASET_NOT_READY")
        with self.assertRaises(DataCatalogError) as ctx:
            get_ready_data_source(self.catalog, dataset_id="unknown")
        self.assertEqual(ctx.exception.code, "DATASET_NOT_LISTED")
        self.ready_dir.rmdir()
        with self.assertRaises(DataCatalogError) as ctx:
            get_ready_data_source(self.catalog, dataset_id="ready.file")
        self.assertEqual(ctx.exception.code, "DATA_SOURCE_UNREADABLE")

    def test_schema_tables_inside_catalog_sections_are_not_datasets(self):
        # DATA documents table/column lists in ordinary tables under §3 (e.g. §3.6 gst_intraday).
        self.write()
        text = self.catalog.read_text(encoding="utf-8").replace(
            "\n\n## 4.",
            "\n\n### 3.6 日内库\n\n| 名称 | 类型 | 列 |\n|---|---|---|\n| `ticks` | 视图 | `symbol, date` |\n"
            "| `bars_1m` | 表 | `minute` |\n\n说明文字。\n\n## 4.", 1)
        self.catalog.write_text(text, encoding="utf-8")
        parsed = read_data_catalog(self.catalog)
        self.assertNotIn("ticks", [row["dataset_id"] for row in parsed["entries"]])
        self.assertEqual(parsed["counts"]["READY"], 2)
        self.assertEqual(parsed["counts"]["NOT_READY"], 1)
        # a malformed row inside a real dataset table still fails closed
        self.catalog.write_text(text.replace("| `ready.api` | API | 实时报价 |", "| `ready.api` |", 1), encoding="utf-8")
        with self.assertRaises(DataCatalogError) as ctx:
            read_data_catalog(self.catalog)
        self.assertEqual(ctx.exception.code, "DATA_CATALOG_FORMAT_INVALID")

    def test_malformed_or_duplicate_catalog_fails_closed(self):
        self.write(duplicate=True)
        with self.assertRaises(DataCatalogError) as ctx:
            read_data_catalog(self.catalog)
        self.assertEqual(ctx.exception.code, "DATA_CATALOG_FORMAT_INVALID")
        # DATA row status is authoritative even if a human-facing section groups
        # mixed review states together.
        self.write(ready_status="REVIEW_REQUIRED")
        parsed = read_data_catalog(self.catalog)
        self.assertEqual(parsed["counts"]["REVIEW_REQUIRED"], 1)
        self.write(ready_status="BROKEN")
        with self.assertRaises(DataCatalogError) as ctx:
            read_data_catalog(self.catalog)
        self.assertEqual(ctx.exception.code, "DATA_CATALOG_FORMAT_INVALID")


class DataCatalogToolTests(CatalogFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.api = ArchivedMarketDataAPI(Inner(), self.output, data_catalog_path=self.catalog)

    def list_args(self):
        return {"status": "READY", "delivery": "ALL", "offset": 0, "limit": 20}

    def test_schema_capabilities_and_direct_boundary(self):
        schemas = {item["name"]: item for item in self.api.schemas()}
        self.assertIn("list_data_catalog", schemas)
        self.assertIn("get_ready_data_source", schemas)
        for name in ("list_data_catalog", "get_ready_data_source"):
            self.assertFalse(schemas[name]["parameters"]["additionalProperties"])
            self.assertTrue({"path", "root", "approve", "execute"}.isdisjoint(
                schemas[name]["parameters"]["properties"]))
        caps = self.api.call("get_capabilities", {})["data"]
        self.assertTrue(caps["data_catalog_read_available"])
        self.assertTrue(caps["data_catalog_configured"])
        self.assertFalse(caps["data_catalog_write_authorized"])
        listed = self.api.call("list_data_catalog", self.list_args())
        self.assertTrue(listed["ok"])
        self.assertEqual(listed["data"]["data_authority"], "DATA")
        ready = self.api.call("get_ready_data_source", {"dataset_id": "ready.file"})
        self.assertTrue(ready["ok"])
        blocked = self.api.call("get_ready_data_source", {"dataset_id": "not.ready"})
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error"]["code"], "DATASET_NOT_READY")

    def test_cli_matches_direct_api(self):
        cases = [
            (
                ["data-catalog-list", "--catalog", str(self.catalog)],
                self.api.call("list_data_catalog", self.list_args()),
                0,
            ),
            (
                ["data-catalog-get", "--catalog", str(self.catalog), "--dataset-id", "ready.file"],
                self.api.call("get_ready_data_source", {"dataset_id": "ready.file"}),
                0,
            ),
            (
                ["data-catalog-get", "--catalog", str(self.catalog), "--dataset-id", "not.ready"],
                self.api.call("get_ready_data_source", {"dataset_id": "not.ready"}),
                2,
            ),
        ]
        for argv, expected, code_expected in cases:
            out = io.StringIO()
            with self.subTest(argv=argv), contextlib.redirect_stdout(out):
                code = main(argv)
            self.assertEqual(code, code_expected)
            self.assertEqual(json.loads(out.getvalue()), expected)

    def test_normal_chat_has_catalog_tools_but_locked_spec_does_not(self):
        normal = ChatRuntime(self.output, local_data_only=True, data_catalog_path=self.catalog).api
        names = {tool["name"] for tool in normal.schemas()}
        self.assertIn("list_data_catalog", names)
        self.assertIn("get_ready_data_source", names)

        from test_qm50_archived_inputs import ArchivedQM50Tests
        f = ArchivedQM50Tests()
        self.addCleanup(f.doCleanups)
        f.setUp()
        locked = ChatRuntime(
            f.output,
            local_data_only=True,
            research_spec=f.sid,
            spec_source_workspace=f.source,
            data_catalog_path=self.catalog,
        ).api
        locked_names = {tool["name"] for tool in locked.schemas()}
        self.assertNotIn("list_data_catalog", locked_names)
        self.assertNotIn("get_ready_data_source", locked_names)


class DataCatalogMCPTests(CatalogFixture, IsolatedAsyncioTestCase):
    async def test_inprocess_and_stdio_mcp_are_readonly_and_match_direct(self):
        from mcp import Client, StdioServerParameters

        direct = build_mcp_api(self.output, data_catalog_path=self.catalog)
        expected = direct.call("get_ready_data_source", {"dataset_id": "ready.file"})
        stdio = StdioServerParameters(
            command=sys.executable,
            args=["-B", "-m", "quantlab.agent.mcp_server", "--output", str(self.output),
                  "--data-catalog-path", str(self.catalog)],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        for server in (build_mcp_server(self.output, data_catalog_path=self.catalog), stdio):
            async with Client(server, read_timeout_seconds=30) as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                for name in ("list_data_catalog", "get_ready_data_source"):
                    self.assertTrue(tools[name].annotations.read_only_hint)
                    self.assertFalse(tools[name].input_schema["additionalProperties"])
                got = await client.call_tool("get_ready_data_source", {"dataset_id": "ready.file"})
                self.assertFalse(got.is_error)
                self.assertEqual(json.loads(got.content[0].text), expected)
                bad = await client.call_tool(
                    "get_ready_data_source", {"dataset_id": "ready.file", "path": "/tmp/x"})
                self.assertTrue(bad.is_error)


if __name__ == "__main__":
    import unittest
    unittest.main()
