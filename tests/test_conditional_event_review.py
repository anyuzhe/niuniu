import json
import unittest
from datetime import datetime, timedelta
from copy import deepcopy
import polars as pl
import test_core
from quantlab.agent.conditional_events import conditional_event_review
from quantlab.agent.candidate_review import compare_candidate
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.workbench.jobs import prepare, execute
from quantlab.storage.artifact_integrity import snapshot_tree


def frame(rows):
    return pl.DataFrame([{'symbol':f's{i}', 'datetime':datetime(2025,1,1)+timedelta(days=d),
        'candidate':c,'baseline':b,'forward_5':v,'mae_5':r} for i,(d,c,b,v,r) in enumerate(rows)],
        schema_overrides={c:pl.Float64 for c in ('candidate','baseline','forward_5','mae_5')})


class ConditionalEventTests(unittest.TestCase):
    def review(self, rows, risk=True):return conditional_event_review(frame(rows),5,risk_available=risk)
    def test_date_equal_comparison_is_not_pooled_stock_days(self):
        rows=[(0,1,1,.1,-.02)]+[(0,0,1,0.,-.03)]*9+[(1,1,1,-.1,-.15),(1,0,1,-.2,-.3)]
        result=self.review(rows)
        self.assertAlmostEqual(result['paired_return_vs_baseline']['difference'],.07)
        self.assertAlmostEqual(result['paired_return_vs_rejected']['difference'],.1)
        self.assertEqual(result['paired_return_vs_rejected']['dates'],2)
        self.assertIsNone(result['p_value']);self.assertFalse(result['alpha_verified'])
    def test_missing_candidate_not_relabelled_as_rejected_or_zero(self):
        result=self.review([(0,1,1,.1,-.1),(0,0,1,.0,-.1),(0,None,1,-.9,None)])
        self.assertEqual(result['coverage']['candidate_unknown_baseline_events'],1)
        self.assertEqual(result['rejected']['events'],1)
        self.assertEqual(result['baseline_all_mature']['events'],3)
        self.assertEqual(result['baseline_on_selected_dates']['events'],2)
        self.assertAlmostEqual(result['paired_return_vs_baseline']['difference'],.05)
    def test_candidate_outside_baseline_never_treated_as_filter(self):
        for baseline in (0.,None):
            result=self.review([(0,1,baseline,.1,-.1)])
            self.assertEqual(result['status'],'not_a_nested_filter');self.assertNotIn('selected',result)
    def test_no_signal_is_missing_comparison_not_zero_profit(self):
        result=self.review([(0,0,1,.1,-.1)])
        self.assertEqual(result['status'],'no_selected_mature_events')
        self.assertIsNone(result['paired_return_vs_baseline']['difference'])
        self.assertEqual(result['coverage']['baseline_mature_dates_without_selection'],1)
        self.assertIsNone(result['selected']['return_tail']['worst_5pct_mean'])
    def test_no_filter_detected_without_fake_rejected_group(self):
        result=self.review([(0,1,1,.1,-.1),(1,1,1,.2,-.2)])
        self.assertEqual(result['status'],'no_rejected_mature_events')
        self.assertEqual(result['paired_return_vs_baseline']['difference'],0.)
        self.assertIsNone(result['paired_return_vs_rejected']['difference'])
    def test_maturity_never_defines_initial_selection(self):
        result=self.review([(0,1,1,None,None),(1,0,1,.1,-.1)])
        self.assertEqual(result['coverage']['selected_events'],1)
        self.assertEqual(result['coverage']['selected_pending_events'],1)
        self.assertEqual(result['selected']['events'],0)
    def test_disjoint_dates_not_paired(self):
        result=self.review([(0,1,1,.1,-.1),(1,0,1,.2,-.2)])
        self.assertEqual(result['status'],'no_same_date_selected_rejected')
        self.assertIsNone(result['paired_return_vs_rejected']['difference'])
    def test_tail_definition_ceil_count_event_weighted(self):
        result=self.review([(i,1,1,-i/100,-i/100) for i in range(40)])
        tail=result['selected']['return_tail']
        self.assertEqual(tail['tail_count'],2);self.assertAlmostEqual(tail['worst_5pct_mean'],-.385)
    def test_missing_risk_is_explicit_not_filled(self):
        result=self.review([(0,1,1,.1,None),(0,0,1,0.,None)],risk=False)
        self.assertFalse(result['selected']['mae_available']);self.assertIsNone(result['paired_mae_vs_baseline'])
    def test_nullable_paths_count_and_valid_zero_retained(self):
        result=self.review([(0,1,1,0.,0.),(0,1,1,-.1,None),(0,0,1,0.,-.2)])
        self.assertEqual(result['selected']['mae_missing_events'],1)
        self.assertEqual(result['selected']['mean_mae'],0.)
        self.assertEqual(result['selected']['mae_tail']['count'],1)
    def test_invalid_binary_rejected(self):
        with self.assertRaisesRegex(ValueError,'binary'):
            self.review([(0,2,1,.1,-.1)])
    def test_no_input_mutation(self):
        data=frame([(0,1,1,.1,-.1),(0,0,1,0.,-.2)]);old=data.clone()
        conditional_event_review(data,5,risk_available=True);self.assertTrue(data.equals(old))


class ConditionalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.root;self.out=self.root/'conditional-review'
        def spec(threshold):
            return {'question':'synthetic conditional comparison','symbols':list(self.fixture.symbols),
                'start':'2025-01-01','end':'2025-01-10','timeframe':'1d','adjustment':'raw',
                'factor':'COMB.CONDITION','version':'1.0.0','mode':'single','horizons':[2],
                'quantiles':3,'replay':True,'parameters':{'inputs':{'m':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':1}}},
                    'rule':{'input':'m','op':'gt','value':threshold}}}
        self.base=execute(prepare(spec(0.)),self.root,self.out)
        self.candidate=execute(prepare(spec(.035)),self.root,self.out)
    def test_production_archives_native_api_and_unchanged_sources(self):
        before=[snapshot_tree(self.out,r.run_id) for r in (self.base,self.candidate)]
        args={'candidate_run_id':self.candidate.run_id,'baseline_run_id':self.base.run_id,'horizon':2}
        api=MarketDataResearchAPI(self.out,self.root);result=api.call('compare_factor_candidates',args)
        self.assertTrue(result['ok'],result);ev=result['data']['conditional_events']
        self.assertEqual(ev['status'],'descriptive_comparison');self.assertGreater(ev['selected']['events'],0)
        self.assertEqual(ev['candidate_triggered_outside_baseline'],0)
        self.assertTrue(ev['selected']['mae_available']);self.assertIsNone(ev['p_value'])
        self.assertLess(len(json.dumps(result)),24000)
        self.assertEqual(before,[snapshot_tree(self.out,r.run_id) for r in (self.base,self.candidate)])
        self.assertFalse((self.out/'_jobs').exists())
    def test_risk_mismatch_rejected(self):
        p=self.candidate.artifact_path/'observations.parquet'
        pl.read_parquet(p).with_columns((pl.col('mae_2')-.01).alias('mae_2')).write_parquet(p)
        with self.assertRaisesRegex(ValueError,'MAE不一致'):
            compare_candidate(self.out,self.candidate.run_id,self.base.run_id,2)
    def test_optional_risk_absence_does_not_invent_fields(self):
        p=self.candidate.artifact_path/'observations.parquet';pl.read_parquet(p).drop('mae_2').write_parquet(p)
        result=compare_candidate(self.out,self.candidate.run_id,self.base.run_id,2)
        self.assertFalse(result['conditional_events']['selected']['mae_available'])
    def test_invalid_risk_rejected_not_dropped_for_better_outcome(self):
        for value in (float('inf'),.1):
            p=self.candidate.artifact_path/'observations.parquet'
            pl.read_parquet(p).with_columns(pl.lit(value).alias('mae_2')).write_parquet(p)
            with self.assertRaisesRegex(ValueError,'MAE包含'):
                compare_candidate(self.out,self.candidate.run_id,self.base.run_id,2)


class FrozenPilotProtocolTests(unittest.TestCase):
    def test_model_selected_specs_are_frozen_and_not_blind_claims(self):
        from pathlib import Path
        from quantlab.storage.codec import digest
        p=Path(__file__).resolve().parents[1]/'docs/reference/dip-factor-research-v1.json'
        protocol=json.loads(p.read_text());signed=dict(protocol);signature=signed.pop('protocol_digest')
        self.assertEqual(signature,digest(signed));self.assertFalse(protocol['data']['blind_holdout'])
        self.assertEqual(protocol['primary_horizon'],5)
        self.assertEqual(len(protocol['studies']),2)
        base,candidate=protocol['studies']
        for study in (base,candidate):
            self.assertEqual(study['spec_digest'],digest(study['spec']))
            prepare(study['spec'])
            self.assertEqual(study['spec']['horizons'],[3,5,10])
            self.assertTrue(study['spec']['replay'])
        self.assertEqual(base['spec']['parameters']['inputs'],candidate['spec']['parameters']['inputs'])
        for rule in base['spec']['parameters']['rule']['all']:
            self.assertIn(rule,candidate['spec']['parameters']['rule']['all'])
        self.assertFalse(protocol['readout']['execution_costs_modelled'])


if __name__=='__main__':unittest.main()
