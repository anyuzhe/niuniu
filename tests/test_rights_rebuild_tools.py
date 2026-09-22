"""F18 real API/CLI/MCP and scripted ChatRuntime, never business model or data."""
import contextlib
import io
import json
import os
import sys
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import patch

from test_rights_rebuild_preview import PreviewFixture
from test_rights_candidates import make_row
from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.data_review_cli import main
from quantlab.agent.archived_data_tools import MAX_RESPONSE_BYTES
from quantlab.storage.codec import encode

NAMES={'get_rights_rebuild_contract','preview_rights_rebuild'}


class Setup(PreviewFixture):
    def setUp(self):
        super().setUp();self.output=self.root/'output';self.output.mkdir()
        self.api=build_mcp_api(self.output,rights_candidate_binding=self.binding)
    def flags(self):
        return ['--rights-csv',str(self.csv),'--rights-summary',str(self.summary),
                '--rights-csv-sha256',self.binding.csv_sha256,'--rights-summary-sha256',self.binding.summary_sha256]
    def cli(self, request):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            code=main(['rights-preview',*self.flags(),'--request-json',json.dumps(request)])
        return code,json.loads(stream.getvalue())
    def call(self,request):
        return self.api.call('preview_rights_rebuild',{'request_json':json.dumps(request)})


