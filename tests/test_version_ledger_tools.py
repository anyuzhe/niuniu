"""F21 version-ledger API/CLI/Chat/MCP boundaries; synthetic-only."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from test_version_ledger import VersionLedgerFixture
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.data_review_cli import main
from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
from quantlab.data.version_ledger import SELECTION_CONTRACT

NAMES = {
    "get_version_ledger_manifest",
    "query_version_ledger",
    "get_version_selection_contract",
    "preview_version_selection",
}


class Setup(VersionLedgerFixture):
    def setUp(self):
        super().setUp()
        self.output = self.root / "output"; self.output.mkdir()
        self.api = build_mcp_api(self.output, version_ledger_binding=self.binding)

    def flags(self):
        return [
            "--version-ledger-jsonl", str(self.jsonl),
            "--version-ledger-summary", str(self.summary),
            "--version-ledger-jsonl-sha256", self.binding.jsonl_sha256,
            "--version-ledger-summary-sha256", self.binding.summary_sha256,
        ]

    def query_args(self):
        return {"domain":"corporate_action","event_type":"rights_issue","event_id":"",
                "source_id":"tdx","offset":0,"limit":20}

    def preview_args(self):
        request = {
            "contract": SELECTION_CONTRACT,
            "event_id": self.rows[0]["event_id"],
            "source_id": "tdx",
            "policy": "latest_observed_revision_as_of_v1",
            "revision_id": "",
            "as_of": "2020-01-04T00:00:00+00:00",
        }
        return {"request_json": json.dumps(request)}


class VersionLedgerToolTests(Setup, TestCase):
    def test_schema_capabilities_and_unbound_fail_closed_without_discovery(self):
        schemas = {tool["name"]:tool for tool in self.api.schemas()}
        self.assertTrue(NAMES <= set(schemas))
        caps = self.api.call("get_capabilities", {})["data"]
        self.assertTrue(caps["version_ledger_available"])
        self.assertTrue(caps["version_ledger_configured"])
        self.assertFalse(caps["version_ledger_write_authorized"])
        self.assertFalse(caps["version_cross_source_merge_authorized"])
        for name in NAMES:
            self.assertFalse(schemas[name]["parameters"]["additionalProperties"])
            self.assertTrue({"path","root","hash","sha256","approve","execute"}.isdisjoint(
                schemas[name]["parameters"]["properties"]))
        unbound = build_mcp_api(self.output)
        with patch("quantlab.data.version_ledger._read_pinned",
                   side_effect=AssertionError("unbound must not discover files")) as read:
            result = unbound.call("get_version_ledger_manifest", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "VERSION_LEDGER_NOT_CONFIGURED")
        read.assert_not_called()

    def test_direct_manifest_query_contract_and_preview(self):
        manifest = self.api.call("get_version_ledger_manifest", {})
        self.assertTrue(manifest["ok"])
        self.assertEqual((manifest["data"]["records"], manifest["data"]["revisions"]), (4,3))
        query = self.api.call("query_version_ledger", self.query_args())
        self.assertTrue(query["ok"]); self.assertEqual(query["data"]["pagination"]["total"], 3)
        contract = self.api.call("get_version_selection_contract", {})
        self.assertTrue(contract["ok"]); self.assertFalse(contract["data"]["implicit_latest"])
        preview = self.api.call("preview_version_selection", self.preview_args())
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["data"]["status"], "ready_for_review")
        self.assertEqual(preview["data"]["selected"]["source_revision_key"], "r2")
        self.assertFalse(preview["data"]["merge_authorized"])
        self.assertFalse(preview["data"]["publication_authorized"])

    def test_cli_matches_direct_api(self):
        cases = [
            (["version-ledger-manifest", *self.flags()],
             self.api.call("get_version_ledger_manifest", {}), 0),
            (["version-ledger-query", *self.flags(), "--domain","corporate_action",
              "--event-type","rights_issue","--source-id","tdx"],
             self.api.call("query_version_ledger", self.query_args()), 0),
            (["version-selection-contract"],
             self.api.call("get_version_selection_contract", {}), 0),
            (["version-selection-preview", *self.flags(),
              "--request-json", self.preview_args()["request_json"]],
             self.api.call("preview_version_selection", self.preview_args()), 0),
        ]
        for argv, expected, code_expected in cases:
            out = io.StringIO()
            with self.subTest(command=argv[0]), contextlib.redirect_stdout(out):
                code = main(argv)
            self.assertEqual(code, code_expected)
            self.assertEqual(json.loads(out.getvalue()), expected)

    def test_formal_chat_reads_versions_without_jobs_or_writes(self):
        from test_agent_chat import FakeProvider
        from quantlab.agent.model_config import ModelConfig
        before = {p.name:p.read_bytes() for p in (self.jsonl,self.summary)}
        runtime = ChatRuntime(self.output, local_data_only=True, version_ledger_binding=self.binding)
        provider = FakeProvider([
            ("get_version_ledger_manifest", {}),
            ("query_version_ledger", self.query_args()),
            ("preview_version_selection", self.preview_args()),
        ])
        result = runtime.send(runtime.store.create(), "只读核对版本，不合并来源也不重建",
                              ModelConfig(max_context_chars=180000), allow_send=True, provider=provider)
        self.assertEqual(result["tool_calls"], 3)
        self.assertTrue(all(item["ok"] for item in provider.results))
        self.assertEqual(provider.results[-1]["data"]["status"], "ready_for_review")
        self.assertFalse(provider.results[-1]["data"]["reconstruction_authorized"])
        self.assertEqual(before, {p.name:p.read_bytes() for p in (self.jsonl,self.summary)})
        self.assertFalse((self.output/"_jobs").exists())

    def test_locked_qm50_and_peer_reviewer_do_not_gain_f21_tools(self):
        from quantlab.agent.peer_review import ReviewReadOnlyAPI
        from test_qm50_archived_inputs import ArchivedQM50Tests
        f = ArchivedQM50Tests(); self.addCleanup(f.doCleanups); f.setUp()
        locked = ChatRuntime(f.output, local_data_only=True, research_spec=f.sid,
                             spec_source_workspace=f.source, version_ledger_binding=self.binding).api
        for api in (locked, ReviewReadOnlyAPI(self.output, None)):
            names = {tool["name"] for tool in api.schemas()}
            self.assertTrue(NAMES.isdisjoint(names))
            for name in NAMES:
                self.assertFalse(api.call(name, {})["ok"])

    def test_extra_fields_and_mutation_are_rejected(self):
        bad = self.api.call("query_version_ledger", {**self.query_args(), "path":"/tmp/x"})
        self.assertFalse(bad["ok"]); self.assertEqual(bad["error"]["code"], "INVALID_ARGUMENT")
        self.assertTrue(self.api.call("get_version_ledger_manifest", {})["ok"])
        self.jsonl.write_bytes(self.jsonl.read_bytes()+b"\n")
        changed = self.api.call("get_version_ledger_manifest", {})
        self.assertFalse(changed["ok"])

    def test_model_cannot_mix_source_selection_or_implicit_latest(self):
        request = json.loads(self.preview_args()["request_json"])
        request["source_id"] = ""
        result = self.api.call("preview_version_selection", {"request_json":json.dumps(request)})
        self.assertFalse(result["ok"])
        request = json.loads(self.preview_args()["request_json"])
        request["policy"] = "latest"
        result = self.api.call("preview_version_selection", {"request_json":json.dumps(request)})
        self.assertFalse(result["ok"])


class VersionLedgerMCPTests(Setup, IsolatedAsyncioTestCase):
    async def test_inprocess_and_stdio_restart_match_direct_boundary(self):
        from mcp import Client, StdioServerParameters
        expected = self.api.call("query_version_ledger", self.query_args())
        params = StdioServerParameters(
            command=sys.executable,
            args=["-B","-m","quantlab.agent.mcp_server","--output",str(self.output),*self.flags()],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE":"1"},
        )
        servers = [
            build_mcp_server(self.output, version_ledger_binding=self.binding),
            params, params,
        ]
        for server in servers:
            async with Client(server, read_timeout_seconds=45) as client:
                tools = {tool.name:tool for tool in (await client.list_tools()).tools}
                for name in NAMES:
                    self.assertTrue(tools[name].annotations.read_only_hint)
                    self.assertFalse(tools[name].input_schema["additionalProperties"])
                got = await client.call_tool("query_version_ledger", self.query_args())
                self.assertFalse(got.is_error)
                self.assertEqual(json.loads(got.content[0].text), expected)
                bad = await client.call_tool("query_version_ledger", {**self.query_args(),"hash":"0"*64})
                self.assertTrue(bad.is_error)
        self.assertFalse((self.output/"_jobs").exists())


if __name__ == "__main__":
    import unittest
    unittest.main()
