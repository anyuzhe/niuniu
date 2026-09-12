from copy import deepcopy
from uuid import uuid4
import json
import unittest

import test_core
from test_restricted_dsl import sample_ast
from quantlab.agent.alpha_factory import AlphaFactoryService
from quantlab.agent.dsl_candidates import DslCandidateService
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.app import build_runner
from quantlab.experiments.config import ExperimentConfig
from quantlab.storage.codec import digest
from quantlab.workbench.jobs import JobQueue,prepare,execute


class AlphaFactoryTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_core.CoreTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.output=self.fx.root/'factory-runs';self.output.mkdir()
        cfg=ExperimentConfig('Factory baseline',self.fx.request,'BASE.MOMENTUM',parameters={'lookback':2},horizons=(1,),quantiles=3,replay=True)
        self.baseline=build_runner(self.fx.root,self.output,self.fx.symbols).run(cfg)
        dsl=DslCandidateService(self.output);request=str(uuid4())
        proposal=dsl.propose(request,'Factory DSL',sample_ast(),self.baseline.run_id)
        self.candidate=dsl.register(request,proposal['plan_digest'],confirmed=True)['candidate_id']
        self.service=AlphaFactoryService(self.output,self.fx.root)
    def plan(self,**changes):
        value={'name':'固定Alpha工厂','candidate_ids':[self.candidate],
            'baseline_run_id':self.baseline.run_id,'control_run_ids':[self.baseline.run_id],
            'baseline_execution_run_id':None,'train_end':'2025-01-06','evaluation_start':'2025-01-07','horizon':1,'alpha':.05,
            'min_common_finite_ratio':.5,'max_abs_signal_corr':1.0,
            'require_positive_paired_ic_difference':False,'require_net_return':False}
        value.update(changes);return value

    def test_preview_propose_submit_sync_and_no_auto_promotion(self):
        preview=self.service.preview(self.plan());self.assertEqual(preview['planned_test_count'],1)
        self.assertFalse(preview['automatic_watchlist_promotion']);self.assertFalse((self.output/'_jobs').exists())
        proposal=self.service.propose(str(uuid4()),self.plan())
        with self.assertRaisesRegex(ValueError,'明确批准'):
            self.service.submit(proposal['proposal_id'],proposal['prepared_digest'],lambda:None)
        queue=JobQueue(self.output,self.fx.root)
        try:self.service.submit(proposal['proposal_id'],proposal['prepared_digest'],lambda:queue,confirmed=True)
        finally:queue.close()
        result=self.service.sync(proposal['proposal_id'])
        self.assertEqual(result['status'],'completed');self.assertEqual(len(result['tests']),1)
        self.assertEqual(len(result['decisions']),1);self.assertEqual(result['promotions'],[])
        self.assertTrue((self.output/result['result_run_id']/'experiment.json').is_file())
        again=self.service.sync(proposal['proposal_id']);self.assertEqual(again['result_run_id'],result['result_run_id'])
    def baseline_execution(self):
        spec={'question':'Factory baseline execution','symbols':list(self.fx.symbols),
            'start':str(self.fx.start),'end':str(self.fx.end),'factor':'BASE.MOMENTUM',
            'parameters':{'lookback':2},'horizons':[1],'quantiles':3,'replay':True,
            'mode':'execution','adjustment':'raw','execution':{'top_n':1,'price_mode':'research'}}
        return execute(prepare(spec),self.fx.root,self.output)

    def test_optional_cost_after_slot_is_frozen_in_same_family(self):
        account=self.baseline_execution();plan=self.plan(require_net_return=True,
            baseline_execution_run_id=account.run_id)
        proposal=self.service.propose(str(uuid4()),plan);queue=JobQueue(self.output,self.fx.root)
        try:self.service.submit(proposal['proposal_id'],proposal['prepared_digest'],lambda:queue,confirmed=True)
        finally:queue.close()
        result=self.service.sync(proposal['proposal_id']);self.assertEqual(len(result['tests']),2)
        self.assertEqual({r['id'] for r in result['tests']},{'residual_ic','net_return_increment'})
        self.assertEqual(result['prepared']['planned_test_count'],2)

    def test_source_change_after_proposal_blocks_admission(self):
        proposal=self.service.propose(str(uuid4()),self.plan())
        path=self.baseline.artifact_path/'observations.parquet';path.write_bytes(path.read_bytes()+b'x')
        queue=JobQueue(self.output,self.fx.root)
        try:
            with self.assertRaisesRegex(ValueError,'变化'):
                self.service.submit(proposal['proposal_id'],proposal['prepared_digest'],lambda:queue,confirmed=True)
        finally:queue.close()
        self.assertEqual(queue.list(),[])
    def test_agent_can_freeze_factory_but_not_execute_or_promote(self):
        api=MarketDataResearchAPI(self.output,self.fx.root);plan=self.plan()
        preview=api.call('preview_alpha_factory',{'plan_json':json.dumps(plan)})
        self.assertTrue(preview['ok'],preview)
        request=str(uuid4());proposal=api.call('propose_alpha_factory',
            {'request_id':request,'plan_json':json.dumps(plan)})
        self.assertTrue(proposal['ok'],proposal)
        self.assertFalse(api.call('execute_alpha_factory',{})['ok'])
        self.assertFalse(api.call('promote_alpha_candidate',{})['ok'])
        self.assertFalse((self.output/'_jobs').exists())

    def test_watchlist_promotion_requires_second_host_confirmation(self):
        proposal=self.service.propose(str(uuid4()),self.plan());queue=JobQueue(self.output,self.fx.root)
        try:self.service.submit(proposal['proposal_id'],proposal['prepared_digest'],lambda:queue,confirmed=True)
        finally:queue.close()
        result=self.service.sync(proposal['proposal_id']);state=self.service.get(proposal['proposal_id'])
        state['recommended_candidate_ids']=[self.candidate];self.service.store.save(state)
        with self.assertRaisesRegex(ValueError,'再次明确确认'):
            self.service.promote(proposal['proposal_id'],self.candidate,'Factory观察候选')
        promoted=self.service.promote(proposal['proposal_id'],self.candidate,'Factory观察候选',confirmed=True)
        self.assertFalse(promoted['authorization_created'])
        from quantlab.agent.tracking_control_store import ControlStore
        self.assertIsNone(ControlStore(self.output).get(promoted['watch_id']))

    def test_factory_parent_frozen_reproduction(self):
        proposal=self.service.propose(str(uuid4()),self.plan());queue=JobQueue(self.output,self.fx.root)
        try:self.service.submit(proposal['proposal_id'],proposal['prepared_digest'],lambda:queue,confirmed=True)
        finally:queue.close()
        result=self.service.sync(proposal['proposal_id'])
        from quantlab.storage.bundle import reproduce_artifact
        proof=reproduce_artifact(self.output/result['result_run_id'],self.fx.root/'factory-reproduced')
        self.assertEqual(proof['status'],'numerically_matched')
        self.assertEqual(proof['planned_candidates'],1);self.assertEqual(proof['planned_tests'],1)
