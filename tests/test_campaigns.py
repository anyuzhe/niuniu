import json
import tempfile
import time
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import polars as pl
import test_core
from quantlab.agent.campaign_plan import prepare_campaign
from quantlab.agent.planning import ResearchBudget, ProposalError
from quantlab.agent.campaign_tools import ResearchCampaignAPI
from quantlab.agent.proposals import ProposalService
from quantlab.experiments.campaign import run_campaign
from quantlab.experiments.campaign_state import read_checked
from quantlab.progress import research_progress, ResearchCancelled
from quantlab.workbench.jobs import prepare, execute, JobQueue
from quantlab.storage.experiments import load_record_fields


def pack(symbols):
    base={'question':'fixed node','symbols':list(symbols),'start':'2025-01-01','end':'2025-01-10',
        'factor':'BASE.MOMENTUM','parameters':{'lookback':2},'horizons':[1],
        'replay':True,'permutation':{'resamples':20,'block_days':1}}
    return {'mode':'campaign','question':'fixed pack','alpha':.05,'failure_policy':'continue_independent',
        'nodes':[{'node_id':'first','depends_on':[],'spec':base},
            {'node_id':'second','depends_on':['first'],'spec':{**base,'parameters':{'lookback':3}}}]}


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.root;self.output=self.root/'campaign-runs';self.output.mkdir()
        self.plan=pack(self.fixture.symbols)
    def test_static_dag_validation_and_total_budget(self):
        preview=prepare_campaign(self.plan)
        self.assertEqual(preview['order'],['first','second']);self.assertEqual(preview['estimate']['planned_tests'],4)
        with self.assertRaisesRegex(ProposalError,'整个研究包'):
            prepare_campaign(self.plan,replace(ResearchBudget(),max_leaf_studies=1))
        for mutate in (lambda p:p['nodes'][0].update(depends_on=['second']),
            lambda p:p['nodes'][1].update(depends_on=['unknown']),
            lambda p:p['nodes'][1].update(spec={**p['nodes'][0]['spec'],'question':'different title'}),
            lambda p:p['nodes'][0]['spec'].update(replay=False),
            lambda p:p['nodes'][0]['spec'].pop('permutation'),
            lambda p:p['nodes'][0].update(spec={'mode':'campaign'}),
            lambda p:p['nodes'][0].update(select_if_p_below=.05)):
            candidate=deepcopy(self.plan);mutate(candidate)
            with self.assertRaises(ValueError):prepare_campaign(candidate)
    def test_real_engine_fixed_family_and_receipt_idempotence(self):
        job=str(uuid4());submission=prepare(self.plan)
        result=run_campaign(submission,self.root,self.output,job)
        self.assertEqual(result.summary['counts']['completed'],2)
        self.assertEqual(result.summary['family']['planned_tests'],4)
        with patch('quantlab.workbench.jobs.execute',side_effect=AssertionError('must reuse receipt')):
            again=run_campaign(submission,self.root,self.output,job)
        self.assertEqual(again.run_id,result.run_id)
    def test_failure_and_dependency_skip_keep_family_slots(self):
        first=deepcopy(self.plan['nodes'][0]);first['node_id']='missing';first['spec']['symbols']=['sh.699999']
        dependent=deepcopy(self.plan['nodes'][1]);dependent['node_id']='blocked';dependent['depends_on']=['missing']
        dependent['spec']['parameters']={'lookback':4}
        self.plan['nodes']=[first,dependent,*self.plan['nodes']]
        result=execute(prepare(self.plan),self.root,self.output)
        self.assertEqual(result.summary['counts'],{'completed':2,'failed':1,'skipped':1,'not_run':0})
        family=result.summary['family'];self.assertEqual(family['planned_tests'],8)
        missing=[t for t in family['tests'] if t['trial_id'] in ('missing','blocked')]
        self.assertEqual(len(missing),4);self.assertTrue(all(t['p_value'] is None for t in missing))
        self.assertEqual(result.summary['workflow_status'],'completed_with_failures')
    def test_stop_policy_does_not_run_independent_successor(self):
        self.plan['failure_policy']='stop';self.plan['nodes'][0]['spec']['symbols']=['sh.699999']
        self.plan['nodes'][1]['depends_on']=[]
        result=execute(prepare(self.plan),self.root,self.output)
        self.assertEqual(result.summary['counts']['failed'],1);self.assertEqual(result.summary['counts']['skipped'],1)
        self.assertEqual(result.summary['family']['available_tests'],0)
    def interrupt_after_first(self,job):
        def cancel(stage=None,*_):
            if stage=='研究包节点 · second':raise ResearchCancelled('fixture cancellation')
        with research_progress(cancel),self.assertRaises(ResearchCancelled):
            run_campaign(prepare(self.plan),self.root,self.output,job)
        state=read_checked(self.output/'_campaigns'/job/'state.json')
        self.assertEqual(set(state['nodes']),{'first'});return state
    def test_resume_preserves_committed_node_and_matches_clean(self):
        job=str(uuid4());before=self.interrupt_after_first(job);calls=[];original=execute
        def run(spec,*args,**kwargs):calls.append(spec.config.parameters);return original(spec,*args,**kwargs)
        with patch('quantlab.workbench.jobs.execute',side_effect=run):
            resumed=run_campaign(prepare(self.plan),self.root,self.output,job)
        self.assertEqual(calls,[{'lookback':3}])
        self.assertEqual(resumed.summary['nodes'][0]['run_id'],before['nodes']['first']['run_id'])
        clean=execute(prepare(self.plan),self.root,self.root/'clean')
        self.assertEqual(resumed.experiment_id,clean.experiment_id)
        for a,b in zip(resumed.summary['family']['tests'],clean.summary['family']['tests']):
            for k in ('trial_id','horizon','metric','p_value','p_holm','status'):self.assertEqual(a[k],b[k])
    def test_resume_rejects_changed_input_record_or_plan(self):
        job=str(uuid4());before=self.interrupt_after_first(job)
        altered=deepcopy(self.plan);altered['question']='changed'
        with self.assertRaisesRegex(ProposalError,'计划或输入'):run_campaign(prepare(altered),self.root,self.output,job)
        artifact=self.output/before['nodes']['first']['run_id']/'experiment.json'
        record=json.loads(artifact.read_text());record['metrics']['1']['rank_ic']=.99;artifact.write_text(json.dumps(record))
        with self.assertRaisesRegex(ProposalError,'数值记录'):run_campaign(prepare(self.plan),self.root,self.output,job)
    def test_source_change_stops_before_reusing_nodes(self):
        job=str(uuid4());self.interrupt_after_first(job)
        path=next((self.root/'lake/silver/qfq_kline_daily').glob('*.parquet'))
        frame=pl.read_parquet(path);frame.with_columns((pl.col('close').cast(pl.Float64)*1.001).alias('close')).write_parquet(path)
        with self.assertRaisesRegex(ProposalError,'输入数据变化'):run_campaign(prepare(self.plan),self.root,self.output,job)
    def test_holdout_family_expands_before_execution(self):
        self.plan['nodes'][1]['spec'].update(mode='holdout',split={'train_end':'2025-01-04','valid_end':'2025-01-07'})
        result=execute(prepare(self.plan),self.root,self.output)
        self.assertEqual(result.summary['planned_tests'],8)
        self.assertEqual(result.summary['family']['planned_tests'],8)
        self.assertEqual(result.summary['counts']['completed'],2)
    def test_proposal_is_host_only_and_queue_is_idempotent(self):
        api=ResearchCampaignAPI(self.output,self.root)
        self.assertNotIn('approve_campaign',[t['name'] for t in api.schemas()])
        self.assertFalse(api.call('approve_campaign',{})['ok'])
        value=api.call('propose_campaign',{'request_id':str(uuid4()),'spec_json':json.dumps(self.plan)})
        self.assertTrue(value['ok'],value);proposal_id=value['evidence'][0]['proposal_id']
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
        proposal=api.proposals.store.get(proposal_id);queue=JobQueue(self.output,self.root)
        try:
            a=api.proposals.approve_and_submit(proposal_id,proposal['proposal_digest'],lambda:queue)
            b=api.proposals.approve_and_submit(proposal_id,proposal['proposal_digest'],lambda:queue)
            self.assertEqual(a['job']['job_id'],b['job']['job_id'])
        finally:queue.close()
        self.assertEqual(queue.list()[0]['status'],'completed',queue.list())
        viewed=api.call('get_campaign',{'proposal_id':proposal_id})
        self.assertTrue(viewed['ok'],viewed);self.assertEqual(len(queue.list()),1)
        self.assertEqual(viewed['data']['result']['kind'],'campaign')
    def test_diagnostic_execution_not_part_of_ic_family(self):
        node=deepcopy(self.plan['nodes'][1]);node['spec'].update(mode='execution',execution={'top_n':1})
        node['node_id']='costs';self.plan['nodes']=[self.plan['nodes'][0],node]
        result=execute(prepare(self.plan),self.root,self.output)
        self.assertEqual(result.summary['counts']['completed'],2)
        self.assertEqual(result.summary['planned_tests'],2)
        self.assertEqual(result.summary['family']['planned_tests'],2)
    def test_queue_cancel_reopen_and_explicit_resume_same_job(self):
        from quantlab.factors.engine import compute_factor
        job=str(uuid4());queue=JobQueue(self.output,self.root)
        def interrupt(factor,bars,parameters):
            if parameters.get('lookback')==3:raise ResearchCancelled('interrupt second node')
            return compute_factor(factor,bars,parameters)
        try:
            with patch('quantlab.experiments.runner.compute_factor',side_effect=interrupt):
                queue.submit(job,self.plan)
                limit=time.monotonic()+30
                while queue.list()[0]['status'] in ('queued','running') and time.monotonic()<limit:time.sleep(.02)
            self.assertEqual(queue.list()[0]['status'],'cancelled')
        finally:queue.close()
        before=read_checked(self.output/'_campaigns'/job/'state.json')['nodes']['first']['run_id']
        resumed=JobQueue(self.output,self.root)
        try:resumed.resume(job)
        finally:resumed.close()
        state=resumed.list()[0];self.assertEqual(state['status'],'completed',state)
        final=read_checked(self.output/'_campaigns'/job/'state.json')
        self.assertEqual(final['nodes']['first']['run_id'],before)
        self.assertEqual(len(final['attempts']),2);self.assertEqual(len(resumed.list()),1)
    def test_missing_receipt_not_silently_recreated(self):
        job=str(uuid4());self.interrupt_after_first(job)
        (self.output/'_campaigns'/job/'state.json').unlink()
        with self.assertRaisesRegex(ProposalError,'回执缺失'):
            run_campaign(prepare(self.plan),self.root,self.output,job)
    def test_factor_version_alias_returns_actionable_error(self):
        api=ResearchCampaignAPI(self.output,self.root)
        bad=api.call('describe_factor',{'factor_id':'BASE.MOMENTUM','version':'latest'})
        self.assertFalse(bad['ok']);self.assertEqual(bad['error']['code'],'INVALID_ARGUMENT')
        self.assertIn('search_factors',bad['error']['message'])
        good=api.call('describe_factor',{'factor_id':'BASE.MOMENTUM','version':'1.0.0'})
        self.assertTrue(good['ok'])
