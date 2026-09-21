"""Real strategy archive API/CLI/MCP wiring over isolated synthetic archives."""
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import test_core
from test_strategy_package import package
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.peer_review import ReviewReadOnlyAPI
from quantlab.agent.research_spec_tools import ResearchSpecAPI
from quantlab.agent.strategy_package_cli import main
from quantlab.storage.codec import encode
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.trading.strategy_package import compile_strategy
from quantlab.workbench.jobs import execute, prepare

NAMES = {'list_strategy_runs', 'get_strategy_run', 'compare_strategy_runs'}

class Archives:
    def setUp(self):
        self.fixture = test_core.CoreTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.output = self.fixture.root / 'run-tools'; self.output.mkdir()
        self.left = execute(prepare(compile_strategy(package())['spec']), self.fixture.root, self.output)
        self.right = execute(prepare(compile_strategy(package(max_position=0.5))['spec']), self.fixture.root, self.output)
        self.api = ReadOnlyResearchAPI(self.output)

class StrategyRunToolTests(Archives, unittest.TestCase):
    def test_list_get_compare_use_actual_archive_and_do_not_create_jobs(self):
        # ChatStore initialization has its own existing journal setup; only the
        # subsequent archive tools are being asserted to perform no writes.
        chat = ChatRuntime(self.output, local_data_only=True)
        before = snapshot_tree(self.output, self.left.run_id)
        names = sorted(str(p) for p in self.output.rglob('*'))
        with patch('quantlab.data.mqc.MQCParquetProvider.load', side_effect=AssertionError('live data read')):
            for api in (self.api, chat.api):
                listed = api.call('list_strategy_runs', {'query':'tests.f3b', 'offset':0, 'limit':20})
                self.assertTrue(listed['ok'], listed)
                self.assertEqual({row['run_id'] for row in listed['data']['runs']}, {self.left.run_id,self.right.run_id})
                self.assertTrue(all(row['verification']=='metadata_only' for row in listed['data']['runs']))
                got = api.call('get_strategy_run', {'run_id':self.left.run_id})
                self.assertTrue(got['ok'], got)
                self.assertEqual(got['data']['verification'], 'archive_internal_consistency')
                self.assertNotIn('package', got['data'])
                compared = api.call('compare_strategy_runs', {'left_run_id':self.left.run_id,'right_run_id':self.right.run_id})
                self.assertTrue(compared['ok'], compared)
                self.assertTrue(compared['data']['comparable'], compared['data']['blockers'])
                self.assertEqual(compared['data']['scope'],'DESCRIPTIVE_ONLY')
                self.assertEqual({r['run_id'] for r in compared['evidence']},{self.left.run_id,self.right.run_id})
        self.assertEqual(before, snapshot_tree(self.output,self.left.run_id))
        self.assertEqual(names, sorted(str(p) for p in self.output.rglob('*')))
        self.assertFalse((self.output/'_jobs').exists())

    def test_partial_directory_and_corrupt_selected_archive_are_disclosed(self):
        bad=self.output/str(uuid4()); bad.mkdir(); (bad/'experiment.json').write_text('{bad')
        listed=self.api.call('list_strategy_runs',{'query':'','offset':0,'limit':20})
        self.assertTrue(listed['ok'],listed); self.assertTrue(listed['data']['incomplete'])
        self.assertTrue(listed['data']['errors']); self.assertTrue(listed['warnings'])
        path=self.left.artifact_path/'experiment.json'; record=json.loads(path.read_text())
        del record['fills'][0]['tax']; path.write_text(encode(record))
        self.assertFalse(self.api.call('get_strategy_run',{'run_id':self.left.run_id})['ok'])
        self.assertFalse(self.api.call('compare_strategy_runs',{'left_run_id':self.left.run_id,'right_run_id':self.right.run_id})['ok'])

    def test_permissions_and_invalid_arguments_remain_bounded(self):
        reviewer=ReviewReadOnlyAPI(self.output)
        self.assertFalse(NAMES & {r['name'] for r in reviewer.schemas()})
        caps=reviewer.call('get_capabilities',{})
        self.assertFalse(caps['data']['strategy_result_comparison_available'])
        for name in NAMES: self.assertEqual(reviewer.call(name,{})['error']['code'],'REVIEW_TOOL_DENIED')
        with patch('quantlab.agent.research_spec_tools.ResearchSpecStore.get'):
            bound=ResearchSpecAPI(self.api,self.output,active_spec='synthetic-bound-spec')
        self.assertFalse(NAMES & {r['name'] for r in bound.schemas()})
        for name in NAMES: self.assertEqual(bound.call(name,{})['error']['code'],'SPEC_SUBSTITUTION_REJECTED')
        for args in ({'query':'','offset':True,'limit':20},{'query':'','offset':0,'limit':21}):
            self.assertFalse(self.api.call('list_strategy_runs',args)['ok'])
        self.assertFalse(self.api.call('get_strategy_run',{'run_id':'../escape'})['ok'])
        self.assertFalse(self.api.call('approve_strategy_run',{})['ok'])

    def test_original_symlink_output_is_rejected_before_chat_or_mcp_setup(self):
        from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
        link = self.fixture.root / 'linked-output'
        link.symlink_to(self.output, target_is_directory=True)
        before = sorted(str(p) for p in self.output.rglob('*'))
        factories = [ReadOnlyResearchAPI, lambda p: ChatRuntime(p, local_data_only=True),
                     build_mcp_api, build_mcp_server]
        for factory in factories:
            with self.subTest(factory=factory), self.assertRaisesRegex(ValueError, 'symlink'):
                factory(link)
        self.assertEqual(before, sorted(str(p) for p in self.output.rglob('*')))

    def test_cost_mismatch_remains_explicit_with_null_deltas(self):
        changed=package(); changed['spec']['execution']['commission_bps']=8
        other=execute(prepare(compile_strategy(changed)['spec']),self.fixture.root,self.output)
        result=self.api.call('compare_strategy_runs',{'left_run_id':self.left.run_id,'right_run_id':other.run_id})
        self.assertTrue(result['ok'],result);self.assertFalse(result['data']['comparable'])
        self.assertIn('execution_assumptions_or_costs_differ',result['data']['blockers'])
        self.assertTrue(all(row['delta'] is None for row in result['data']['metrics']))

    def test_large_comparison_is_rejected_without_dropping_blockers(self):
        with patch('quantlab.trading.strategy_comparison.compare_strategy_runs',return_value={'comparable':False,'blockers':['x'*25000]}):
            result=self.api.call('compare_strategy_runs',{'left_run_id':self.left.run_id,'right_run_id':self.right.run_id})
        self.assertFalse(result['ok']); self.assertEqual(result['error']['code'],'RESULT_TOO_LARGE'); self.assertIsNone(result['data'])

    def test_cli_discovery_get_and_failure_codes(self):
        def call(args):
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream): code=main(args)
            return code,json.loads(stream.getvalue())
        code,value=call(['list-runs','--output',str(self.output)])
        self.assertEqual(code,0); self.assertEqual(len(value['data']['runs']),2)
        code,value=call(['get-run','--output',str(self.output),'--run-id',self.left.run_id])
        self.assertEqual(code,0); self.assertEqual(value['data']['package']['strategy_key'],'tests.f3b')
        bad=self.output/str(uuid4());bad.mkdir();(bad/'experiment.json').write_text('bad')
        code,value=call(['list-runs','--output',str(self.output)])
        self.assertEqual(code,3); self.assertTrue(value['data']['incomplete'])
        code,value=call(['get-run','--output',str(self.output),'--run-id','../x'])
        self.assertEqual(code,2); self.assertFalse(value['ok'])

