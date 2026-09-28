"""Frozen grant references must narrow, never widen, existing research authority."""
import io
import json
import unittest
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch
from contextlib import redirect_stdout

import test_research_session_grant as fixtures
from quantlab.agent.research_session_grant import (
    ResearchSessionGrantService, SessionGrantStore, grant_status, authorize_grant, revoke_grant)
from quantlab.agent.research_session_tools import ResearchSessionGrantAPI
from quantlab.agent.peer_review_tools import PeerReviewResearchAPI
from quantlab.agent.grant_fixed_specs import prepared_digest
from quantlab.storage.codec import digest

class FixedGrantTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ResearchSessionGrantTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.spec=self.fx.research_spec();self.spec2=self.fx.research_spec(parameters={'lookback':3},question='second fixed study')
        self.catalog={'first':self.spec,'second':self.spec2}
        self.service=ResearchSessionGrantService(self.fx.output,self.fx.root,self.fx.get_queue)
        self.api=ResearchSessionGrantAPI(PeerReviewResearchAPI(self.fx.output,self.fx.root),self.fx.output,self.fx.root,self.fx.get_queue)
    def authorize(self,**kw):
        return self.fx.authorize(fixed_specs=self.catalog,**kw)
    def submit(self,state,spec):return self.service.submit(state['grant_id'],str(uuid4()),spec)
    def test_host_confirmation_and_catalog_bound_into_plan(self):
        plan=self.fx.plan(fixed_specs=self.catalog)
        self.assertEqual(plan['version'],2);self.assertEqual(plan['fixed_specs'],self.catalog)
        with self.assertRaises(ValueError):authorize_grant(self.fx.output,self.fx.root,plan,digest(plan))
        bad=deepcopy(plan);bad['fixed_specs']['first']['symbols'].pop()
        with self.assertRaises(ValueError):authorize_grant(self.fx.output,self.fx.root,bad,digest(plan),confirmed=True)
        state=authorize_grant(self.fx.output,self.fx.root,plan,digest(plan),confirmed=True)
        status=grant_status(self.fx.output,self.fx.root)
        self.assertTrue(status['fixed_specs_only']);self.assertEqual(len(status['fixed_specs']),2)
        self.assertEqual(status['fixed_specs'][0]['prepared_digest'],prepared_digest(self.spec))
        self.assertEqual(status['fixed_specs'][0]['symbols_count'],5)
        self.assertNotIn('parameters',status['fixed_specs'][0]);self.assertEqual(status['used']['jobs'],0)
        self.assertFalse((self.fx.output/'_jobs').exists())
    def test_preview_reference_and_submit_exact_original_without_model_copy(self):
        state=self.authorize();ref={'grant_spec':'first'}
        value=self.api.call('preview_experiment',{'spec_json':json.dumps(ref)})
        self.assertTrue(value['ok'],value);self.assertEqual(value['data']['fixed_spec_digest'],prepared_digest(self.spec))
        self.assertIsNone(self.fx.queue);self.assertFalse((self.fx.output/'_approval_input_freezes').exists())
        out=self.api.call('submit_granted_experiment',{'grant_id':state['grant_id'],'request_id':str(uuid4()),'spec_json':json.dumps(ref)})
        self.assertTrue(out['ok'],out);final=self.fx.settled(out['data']['job']['job_id'])
        self.assertEqual(final['status'],'completed',final);self.assertEqual(final['spec'],self.spec)
        self.assertTrue((self.fx.output/'_approval_input_freezes'/final['job_id']/'manifest.json').is_file())
    def test_raw_json_cannot_drop_stock_change_rule_or_question(self):
        state=self.authorize()
        bad=[{**self.spec,'symbols':self.spec['symbols'][:-1]},
             {**self.spec,'parameters':{'lookback':4}},{**self.spec,'question':'rewritten'},
             {**self.spec,'end':'2025-01-09'},{**self.spec,'horizons':[2]},
             {**self.spec,'mode':'execution','execution':{'top_n':1}}]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError):self.submit(state,value)
        self.assertIsNone(self.fx.queue);self.assertEqual(grant_status(self.fx.output,self.fx.root)['used']['jobs'],0)
        self.assertFalse((self.fx.output/'_approval_input_freezes').exists())
    def test_mixed_fields_unknown_reference_and_path_never_expand(self):
        state=self.authorize()
        for value in ({'grant_spec':'absent'},{'grant_spec':'../first'},{'grant_spec':None},
                      {'grant_spec':[]},{'grant_spec':'first','symbols':self.spec['symbols'][:-1]}):
            with self.subTest(value=value),self.assertRaises(ValueError):self.submit(state,value)
            response=self.api.call('preview_experiment',{'spec_json':json.dumps(value)})
            self.assertFalse(response['ok'],response)
        self.assertIsNone(self.fx.queue)
    def test_exact_and_reference_retries_share_one_job_across_request_ids(self):
        state=self.authorize(max_jobs=1)
        first=self.submit(state,{'grant_spec':'first'});self.fx.settled(first['job']['job_id'])
        same=self.submit(state,self.spec);again=self.submit(state,{'grant_spec':'first'})
        self.assertEqual(first['job']['job_id'],same['job']['job_id']);self.assertEqual(same['job']['job_id'],again['job']['job_id'])
        self.assertEqual(grant_status(self.fx.output,self.fx.root)['used']['jobs'],1)
        with self.assertRaises(ValueError):self.submit(state,{'grant_spec':'second'})
    def test_failed_fixed_task_is_not_reexecuted_or_refunded(self):
        state=self.authorize(max_jobs=1)
        with patch('quantlab.workbench.jobs.execute',side_effect=ValueError('expected failure')):
            first=self.submit(state,{'grant_spec':'first'});self.assertEqual(self.fx.settled(first['job']['job_id'])['status'],'failed')
        with patch('quantlab.workbench.jobs.execute',side_effect=AssertionError('must not rerun')):
            retried=self.submit(state,{'grant_spec':'first'})
            self.assertEqual(retried['job']['status'],'failed')
        self.assertEqual(grant_status(self.fx.output,self.fx.root)['remaining']['jobs'],0)
    def test_revocation_expiry_and_runtime_staleness_remain_enforced(self):
        state=self.authorize()
        with patch('quantlab.agent.research_session_grant._binding_matches',return_value=False):
            with self.assertRaises(ValueError):self.service.preview_fixed({'grant_spec':'first'})
            with self.assertRaises(ValueError):self.submit(state,{'grant_spec':'first'})
        future=datetime.now(timezone.utc)+timedelta(days=2)
        with patch('quantlab.agent.research_session_grant.utc',return_value=future):
            with self.assertRaises(ValueError):self.submit(state,{'grant_spec':'first'})
        revoke_grant(self.fx.output,state['grant_id'],confirmed=True)
        with self.assertRaises(ValueError):self.submit(state,{'grant_spec':'first'})
        with self.assertRaises(ValueError):self.service.preview_fixed({'grant_spec':'first'})
        self.assertIsNone(self.fx.queue)
    def test_bad_fixed_catalog_rejected_before_authorization(self):
        for catalog in ({},{'../x':self.spec},{'a':self.spec,'b':self.spec},
                        {'x':{**self.spec,'symbols':['sh.699999']}},
                        {'x':{**self.spec,'context':{}}},
                        {'x':{**self.spec,'unexpected':'field'}}):
            with self.subTest(catalog=catalog),self.assertRaises(ValueError):self.fx.plan(fixed_specs=catalog)
        self.assertFalse((self.fx.output/'_research_session_grants').exists())
    def test_legacy_plan_stays_legacy_and_reference_is_not_implicit_authority(self):
        plan=self.fx.plan();self.assertEqual(plan['version'],1);self.assertNotIn('fixed_specs',plan)
        state=authorize_grant(self.fx.output,self.fx.root,plan,digest(plan),confirmed=True)
        with self.assertRaises(ValueError):self.submit(state,{'grant_spec':'first'})
        result=self.submit(state,self.spec);self.assertEqual(self.fx.settled(result['job']['job_id'])['status'],'completed')
        readonly=ResearchSessionGrantAPI(PeerReviewResearchAPI(self.fx.output,self.fx.root),self.fx.output,self.fx.root,None)
        self.assertNotIn('submit_granted_experiment',{t['name'] for t in readonly.schemas()})
    def test_native_chat_reference_routes_with_one_canonical_journal(self):
        from quantlab.agent.chat_runtime import ChatRuntime
        from quantlab.agent.model_config import ModelConfig
        from test_agent_chat import FakeProvider
        state=self.authorize();runtime=ChatRuntime(self.fx.output,self.fx.root,self.fx.get_queue)
        ref=json.dumps({'grant_spec':'first'})
        provider=FakeProvider([('preview_experiment',{'spec_json':ref}),
            ('submit_granted_experiment',{'grant_id':state['grant_id'],'request_id':'model-value','spec_json':ref})])
        cid=runtime.store.create();result=runtime.send(cid,'运行宿主冻结first',ModelConfig(),allow_send=True,provider=provider)
        self.assertTrue(all(r['ok'] for r in provider.results),provider.results)
        final=self.fx.settled(provider.results[1]['data']['job']['job_id']);self.assertEqual(final['spec'],self.spec)
        self.assertEqual(result['tool_calls'],2)
        events=runtime.store.events(cid)['events'];self.assertEqual(sum(e['kind']=='tool_result' for e in events),2)
        for profile in ('everyday','evidence'):
            r=ChatRuntime(self.fx.output,self.fx.root,self.fx.get_queue,tool_profile=profile)
            self.assertNotIn('submit_granted_experiment',{t['name'] for t in r.api.schemas()})
    def test_cli_fixed_catalog_is_optional_and_preserves_full_specs(self):
        from quantlab.agent.research_session_grant_cli import main
        scope=self.fx.root/'scope.json';scope.write_text(json.dumps(self.fx.scope))
        catalog=self.fx.root/'fixed.json';catalog.write_text(json.dumps(self.catalog))
        stream=io.StringIO()
        with redirect_stdout(stream):
            code=main(['preview','--output',str(self.fx.output),'--data-root',str(self.fx.root),
                '--scope-file',str(scope),'--fixed-specs-file',str(catalog),
                '--expires-at',(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()])
        self.assertEqual(code,0,stream.getvalue());plan=json.loads(stream.getvalue())['data']['plan']
        self.assertEqual(plan['fixed_specs'],self.catalog);self.assertIsNone(self.fx.queue)

if __name__=='__main__':unittest.main()
