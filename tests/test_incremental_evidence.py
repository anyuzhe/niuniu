from copy import deepcopy
from uuid import uuid4
import json
import unittest
import polars as pl
import test_candidate_review as fixture
from test_campaigns import pack
from quantlab.agent.incremental_evidence import IncrementalEvidenceService
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.workbench.jobs import prepare,execute
from quantlab.storage.artifact_integrity import snapshot_tree


class IncrementalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.CandidateReviewTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.service=IncrementalEvidenceService(self.fx.output)
    def plan(self,**changes):
        value={'candidate_run_id':self.fx.a.run_id,'control_run_ids':[self.fx.b.run_id],
            'train_end':'2025-01-06','horizon':1,'alpha':.05,'return_pair':None}
        value.update(changes);return value
    def execution_pair(self):
        spec=deepcopy(pack(self.fx.fixture.symbols)['nodes'][0]['spec'])
        spec.update(horizons=[1,2],quantiles=3,mode='execution',execution={'price_mode':'research','top_n':2})
        spec.pop('permutation',None)
        a=execute(prepare(spec),self.fx.root,self.fx.output)
        b=execute(prepare({**spec,'parameters':{'lookback':3}}),self.fx.root,self.fx.output)
        return a,b
    def test_preview_propose_and_agent_never_execute(self):
        before=[snapshot_tree(self.fx.output,r.run_id) for r in (self.fx.a,self.fx.b)]
        preview=self.service.preview(self.plan())
        self.assertEqual(preview['planned_tests'],[{'id':'residual_ic','kind':'residual_alpha'}])
        self.assertEqual(preview['new_research_jobs'],0);self.assertFalse((self.fx.output/'_incremental_evidence').exists())
        request=str(uuid4());saved=self.service.propose(request,self.plan())
        self.assertEqual(saved['status'],'pending');self.assertIsNone(saved['result_run_id'])
        self.assertEqual(before,[snapshot_tree(self.fx.output,r.run_id) for r in (self.fx.a,self.fx.b)])
        self.assertEqual(self.service.propose(request,self.plan())['proposal_id'],saved['proposal_id'])
        with self.assertRaisesRegex(ValueError,'不能改写'):
            self.service.propose(request,self.plan(train_end='2025-01-05'))
        api=MarketDataResearchAPI(self.fx.output,self.fx.root)
        args={'plan_json':json.dumps(self.plan())}
        self.assertTrue(api.call('preview_incremental_evidence',args)['ok'])
        rid=str(uuid4());proposed=api.call('propose_incremental_evidence',{'request_id':rid,**args})
        self.assertTrue(proposed['ok'],proposed)
        pid=proposed['data']['proposal_id'];self.assertTrue(api.call('get_incremental_evidence',{'proposal_id':pid})['ok'])
        for name in ('execute_incremental_evidence','approve_incremental_evidence','run_incremental_evidence'):
            self.assertFalse(api.call(name,{})['ok'])
    def test_host_execute_is_idempotent_and_source_change_blocks(self):
        request=str(uuid4());saved=self.service.propose(request,self.plan())
        with self.assertRaisesRegex(ValueError,'宿主明确确认'):
            self.service.execute(saved['proposal_id'],saved['prepared_digest'])
        result=self.service.execute(saved['proposal_id'],saved['prepared_digest'],confirmed=True)
        self.assertEqual(result['status'],'completed');self.assertEqual(result['summary']['planned_tests'],1)
        self.assertEqual(len(result['tests']),1);self.assertEqual(result['tests'][0]['kind'],'residual_alpha')
        parent=result['result_run_id'];child=result['tests'][0]['run_id']
        again=self.service.execute(saved['proposal_id'],saved['prepared_digest'],confirmed=True)
        self.assertEqual((again['result_run_id'],again['tests'][0]['run_id']),(parent,child))
        other=self.service.propose(str(uuid4()),self.plan())
        path=self.fx.a.artifact_path/'observations.parquet';frame=pl.read_parquet(path)
        frame.with_columns((pl.col('value')+1).alias('value')).write_parquet(path)
        with self.assertRaisesRegex(ValueError,'变化'):
            self.service.execute(other['proposal_id'],other['prepared_digest'],confirmed=True)

    def test_failed_slot_remains_in_family(self):
        saved=self.service.propose(str(uuid4()),self.plan(train_end='2025-01-01'))
        result=self.service.execute(saved['proposal_id'],saved['prepared_digest'],confirmed=True)
        self.assertEqual(result['summary']['planned_tests'],1);self.assertEqual(result['summary']['available_tests'],0)
        row=result['summary']['tests'][0]
        self.assertEqual(row['status'],'failed');self.assertIsNone(row['p_value']);self.assertIsNone(row['p_holm'])
        self.assertEqual(result['summary']['workflow_status'],'completed_with_failures')
    def test_two_slot_family_includes_cost_after_increment(self):
        a,b=self.execution_pair()
        pair={'candidate_run_id':a.run_id,'baseline_run_id':b.run_id,'evaluation_start':'2025-01-03'}
        saved=self.service.propose(str(uuid4()),self.plan(return_pair=pair))
        result=self.service.execute(saved['proposal_id'],saved['prepared_digest'],confirmed=True)
        summary=result['summary'];self.assertEqual(summary['planned_tests'],2)
        self.assertEqual([r['kind'] for r in summary['tests']],['residual_alpha','return_increment'])
        self.assertEqual(len(result['tests']),2)
        adjusted=[r['p_holm'] for r in summary['tests']]
        self.assertTrue(all(v is None or 0<=v<=1 for v in adjusted))
        records=[json.loads(p.read_text()) for p in self.fx.output.glob('*/experiment.json')]
        self.assertEqual(sum(r.get('kind')=='incremental_evidence' for r in records),1)

    def test_plan_validation_rejects_duplicate_or_incompatible_sources(self):
        for bad in (self.plan(control_run_ids=[self.fx.a.run_id]),self.plan(control_run_ids=[]),
                self.plan(horizon=True),self.plan(alpha=.5)):
            with self.assertRaises((ValueError,TypeError)):self.service.preview(bad)

    def test_parent_reproduction_keeps_fixed_family(self):
        from quantlab.storage.bundle import reproduce_artifact
        saved=self.service.propose(str(uuid4()),self.plan())
        result=self.service.execute(saved['proposal_id'],saved['prepared_digest'],confirmed=True)
        proof=reproduce_artifact(self.fx.output/result['result_run_id'],self.fx.root/'incremental-replayed')
        self.assertIn(proof['status'],('numerically_matched','available_results_matched'))
        self.assertEqual(proof['planned_tests'],1)
        self.assertEqual(proof['recomputed_tests'],1)
