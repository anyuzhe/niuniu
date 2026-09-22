"""F19 Chat/API/CLI/MCP boundaries for supplemental unresolved evidence."""
import contextlib, io, json, os, sys
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import patch

from test_rights_conflict_evidence import ConflictEvidenceFixture
from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.data_review_cli import main

NAMES={'get_rights_conflict_evidence_manifest','query_rights_conflict_evidence'}


class Setup(ConflictEvidenceFixture):
    def setUp(self):
        super().setUp();self.output=self.root/'output';self.output.mkdir()
        self.api=build_mcp_api(self.output,rights_candidate_binding=self.binding,
            rights_evidence_binding=self.evidence_binding)
    def flags(self):
        return ['--rights-csv',str(self.csv),'--rights-summary',str(self.summary),
            '--rights-csv-sha256',self.binding.csv_sha256,'--rights-summary-sha256',self.binding.summary_sha256,
            '--rights-evidence-jsonl',str(self.evidence_jsonl),'--rights-evidence-summary',str(self.evidence_summary),
            '--rights-evidence-jsonl-sha256',self.evidence_binding.jsonl_sha256,
            '--rights-evidence-summary-sha256',self.evidence_binding.summary_sha256]
    def qargs(self):
        return {'symbol':'','start':'2000-01-01','end':'2000-01-31','offset':0,'limit':5}


class RightsConflictToolTests(Setup,TestCase):
    def test_schema_capabilities_and_unbound_fail_closed(self):
        names={t['name'] for t in self.api.schemas()};self.assertTrue(NAMES<=names)
        caps=self.api.call('get_capabilities',{})['data']
        self.assertTrue(caps['rights_conflict_evidence_configured'])
        self.assertFalse(caps['rights_conflict_evidence_write_authorized'])
        for t in self.api.schemas():
            if t['name'] in NAMES:
                self.assertFalse(t['parameters']['additionalProperties'])
                self.assertTrue({'path','hash','approve','execute'}.isdisjoint(t['parameters']['properties']))
        api=build_mcp_api(self.output,rights_candidate_binding=self.binding)
        with patch('quantlab.data.rights_conflict_evidence._read',side_effect=AssertionError('no discovery')) as read:
            result=api.call('get_rights_conflict_evidence_manifest',{})
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'RIGHTS_EVIDENCE_NOT_CONFIGURED');read.assert_not_called()

    def test_cli_manifest_query_and_preview_with_supplement(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=main(['rights-evidence-manifest',*self.flags()])
        got=json.loads(out.getvalue());self.assertEqual(code,0)
        self.assertEqual(got,self.api.call('get_rights_conflict_evidence_manifest',{}))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=main(['rights-evidence-query',*self.flags(),
            '--start','2000-01-01','--end','2000-01-31'])
        self.assertEqual(code,0);self.assertEqual(json.loads(out.getvalue()),
            self.api.call('query_rights_conflict_evidence',self.qargs()))
        event=next(r for r in self.query(status='conflicts')['rows'])
        req={'contract':'niuniu-rights-rebuild-preview-v1','bundle_id':self.binding.bundle_id,
             'scope':{'symbols':[event['fields']['code']],'start':event['fields']['ex_date'],'end':event['fields']['ex_date']},
             'choices':[{'code':event['fields']['code'],'ex_date':event['fields']['ex_date'],
                         'event_digest':event['event_digest'],'rights_source':'tdx'}]}
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=main(['rights-preview',*self.flags(),'--request-json',json.dumps(req)])
        data=json.loads(out.getvalue());self.assertEqual(code,3);self.assertTrue(data['ok'])
        self.assertTrue(data['data']['supplemental_evidence_bound'])
        self.assertEqual(data['data']['events'][0]['supplemental_evidence']['verdict'],'UNRESOLVED')

    def test_formal_chat_reads_supplement_without_jobs_or_writes(self):
        from test_agent_chat import FakeProvider
        from quantlab.agent.model_config import ModelConfig
        before={p.name:p.read_bytes() for p in (self.csv,self.summary,self.evidence_jsonl,self.evidence_summary)}
        runtime=ChatRuntime(self.output,local_data_only=True,rights_candidate_binding=self.binding,
            rights_evidence_binding=self.evidence_binding)
        provider=FakeProvider([('get_rights_conflict_evidence_manifest',{}),
            ('query_rights_conflict_evidence',self.qargs())])
        result=runtime.send(runtime.store.create(),'只读核对未决证据，不作裁决',
            ModelConfig(max_context_chars=150000),allow_send=True,provider=provider)
        self.assertEqual(result['tool_calls'],2);self.assertTrue(all(x['ok'] for x in provider.results))
        self.assertEqual(provider.results[-1]['data']['rows'][0]['verdict'],'UNRESOLVED')
        self.assertFalse((self.output/'_jobs').exists());self.assertFalse((self.output/'_approval_input_freezes').exists())
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.csv,self.summary,self.evidence_jsonl,self.evidence_summary)})

    def test_locked_qm50_and_reviewer_do_not_gain_evidence_tools(self):
        from quantlab.agent.peer_review import ReviewReadOnlyAPI
        from test_qm50_archived_inputs import ArchivedQM50Tests
        f=ArchivedQM50Tests();self.addCleanup(f.doCleanups);f.setUp()
        locked=ChatRuntime(f.output,local_data_only=True,research_spec=f.sid,spec_source_workspace=f.source,
            rights_candidate_binding=self.binding,rights_evidence_binding=self.evidence_binding).api
        for api in (locked,ReviewReadOnlyAPI(self.output,None)):
            schemas={t['name'] for t in api.schemas()};self.assertTrue(NAMES.isdisjoint(schemas))
            for name in NAMES:self.assertFalse(api.call(name,{})['ok'])

    def test_extra_fields_rejected_and_changed_bytes_fail_same_runtime(self):
        self.assertFalse(self.api.call('query_rights_conflict_evidence',{**self.qargs(),'path':'/tmp'})['ok'])
        self.assertTrue(self.api.call('get_rights_conflict_evidence_manifest',{})['ok'])
        self.evidence_jsonl.write_bytes(self.evidence_jsonl.read_bytes()+b'\n')
        result=self.api.call('get_rights_conflict_evidence_manifest',{})
        self.assertFalse(result['ok'])


class RightsConflictMCPTests(Setup,IsolatedAsyncioTestCase):
    async def test_real_stdio_restart_matches_direct_and_is_read_only(self):
        from mcp import Client,StdioServerParameters
        expected=self.api.call('query_rights_conflict_evidence',self.qargs())
        params=StdioServerParameters(command=sys.executable,args=['-B','-m','quantlab.agent.mcp_server',
            '--output',str(self.output),*self.flags()],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        for server in (build_mcp_server(self.output,rights_candidate_binding=self.binding,
                       rights_evidence_binding=self.evidence_binding),params,params):
            async with Client(server,read_timeout_seconds=45) as client:
                tools={t.name:t for t in (await client.list_tools()).tools}
                for name in NAMES:
                    self.assertTrue(tools[name].annotations.read_only_hint)
                    self.assertFalse(tools[name].input_schema['additionalProperties'])
                got=await client.call_tool('query_rights_conflict_evidence',self.qargs())
                self.assertEqual(json.loads(got.content[0].text),expected)
                bad=await client.call_tool('query_rights_conflict_evidence',{**self.qargs(),'approve':True})
                self.assertTrue(bad.is_error)
        self.assertFalse((self.output/'_jobs').exists())
