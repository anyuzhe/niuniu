import json
from copy import deepcopy
import unittest
import polars as pl
import test_core
from test_campaigns import pack
from quantlab.workbench.jobs import prepare, execute
from quantlab.agent.candidate_review import compare_candidate
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.storage.codec import digest


class CandidateReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.root;self.output=self.root/'candidate-runs'
        spec=deepcopy(pack(self.fixture.symbols)['nodes'][0]['spec'])
        spec.update(horizons=[1,2],quantiles=3);spec.pop('permutation')
        self.a=execute(prepare(spec),self.root,self.output)
        self.b=execute(prepare({**spec,'parameters':{'lookback':3}}),self.root,self.output)
    def review(self):return compare_candidate(self.output,self.a.run_id,self.b.run_id,2)
    def rewrite_record(self,result,change):
        path=result.artifact_path/'experiment.json';record=json.loads(path.read_text())
        change(record);record['experiment_id']=digest(record['manifest']);path.write_text(json.dumps(record))
    def change_observations(self,result,change):
        path=result.artifact_path/'observations.parquet'
        frame=pl.read_parquet(path);change(frame).write_parquet(path)
    def test_same_sample_identity_read_only_and_honest_result(self):
        before=[snapshot_tree(self.output,r.run_id) for r in (self.a,self.b)]
        result=self.review()
        self.assertEqual(result['new_research_jobs'],0);self.assertFalse(result['alpha_verified'])
        self.assertIsNone(result['p_value']);self.assertFalse(result['same_run'])
        self.assertGreater(result['coverage']['shared_keys'],0)
        self.assertGreater(result['coverage']['pending_common_rows'],0)
        self.assertEqual(before,[snapshot_tree(self.output,r.run_id) for r in (self.a,self.b)])
        self.assertFalse((self.output/'_jobs').exists())
        same=compare_candidate(self.output,self.a.run_id,self.a.run_id,2)
        self.assertTrue(same['same_run'])
        self.assertAlmostEqual(same['paired_rank_ic']['difference'],0.)
        self.assertAlmostEqual(same['signal_rank_correlation']['mean'],1.)
    def test_factor_correlation_does_not_select_on_future_labels(self):
        before=self.review()['signal_rank_correlation']
        for result in (self.a,self.b):
            self.change_observations(result,lambda f:f.with_columns(pl.lit(None,dtype=pl.Float64).alias('forward_2')))
        after=self.review()
        self.assertEqual(before,after['signal_rank_correlation'])
        self.assertEqual(after['status'],'insufficient_common_sample')
        self.assertIsNone(after['paired_rank_ic']['difference'])
    def test_constant_factor_does_not_become_zero_ic(self):
        self.change_observations(self.a,lambda f:f.with_columns(pl.lit(1.).alias('value')))
        result=self.review();self.assertEqual(result['status'],'insufficient_common_sample')
        self.assertIsNone(result['paired_rank_ic']['candidate'])
        self.assertIsNone(result['signal_rank_correlation']['mean'])
    def test_different_mature_labels_are_rejected_before_row_filtering(self):
        self.change_observations(self.b,lambda f:f.with_columns((pl.col('forward_2')+.01).alias('forward_2')))
        with self.assertRaisesRegex(ValueError,'标签不一致'):self.review()
    def test_missing_keys_reported_and_bad_endpoint_rejected(self):
        self.change_observations(self.b,lambda f:f.slice(1))
        result=self.review();self.assertEqual(result['coverage']['candidate_only_keys'],1)
        self.change_observations(self.b,lambda f:f.drop('label_end_2'))
        with self.assertRaisesRegex(ValueError,'标签结束时间'):self.review()
    def test_runtime_condition_and_failed_runs_are_not_mixed(self):
        self.rewrite_record(self.b,lambda r:r['manifest']['config'].update(quantiles=4))
        with self.assertRaisesRegex(ValueError,'研究条件不同'):self.review()
        self.rewrite_record(self.b,lambda r:r.update(status='failed'))
        with self.assertRaisesRegex(ValueError,'已完成'):self.review()
    def test_nonfinite_duplicate_and_out_of_boundary_labels_rejected(self):
        path=self.b.artifact_path/'observations.parquet';original=path.read_bytes()
        self.change_observations(self.b,lambda f:f.with_columns(pl.lit(float('inf')).alias('value')))
        with self.assertRaisesRegex(ValueError,'非有限'):self.review()
        path.write_bytes(original);self.change_observations(self.b,lambda f:pl.concat([f,f.head(1)]))
        with self.assertRaisesRegex(ValueError,'重复'):self.review()
        path.write_bytes(original)
        self.change_observations(self.b,lambda f:f.with_columns((pl.col('label_end_2')+pl.duration(days=100)).alias('label_end_2')))
        with self.assertRaisesRegex(ValueError,'越过'):self.review()
    def test_agent_contract_and_no_write_tool(self):
        api=MarketDataResearchAPI(self.output,self.root)
        args={'candidate_run_id':self.a.run_id,'baseline_run_id':self.b.run_id,'horizon':2}
        value=api.call('compare_factor_candidates',args);self.assertTrue(value['ok'],value)
        self.assertEqual(len(value['evidence']),2)
        for change in ({'horizon':True},{'horizon':0},{'horizon':3},{'candidate_run_id':'../escape'},{'execute':True}):
            self.assertFalse(api.call('compare_factor_candidates',{**args,**change})['ok'])
        self.assertFalse(api.call('approve_candidate',{})['ok'])
        self.assertFalse((self.output/'_jobs').exists())
