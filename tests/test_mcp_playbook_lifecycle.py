"""Real MCP transport over synthetic Playbook evidence; no market network or orders."""
import json
import sys
import unittest
from importlib.util import find_spec
from pathlib import Path

MCP_AVAILABLE = find_spec('mcp') is not None
if MCP_AVAILABLE:
    from mcp import Client, StdioServerParameters
    from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
    from quantlab.agent.playbook_tools import SELECTION_OUTCOME_TOOLS
    from quantlab.agent.peer_review import ReviewReadOnlyAPI
    import test_selection_outcomes as fixtures

@unittest.skipUnless(MCP_AVAILABLE, 'optional mcp dependency is not installed')
class MCPPlaybookLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = fixtures.SelectionOutcomeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.output = self.fixture.output
        self.fixture.capture_days(range(1, 6))
        self.fixture.capture_reference(5)
        self.selection = self.fixture.selection()
        self.fixture.service().build(self.selection['selection_id'], [1, 2])

    async def test_transport_lists_reads_and_reopens_same_selection(self):
        before = {str(p): p.read_bytes() for p in
                  (self.output / '_trading' / 'selection_outcomes').rglob('D*.json')}
        endpoints = [build_mcp_server(self.output), StdioServerParameters(
            command=sys.executable, args=['-B', '-m', 'quantlab.agent.mcp_server',
                                         '--output', str(self.output)])]
        for endpoint in endpoints:
            async with Client(endpoint, read_timeout_seconds=30) as client:
                listed = await client.list_tools()
                names = [tool.name for tool in listed.tools]
                self.assertEqual(len(names), len(set(names)))
                self.assertTrue(set(SELECTION_OUTCOME_TOOLS) <= set(names))
                self.assertIn('get_playbook_case_bundle', names)
                self.assertIn('get_market_snapshot_provider_status', names)
                for tool in listed.tools:
                    if tool.name in SELECTION_OUTCOME_TOOLS:
                        self.assertTrue(tool.annotations.read_only_hint)
                result = await client.call_tool('get_selection_outcome_review',
                    {'selection_id': self.selection['selection_id']})
                self.assertFalse(result.is_error)
                body = json.loads(result.content[0].text)
                self.assertTrue(body['ok'], body)
                self.assertFalse(body['data']['incomplete'])
                self.assertEqual(body['data']['selection_id'], self.selection['selection_id'])
                self.assertEqual(len(body['data']['records']), 2)
                definition = await client.call_tool('get_playbook_definition',
                    {'definition_id': self.fixture.definition['definition_id']})
                self.assertTrue(json.loads(definition.content[0].text)['ok'])
        self.assertEqual(before, {path: Path(path).read_bytes() for path in before})
        self.assertFalse((self.output / '_jobs').exists())

    async def test_corrupt_review_is_disclosed_through_mcp(self):
        path = self.output / '_trading' / 'selection_outcomes' / self.selection['selection_id'] / 'D1.json'
        path.write_text('synthetic corrupt review', encoding='utf-8')
        async with Client(build_mcp_server(self.output)) as client:
            result = await client.call_tool('get_selection_outcome_summary',
                {'definition_id': '', 'kind': '', 'frame': ''})
            body = json.loads(result.content[0].text)
            self.assertTrue(body['ok'], body)
            self.assertTrue(body['data']['incomplete'])
            self.assertEqual(body['data']['errors'][0]['code'], 'CORRUPT_REVIEW')
            self.assertTrue(any('不完整' in value for value in body['warnings']))

    async def test_readonly_extension_does_not_expand_execution_or_reviewer_rights(self):
        api = build_mcp_api(self.output)
        names = {tool['name'] for tool in api.schemas()}
        caps = api.call('get_capabilities', {})
        self.assertTrue(caps['ok'])
        self.assertTrue(caps['data'].get('selection_outcome_available'))
        self.assertFalse(caps['data']['selection_outcome_write_model'])
        for name in ('submit_granted_experiment', 'approve_proposal', 'create_playbook_definition',
                     'run_shell', 'collect_tdx_data', 'execute_paper_plan'):
            self.assertNotIn(name, names)
            self.assertFalse(api.call(name, {})['ok'])
        reviewer_names = {tool['name'] for tool in ReviewReadOnlyAPI(self.output, self.output).schemas()}
        self.assertFalse(set(SELECTION_OUTCOME_TOOLS) & reviewer_names)

if __name__ == '__main__':
    unittest.main()
