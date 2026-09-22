"""F17 registered Chat/API/CLI/MCP paths on synthetic deliveries only."""
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import patch
import contextlib
import io
import json
import os
import sys

from test_rights_candidates import CandidateFixture,make_row
from quantlab.agent.mcp_server import build_mcp_api,build_mcp_server
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.data_review_cli import main
from quantlab.agent.archived_data_tools import MAX_RESPONSE_BYTES
from quantlab.data.rights_candidates import rights_binding_from_arguments
from quantlab.storage.codec import encode

NAMES={'get_rights_candidate_manifest','query_rights_candidates'}

class Setup(CandidateFixture):
    def setUp(self):
        super().setUp();self.output=self.root/'out';self.output.mkdir()
        self.api=build_mcp_api(self.output,rights_candidate_binding=self.binding)
    def flags(self):
        return ['--rights-csv',str(self.csv),'--rights-summary',str(self.summary),
                '--rights-csv-sha256',self.binding.csv_sha256,'--rights-summary-sha256',self.binding.summary_sha256]
    def cli(self,command,*extra):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):code=main([command,*self.flags(),*extra])
        return code,json.loads(output.getvalue())

class RightsCandidateToolTests(Setup,TestCase):
    def test_unbound_not_discovered_from_paths_or_data_root(self):
        api=build_mcp_api(self.output,self.root)
        with patch('quantlab.data.rights_candidates._read',side_effect=AssertionError('No path read')) as read:
            res=api.call('get_rights_candidate_manifest',{})
            self.assertFalse(res['ok']);self.assertEqual(res['error']['code'],'CANDIDATE_NOT_CONFIGURED');read.assert_not_called()
    def test_registered_tools_and_permissions(self):
        defs=self.api.schemas();names=[t['name'] for t in defs]
        self.assertEqual(len(names),len(set(names)));self.assertTrue(NAMES<=set(names))
        cap=self.api.call('get_capabilities',{})['data']
        self.assertTrue(cap['rights_candidate_configured']);self.assertFalse(cap['rights_candidate_write_authorized'])
        for d in defs:
            if d['name'] in NAMES:
                self.assertFalse(d['parameters']['additionalProperties'])
                self.assertTrue({'path','csv_path','data_root','csv_sha256','summary_sha256'}.isdisjoint(d['parameters']['properties']))
        for invalid in ({'path':str(self.csv)},{'confirm':True}):
            self.assertFalse(self.api.call('get_rights_candidate_manifest',invalid)['ok'])
    def test_cli_matches_api_and_known_incomplete_not_execution(self):
        code,got=self.cli('rights-manifest');expected=self.api.call('get_rights_candidate_manifest',{})
        self.assertEqual(code,0);self.assertEqual(got,expected)
        self.assertEqual(got['data']['unresolved_rows'],3);self.assertFalse(got['data']['publication_authorized'])
        code,got=self.cli('rights-query','--start',self.args['start'],'--end',self.args['end'],'--status','conflicts')
        expected=self.api.call('query_rights_candidates',{**self.args,'status':'conflicts'})
        self.assertEqual(code,0);self.assertEqual(got,expected);self.assertFalse((self.output/'_jobs').exists())
    def test_cli_bad_hash_and_partial_binding(self):
        code,got=self.cli('rights-manifest','--rights-csv-sha256','0'*64)
        self.assertEqual(code,2);self.assertEqual(got['error']['code'],'CANDIDATE_HASH_MISMATCH')
        from argparse import Namespace
        with self.assertRaises(ValueError):rights_binding_from_arguments(Namespace(rights_csv=str(self.csv)))
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(['rights-manifest'])
    def test_runtime_host_binding_native_tools_only(self):
        from test_agent_chat import FakeProvider
        from quantlab.agent.model_config import ModelConfig
        before={str(p):p.read_bytes() for p in (self.csv,self.summary)}
        runtime=ChatRuntime(self.output,local_data_only=True,rights_candidate_binding=self.binding)
        provider=FakeProvider([('get_rights_candidate_manifest',{}),('query_rights_candidates',self.args)])
        r=runtime.send(runtime.store.create(),'仅核对候选来源，不运行研究',
            ModelConfig(max_context_chars=150000),allow_send=True,provider=provider)
        self.assertEqual(r['tool_calls'],2);self.assertTrue(all(x['ok'] for x in provider.results),provider.results)
        self.assertEqual(before,{str(p):p.read_bytes() for p in (self.csv,self.summary)})
        self.assertFalse((self.output/'_jobs').exists());self.assertFalse((self.output/'_approval_input_freezes').exists())
    def test_reviewer_and_locked_qm50_still_deny(self):
        from quantlab.agent.peer_review import ReviewReadOnlyAPI
        from test_qm50_archived_inputs import ArchivedQM50Tests
        f=ArchivedQM50Tests();self.addCleanup(f.doCleanups);f.setUp()
        locked=ChatRuntime(f.output,local_data_only=True,research_spec=f.sid,
            spec_source_workspace=f.source,rights_candidate_binding=self.binding).api
        for api in (locked,ReviewReadOnlyAPI(self.output,None)):
            self.assertTrue(NAMES.isdisjoint({d['name'] for d in api.schemas()}))
            for name in NAMES:self.assertFalse(api.call(name,{})['ok'])
    def test_oversized_response_refused_and_smaller_page_works(self):
        self.rows=[make_row(i) for i in range(1,11)]
        for r in self.rows:r['note']='x'*8000
        self.save();api=build_mcp_api(self.output,rights_candidate_binding=self.binding)
        r=api.call('query_rights_candidates',self.args)
        self.assertFalse(r['ok']);self.assertEqual(r['error']['code'],'RESULT_TOO_LARGE')
        self.assertLessEqual(len(encode(r).encode()),MAX_RESPONSE_BYTES)
        small=api.call('query_rights_candidates',{**self.args,'limit':1})
        self.assertTrue(small['ok']);self.assertEqual(small['data']['pagination']['next_offset'],1)
    def test_max_supported_single_unicode_record_is_retrievable(self):
        self.rows[0]['note']='字'*6500;self.save()
        api=build_mcp_api(self.output,rights_candidate_binding=self.binding)
        result=api.call('query_rights_candidates',{**self.args,'limit':1})
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['data']['rows'][0]['fields']['note'],self.rows[0]['note'])
        self.assertLessEqual(len(encode(result).encode()),MAX_RESPONSE_BYTES)
    def test_new_bytes_same_runtime_fail_not_cache(self):
        runtime=ChatRuntime(self.output,local_data_only=True,rights_candidate_binding=self.binding)
        self.assertTrue(runtime.api.call('get_rights_candidate_manifest',{})['ok'])
        self.csv.write_bytes(self.csv.read_bytes()+b'\n')
        self.assertFalse(runtime.api.call('get_rights_candidate_manifest',{})['ok'])
    def test_bad_row_outside_page_not_silently_hidden(self):
        self.rows[2]['theo_price_tdx']='900';self.save();api=build_mcp_api(self.output,rights_candidate_binding=self.binding)
        r=api.call('query_rights_candidates',{**self.args,'status':'exact','limit':1})
        self.assertFalse(r['ok']);self.assertIsNone(r['data'])

class RightsCandidateMCPTests(Setup,IsolatedAsyncioTestCase):
    async def test_real_stdio_same_result_restart_and_extra_fields_rejected(self):
        from mcp import Client,StdioServerParameters
        params=StdioServerParameters(command=sys.executable,args=['-B','-m','quantlab.agent.mcp_server',
            '--output',str(self.output),*self.flags()],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        expected=self.api.call('query_rights_candidates',self.args)
        for server in (build_mcp_server(self.output,rights_candidate_binding=self.binding),params,params):
            async with Client(server,read_timeout_seconds=30) as client:
                tools={d.name:d for d in (await client.list_tools()).tools}
                for name in NAMES:
                    self.assertTrue(tools[name].annotations.read_only_hint)
                    self.assertIs(tools[name].input_schema['additionalProperties'],False)
                result=await client.call_tool('query_rights_candidates',self.args)
                self.assertEqual(json.loads(result.content[0].text),expected)
                bad=await client.call_tool('query_rights_candidates',{**self.args,'path':str(self.root)})
                self.assertTrue(bad.is_error)
        self.assertFalse((self.output/'_jobs').exists())