class StrategyRunMCPTests(Archives, unittest.IsolatedAsyncioTestCase):
    async def test_in_process_and_stdio_read_same_archive_without_write_tools(self):
        from mcp import Client,StdioServerParameters
        from quantlab.agent.mcp_server import build_mcp_server
        endpoints=[build_mcp_server(self.output),StdioServerParameters(command=sys.executable,args=['-B','-m','quantlab.agent.mcp_server','--output',str(self.output)])]
        for endpoint in endpoints:
            async with Client(endpoint,read_timeout_seconds=30) as client:
                tools=(await client.list_tools()).tools; names=[r.name for r in tools]
                self.assertEqual(len(names),len(set(names)));self.assertTrue(NAMES<=set(names))
                self.assertNotIn('submit_granted_experiment',names)
                for tool in tools:
                    if tool.name in NAMES:self.assertTrue(tool.annotations.read_only_hint)
                got=await client.call_tool('get_strategy_run',{'run_id':self.left.run_id})
                result=json.loads(got.content[0].text);self.assertTrue(result['ok'],result)
                self.assertEqual(result['data']['run_id'],self.left.run_id)
                listed=await client.call_tool('list_strategy_runs',{'query':'tests.f3b','offset':0,'limit':20})
                self.assertEqual(len(json.loads(listed.content[0].text)['data']['runs']),2)
        self.assertFalse((self.output/'_jobs').exists())

if __name__=='__main__':unittest.main()