class RightsRebuildToolTests(Setup,TestCase):
    def test_contract_available_without_bound_files_and_no_discovery(self):
        api=build_mcp_api(self.output)
        with patch('quantlab.data.rights_candidates._read',side_effect=AssertionError('no file read')) as read:
            result=api.call('get_rights_rebuild_contract',{})
            self.assertTrue(result['ok']);read.assert_not_called()
            blocked=api.call('preview_rights_rebuild',{'request_json':json.dumps(self.request())})
            self.assertFalse(blocked['ok']);self.assertEqual(blocked['error']['code'],'CANDIDATE_NOT_CONFIGURED')
    def test_cli_contract_and_success_blocked_error_exit_codes(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=main(['rights-preview-contract'])
        self.assertEqual(code,0);self.assertEqual(json.loads(out.getvalue()),self.api.call('get_rights_rebuild_contract',{}))
        for request,expected in ((self.ready_request(),0),(self.request(),3),({**self.request(),'publish':True},2)):
            code,got=self.cli(request);self.assertEqual(code,expected,got);self.assertEqual(got,self.call(request))
    def test_schema_closed_no_path_no_write_commands(self):
        tools=self.api.schemas();names=[t['name'] for t in tools]
        self.assertEqual(len(names),len(set(names)));self.assertTrue(NAMES<=set(names))
        for tool in tools:
            if tool['name'] in NAMES:
                self.assertFalse(tool['parameters']['additionalProperties'])
                self.assertTrue({'path','csv_sha256','execute','approve'}.isdisjoint(tool['parameters']['properties']))
        caps=self.api.call('get_capabilities',{})['data']
        self.assertTrue(caps['rights_rebuild_preview_available']);self.assertFalse(caps['rights_rebuild_execution_available'])
        self.assertFalse(caps['adjustment_rebuild_authorized'])
    def test_new_tools_do_not_expand_reviewer_or_qm50(self):
        from quantlab.agent.peer_review import ReviewReadOnlyAPI
        from test_qm50_archived_inputs import ArchivedQM50Tests
        f=ArchivedQM50Tests();self.addCleanup(f.doCleanups);f.setUp()
        locked=ChatRuntime(f.output,local_data_only=True,research_spec=f.sid,
            spec_source_workspace=f.source,rights_candidate_binding=self.binding).api
        for api in (locked,ReviewReadOnlyAPI(self.output,None)):
            self.assertTrue(NAMES.isdisjoint({t['name'] for t in api.schemas()}))
            for name in NAMES:self.assertFalse(api.call(name,{})['ok'])
    def test_formal_chat_tool_dispatch_preserves_blockers_and_creates_no_job(self):
        from test_agent_chat import FakeProvider
        from quantlab.agent.model_config import ModelConfig
        before={p.name:p.read_bytes() for p in (self.csv,self.summary)}
        runtime=ChatRuntime(self.output,local_data_only=True,rights_candidate_binding=self.binding)
        provider=FakeProvider([('get_rights_rebuild_contract',{}),
            ('preview_rights_rebuild',{'request_json':json.dumps(self.request())})])
        result=runtime.send(runtime.store.create(),'核对完整候选范围草案，不批准执行',
            ModelConfig(max_context_chars=150000),allow_send=True,provider=provider)
        self.assertEqual(result['tool_calls'],2);self.assertTrue(all(r['ok'] for r in provider.results))
        self.assertEqual(provider.results[-1]['data']['status'],'blocked')
        for p in ('_jobs','_approval_input_freezes'):self.assertFalse((self.output/p).exists())
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.csv,self.summary)})
    def test_huge_responses_rejected_not_partial_success(self):
        with patch('quantlab.data.rights_rebuild_preview.preview_rights_rebuild',return_value={
            'events':['x'*6000]*20,'evidence':[]}):
            result=self.call(self.request())
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'RESULT_TOO_LARGE')
        self.assertLessEqual(len(encode(result).encode()),MAX_RESPONSE_BYTES)
    def test_twenty_complete_events_fit_full_tool_envelope(self):
        self.rows=[make_row(i) for i in range(1,21)];self.save()
        self.api=build_mcp_api(self.output,rights_candidate_binding=self.binding)
        # Obtain all event digests without limiting the preview's scope.
        first=self.preview();request=self.request(choices=[{
            'code':e['code'],'ex_date':e['ex_date'],'event_digest':e['event_digest'],'rights_source':'tdx'} for e in first['events']])
        result=self.call(request)
        self.assertTrue(result['ok'],result);self.assertEqual(result['data']['status'],'ready_for_review')
        self.assertEqual(len(result['data']['events']),20)
        self.assertLessEqual(len(encode(result).encode()),MAX_RESPONSE_BYTES)
    def test_new_bytes_same_runtime_rejects_old_binding(self):
        request=self.ready_request();self.assertTrue(self.call(request)['ok'])
        self.csv.write_bytes(self.csv.read_bytes()+b'\n')
        result=self.call(request);self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'],'CANDIDATE_HASH_MISMATCH')
    def test_extra_or_nested_unauthorized_keys_rejected_before_file_read(self):
        with patch('quantlab.data.rights_candidates._read',side_effect=AssertionError('no read')) as read:
            for args in ({'request_json':json.dumps(self.request()),'path':'/tmp'},
                         {'request_json':json.dumps({**self.request(),'execute':True})}):
                result=self.api.call('preview_rights_rebuild',args);self.assertFalse(result['ok'])
            read.assert_not_called()


class RightsRebuildMCPTests(Setup,IsolatedAsyncioTestCase):
    async def test_real_stdio_restart_matches_direct_and_denies_extra_fields(self):
        from mcp import Client,StdioServerParameters
        args={'request_json':json.dumps(self.ready_request())};expected=self.api.call('preview_rights_rebuild',args)
        params=StdioServerParameters(command=sys.executable,args=['-B','-m','quantlab.agent.mcp_server',
            '--output',str(self.output),*self.flags()],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        for server in (build_mcp_server(self.output,rights_candidate_binding=self.binding),params,params):
            async with Client(server,read_timeout_seconds=45) as client:
                tools={t.name:t for t in (await client.list_tools()).tools}
                for name in NAMES:
                    self.assertTrue(tools[name].annotations.read_only_hint)
                    self.assertFalse(tools[name].input_schema['additionalProperties'])
                got=await client.call_tool('preview_rights_rebuild',args)
                self.assertEqual(json.loads(got.content[0].text),expected)
                bad=await client.call_tool('preview_rights_rebuild',{**args,'approve':True})
                self.assertTrue(bad.is_error)
        self.assertFalse((self.output/'_jobs').exists())
