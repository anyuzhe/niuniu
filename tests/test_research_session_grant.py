import json
import time
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

import test_core
from test_workbench_jobs import spec as job_spec
from quantlab.agent.research_session_grant import (preview_grant,authorize_grant,revoke_grant,grant_status,
    ResearchSessionGrantService,assert_grant_active)
from quantlab.agent.research_session_tools import ResearchSessionGrantAPI
from quantlab.agent.peer_review_tools import PeerReviewResearchAPI
from quantlab.storage.codec import digest,encode
from quantlab.workbench.jobs import JobQueue


class ResearchSessionGrantTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.root;self.output=self.root/'session-runs';self.output.mkdir();self.queue=None
        self.addCleanup(lambda:self.queue.close() if self.queue else None)
        self.scope={'symbols':list(self.fixture.symbols),'timeframe':'1d','start':'2025-01-01','end':'2025-01-10',
            'adjustment':'qfq','qualification':'research_only','allowed_modes':['single','holdout','walkforward','sweep'],
            'allowed_factors':['BASE.MOMENTUM@1.0.0']}
    def get_queue(self):
        if self.queue is None:self.queue=JobQueue(self.output,self.root)
        return self.queue
    def plan(self,**changes):
        expiry=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        values={'expires_at':expiry,'max_jobs':5,'max_active_jobs':2,'max_leaf_studies':16,
            'max_total_leaf_studies':40,'max_total_bar_evaluations':5_000_000,
            'max_total_resample_date_draws':20_000_000,'cooperative_seconds':120}
        values.update(changes)
        return preview_grant(self.output,self.root,self.scope,**values)
    def authorize(self,**changes):
        plan=self.plan(**changes)
        return authorize_grant(self.output,self.root,plan,digest(plan),confirmed=True)
    def research_spec(self,**changes):
        value=job_spec(symbols=list(self.fixture.symbols),replay=True,qualification='research_only')
        value.update(changes);return value
    def settled(self,job_id):
        deadline=time.time()+15
        while time.time()<deadline:
            row=next(j for j in self.get_queue().list() if j['job_id']==job_id)
            if row['status'] not in ('queued','running'):return row
            time.sleep(.02)
        self.fail('session grant job did not settle')

    def test_preview_authorize_status_revoke_and_no_implicit_permissions(self):
        plan=self.plan();self.assertFalse(plan['network_allowed']);self.assertFalse(plan['shell_allowed']);self.assertFalse(plan['real_trade_allowed'])
        self.assertEqual(plan['scope']['allowed_modes'],['holdout','single','sweep','walkforward'])
        state=authorize_grant(self.output,self.root,plan,digest(plan),confirmed=True)
        status=grant_status(self.output,self.root);self.assertTrue(status['enabled']);self.assertEqual(status['grant']['grant_id'],state['grant_id'])
        self.assertEqual(status['remaining']['jobs'],5)
        revoked=revoke_grant(self.output,state['grant_id'],confirmed=True);self.assertFalse(revoked['enabled'])
        self.assertFalse(grant_status(self.output,self.root)['enabled'])
        newer=self.authorize();self.assertNotEqual(newer['grant_id'],state['grant_id'])
        self.assertTrue((self.output/'_research_session_grants'/'history'/(state['grant_id']+'.json')).is_file())
    def test_model_tools_can_only_read_or_submit_inside_host_grant(self):
        inner=PeerReviewResearchAPI(self.output,self.root)
        api=ResearchSessionGrantAPI(inner,self.output,self.root,self.get_queue)
        names={tool['name'] for tool in api.schemas()}
        self.assertIn('get_research_session_grant',names);self.assertIn('submit_granted_experiment',names)
        self.assertFalse({'authorize_research_session','revoke_research_session','run_shell','download_data'} & names)
        self.assertEqual(api.call('get_research_session_grant',{})['data']['status'],'not_configured')
        noqueue=ResearchSessionGrantAPI(PeerReviewResearchAPI(self.output,self.root),self.output,self.root,None)
        self.assertNotIn('submit_granted_experiment',{tool['name'] for tool in noqueue.schemas()})

    def test_scope_rejects_symbol_date_factor_mode_execution_context_and_nonreplay(self):
        state=self.authorize();service=ResearchSessionGrantService(self.output,self.root,self.get_queue);base=self.research_spec()
        bad=[{**base,'symbols':['sh.699999']},{**base,'start':'2024-12-31'},
            {**base,'factor':'BASE.CLOSE_LOCATION','parameters':{}},{**base,'mode':'execution','execution':{'top_n':1}},
            {**base,'context':{'start':'2024-12-01'}},{**base,'replay':False},
            {**base,'universe':{'mode':'listing'}}]
        for spec in bad:
            with self.subTest(spec=spec),self.assertRaises(Exception):service.submit(state['grant_id'],str(uuid4()),spec)
        self.assertEqual(grant_status(self.output,self.root)['used']['jobs'],0)

    def test_granted_submit_freezes_inputs_runs_and_is_idempotent(self):
        state=self.authorize();service=ResearchSessionGrantService(self.output,self.root,self.get_queue);request=str(uuid4());spec=self.research_spec()
        first=service.submit(state['grant_id'],request,spec);final=self.settled(first['job']['job_id'])
        self.assertEqual(final['status'],'completed',final);self.assertEqual(first['remaining']['jobs'],4)
        freeze=self.output/'_approval_input_freezes'/first['job']['job_id']/'manifest.json';self.assertTrue(freeze.is_file())
        second=service.submit(state['grant_id'],request,spec);self.assertEqual(second['job']['job_id'],first['job']['job_id'])
        self.assertEqual(grant_status(self.output,self.root)['used']['jobs'],1)
        with self.assertRaises(Exception):service.submit(state['grant_id'],request,{**spec,'question':'conflict'})
    def test_job_and_total_budgets_are_consumed_even_when_result_fails(self):
        state=self.authorize(max_jobs=1,max_total_leaf_studies=2)
        service=ResearchSessionGrantService(self.output,self.root,self.get_queue);request=str(uuid4());spec=self.research_spec()
        with patch('quantlab.workbench.jobs.execute',side_effect=ValueError('fixture failure')):
            item=service.submit(state['grant_id'],request,spec);final=self.settled(item['job']['job_id'])
        self.assertEqual(final['status'],'failed');status=grant_status(self.output,self.root)
        self.assertEqual(status['used']['jobs'],1);self.assertEqual(status['remaining']['jobs'],0)
        with self.assertRaises(Exception):service.submit(state['grant_id'],str(uuid4()),spec)

    def test_revoke_blocks_new_work_and_stops_running_job_at_checkpoint(self):
        import threading
        from quantlab.progress import checkpoint
        state=self.authorize();service=ResearchSessionGrantService(self.output,self.root,self.get_queue)
        entered=threading.Event();release=threading.Event()
        def fake(*args,**kwargs):
            entered.set();release.wait(5);checkpoint('fixture checkpoint');self.fail('revoked grant must stop before fake completes')
        with patch('quantlab.workbench.jobs.execute',side_effect=fake):
            item=service.submit(state['grant_id'],str(uuid4()),self.research_spec());self.assertTrue(entered.wait(5))
            revoke_grant(self.output,state['grant_id'],confirmed=True);release.set();final=self.settled(item['job']['job_id'])
        self.assertEqual(final['status'],'cancelled');self.assertIn('撤销',final['error'])
        with self.assertRaises(Exception):service.submit(state['grant_id'],str(uuid4()),self.research_spec())

    def test_expired_receipt_fails_closed(self):
        state=self.authorize();request=str(uuid4())
        receipt={'format':'niuniu-research-session-grant-receipt-v1','grant_id':state['grant_id'],'plan_digest':state['plan_digest'],
            'request_id':request,'authorized_at':state['authorized_at'],'expires_at':state['plan']['expires_at']}
        with self.assertRaisesRegex(ValueError,'任务不属于'):
            assert_grant_active(self.output,self.root,receipt)
        future=datetime.fromisoformat(state['plan']['expires_at'])+timedelta(seconds=1)
        state['jobs'].append({'request_id':request,'job_id':str(uuid4())})
        from quantlab.agent.research_session_grant import SessionGrantStore
        SessionGrantStore(self.output).save(state)
        with self.assertRaisesRegex(ValueError,'过期'):assert_grant_active(self.output,self.root,receipt,now=future)
    def test_chat_runtime_submits_only_through_active_grant_with_host_request_id(self):
        from quantlab.agent.chat_runtime import ChatRuntime
        from quantlab.agent.model_config import ModelConfig
        from test_agent_chat import FakeProvider
        state=self.authorize();runtime=ChatRuntime(self.output,self.root,self.get_queue);cid=runtime.store.create()
        provider=FakeProvider([('submit_granted_experiment',{'grant_id':state['grant_id'],'request_id':'model-made','spec_json':json.dumps(self.research_spec())})])
        result=runtime.send(cid,'在授权范围内做一项动量研究',ModelConfig(),allow_send=True,provider=provider)
        self.assertTrue(provider.results[0]['ok'],provider.results[0]);job_id=provider.results[0]['data']['job']['job_id']
        self.assertEqual(self.settled(job_id)['status'],'completed');self.assertEqual(result['evidence'][0]['kind'],'job')
        saved=grant_status(self.output,self.root)['jobs'][0];self.assertNotEqual(saved['request_id'],'model-made')
        self.assertEqual(str(uuid4()).count('-'),saved['request_id'].count('-'))

    def test_host_cli_preview_authorize_status_and_revoke(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from quantlab.agent.research_session_grant_cli import main
        scope=self.root/'scope.json';scope.write_text(json.dumps(self.scope));plan_file=self.root/'plan.json'
        expiry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat();stream=StringIO()
        with redirect_stdout(stream):code=main(['preview','--output',str(self.output),'--data-root',str(self.root),'--scope-file',str(scope),'--expires-at',expiry])
        self.assertEqual(code,0);preview=json.loads(stream.getvalue());plan_file.write_text(json.dumps(preview['data']))
        with redirect_stdout(StringIO()):self.assertEqual(main(['authorize','--output',str(self.output),'--data-root',str(self.root),'--plan-file',str(plan_file)]),2)
        with redirect_stdout(StringIO()):self.assertEqual(main(['authorize','--output',str(self.output),'--data-root',str(self.root),'--plan-file',str(plan_file),'--confirm']),0)
        state=grant_status(self.output,self.root);self.assertTrue(state['enabled']);grant_id=state['grant']['grant_id']
        with redirect_stdout(StringIO()):self.assertEqual(main(['revoke','--output',str(self.output),'--grant-id',grant_id,'--confirm']),0)
        self.assertFalse(grant_status(self.output,self.root)['enabled'])
    def test_direct_queue_cannot_forge_session_grant_job(self):
        from quantlab.experiments.runner import runtime_fingerprint
        state=self.authorize();request=str(uuid4())
        receipt={'format':'niuniu-research-session-grant-receipt-v1','grant_id':state['grant_id'],'plan_digest':state['plan_digest'],
            'request_id':request,'authorized_at':state['authorized_at'],'expires_at':state['plan']['expires_at']}
        guard={'runtime':runtime_fingerprint(),'cooperative_seconds':120,'max_active_jobs':2,'session_grant':receipt}
        with self.assertRaisesRegex(ValueError,'不属于'):self.get_queue().submit(str(uuid4()),self.research_spec(),execution_guard=guard)
        self.assertEqual(grant_status(self.output,self.root)['used']['jobs'],0)

    def test_revoked_grant_with_running_job_cannot_be_replaced(self):
        import threading
        state=self.authorize();service=ResearchSessionGrantService(self.output,self.root,self.get_queue);entered=threading.Event();release=threading.Event()
        def fake(*args,**kwargs):entered.set();release.wait(5);return type('Result',(),{'run_id':str(uuid4()),'experiment_id':'fixture'})()
        with patch('quantlab.workbench.jobs.execute',side_effect=fake):
            item=service.submit(state['grant_id'],str(uuid4()),self.research_spec());self.assertTrue(entered.wait(5));revoke_grant(self.output,state['grant_id'],confirmed=True)
            with self.assertRaisesRegex(ValueError,'未终止任务'):self.authorize()
            release.set();self.settled(item['job']['job_id'])
        newer=self.authorize();self.assertNotEqual(newer['grant_id'],state['grant_id'])

    def test_system_health_surfaces_active_grant_without_changing_research_axis(self):
        from quantlab.agent.system_health import SystemHealthService
        self.authorize();health=SystemHealthService(self.output,self.root).build();component=health['components']['research_session_grant']
        self.assertEqual(component['status'],'OK');self.assertTrue(component['evidence']['enabled']);self.assertEqual(component['evidence']['used']['jobs'],0)
        self.assertNotEqual(health['summary']['research_readiness_status'],'BLOCKED')
