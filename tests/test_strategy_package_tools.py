"""Model-facing strategy compilation is exact, bounded, and never execution authority."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.peer_review import ReviewReadOnlyAPI
from quantlab.agent.research_spec_tools import ResearchSpecAPI
from quantlab.storage.codec import encode
from quantlab.workbench.jobs import prepare
from test_strategy_package_cli import package_fixture


class StrategyPackageToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.api = ReadOnlyResearchAPI(self.root)

    def test_contract_matches_compiler_and_no_data_is_read(self):
        from quantlab.trading.strategy_package import FORMAT, LIFECYCLE, compile_strategy
        contract = self.api.call('get_strategy_package_contract', {})
        self.assertTrue(contract['ok'], contract)
        self.assertEqual(contract['data']['format'], FORMAT)
        self.assertEqual(contract['data']['lifecycle'], LIFECYCLE)
        self.assertFalse(contract['data']['execution_authorized'])
        package = package_fixture()
        with patch('quantlab.data.mqc.MQCParquetProvider.load', side_effect=AssertionError('no market reads')):
            result = self.api.call('preview_strategy_package', {'package_json': encode(package)})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['data']['spec'], compile_strategy(package)['spec'])
        self.assertEqual(prepare(result['data']['spec']).mode, 'execution')
        self.assertFalse(result['data']['execution_authorized'])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_input_and_large_result_never_return_truncated_execution_spec(self):
        for text in ('{"format":"x","format":"y"}', '{"x":Infinity}', '[]'):
            value = self.api.call('preview_strategy_package', {'package_json': text})
            self.assertFalse(value['ok'], value)
        from quantlab.trading.strategy_package import compile_strategy
        large = compile_strategy(package_fixture())
        large['spec']['fixture_large_output'] = 'x' * 25000
        with patch('quantlab.trading.strategy_package.compile_strategy', return_value=large):
            result = self.api.call('preview_strategy_package', {'package_json': encode(package_fixture())})
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'RESULT_TOO_LARGE')
        self.assertIsNone(result['data'])

    def test_chat_and_reviewer_read_permissions_do_not_bypass_qm50_binding(self):
        names = {'get_strategy_package_contract', 'preview_strategy_package'}
        for api in (ChatRuntime(self.root, local_data_only=True).api, ReviewReadOnlyAPI(self.root)):
            self.assertTrue(names <= {tool['name'] for tool in api.schemas()})
        with patch('quantlab.agent.research_spec_tools.ResearchSpecStore.get'):
            strict = ResearchSpecAPI(self.api, self.root, active_spec='synthetic-spec')
        self.assertFalse(names & {tool['name'] for tool in strict.schemas()})
        for name in names:
            self.assertEqual(strict.call(name, {})['error']['code'], 'SPEC_SUBSTITUTION_REJECTED')
        self.assertFalse(self.api.call('approve_strategy_package', {})['ok'])


try:
    from mcp import Client
    from quantlab.agent.mcp_server import build_mcp_server
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


@unittest.skipUnless(MCP_AVAILABLE, 'optional MCP dependency unavailable')
class StrategyPackageMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_protocol_lists_and_previews_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = build_mcp_server(root)
            async with Client(server) as client:
                listing = await client.list_tools()
                names = [tool.name for tool in listing.tools]
                self.assertEqual(len(names), len(set(names)))
                tool = next(t for t in listing.tools if t.name == 'preview_strategy_package')
                self.assertTrue(tool.annotations.read_only_hint)
                result = await client.call_tool('preview_strategy_package', {'package_json': encode(package_fixture())})
                self.assertFalse(result.is_error)
                value = json.loads(result.content[0].text)
                self.assertTrue(value['ok'], value)
                self.assertEqual(prepare(value['data']['spec']).mode, 'execution')
                self.assertNotIn('submit_granted_experiment', names)
                self.assertNotIn('approve_strategy_package', names)
            self.assertFalse((root / '_jobs').exists())
            self.assertFalse((root / '_agent' / 'proposals.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
