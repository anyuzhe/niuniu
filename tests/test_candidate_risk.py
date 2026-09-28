import json
import unittest
from datetime import datetime,timedelta
from unittest.mock import patch
import polars as pl
import test_conditional_event_review as fixture
from quantlab.agent.candidate_risk import risk_panels,audit_candidate_risk
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.storage.artifact_integrity import snapshot_tree


def frame(rows):
    # symbol, day, candidate, baseline, forward, MAE, endpoint_day
    origin=datetime(2025,1,1)
    return pl.DataFrame([{'symbol':s,'datetime':origin+timedelta(days=d),'candidate':c,'baseline':b,
        'forward_5':f,'mae_5':m,'label_end_5':None if end is None else origin+timedelta(days=end)}
        for s,d,c,b,f,m,end in rows],schema_overrides={k:pl.Float64 for k in ('candidate','baseline','forward_5','mae_5')})


class RiskPanelTests(unittest.TestCase):
    def test_disjoint_date_pairs_and_tail_weights_not_self_baseline(self):
        rows=[('s',0,1,1,.1,-.02,5)]+[(str(i),0,0,1,0.,-.03,5) for i in range(9)]+[('s',6,1,1,-.1,-.15,11),('r',6,0,1,-.2,-.3,11)]
        r=risk_panels(frame(rows),5)['panels']['all_signals']
        self.assertAlmostEqual(r['date_equal_pairs']['return']['difference'],.1)
        self.assertAlmostEqual(r['date_equal_pairs']['mae']['difference'],.08)
        self.assertAlmostEqual(r['event_equal_mae_tail_difference'],.15)
        self.assertEqual(r['selected']['events'],2);self.assertEqual(r['rejected']['events'],10)
        self.assertEqual(r['selected']['dates'],r['rejected']['dates'])
    def test_common_return_mae_support_then_match_dates(self):
        r=risk_panels(frame([('a',0,1,1,.1,None,5),('b',0,0,1,.0,-.3,5),
            ('a',6,1,1,.0,0.,11),('b',6,0,1,-.1,-.2,11),('c',6,None,1,-.9,-.9,11)]),5)['panels']['all_signals']
        self.assertEqual(r['coverage']['unknown_candidate_events'],1)
        self.assertEqual(r['coverage']['mature_missing_mae_events'],1)
        self.assertEqual(r['coverage']['events_without_opposite_group_date'],1)
        self.assertEqual(r['coverage']['matched_events'],2)
        self.assertEqual(r['selected']['mae_tail']['count'],r['selected']['return_tail']['count'])
        self.assertEqual(r['selected']['event_equal_mean_mae'],0.)
    def test_first_signal_schedule_ignores_membership_maturity_and_outcomes(self):
        rows=[('a',0,None,1,None,None,5),('a',1,1,1,.9,0.,6),('a',5,1,1,.9,0.,10),
              ('a',6,1,1,.2,-.1,11),('r',6,0,1,0.,-.3,11)]
        data=frame(rows);r=risk_panels(data,5)['panels']['nonoverlapping']
        self.assertEqual(r['coverage']['overlap_excluded_events'],2)
        self.assertEqual(r['coverage']['unknown_candidate_events'],1)
        self.assertEqual(r['selected']['events'],1)
        changed=data.with_columns(pl.lit(-.99).alias('forward_5'),pl.lit(-.99).alias('mae_5'),pl.lit(0.).alias('candidate'))
        self.assertEqual(r['scheduled_key_sha256'],risk_panels(changed,5)['panels']['nonoverlapping']['scheduled_key_sha256'])
    def test_missing_outcome_not_replaced_by_next_winner(self):
        data=frame([('a',0,1,1,None,None,5),('a',1,1,1,.8,-.01,6),('b',0,0,1,0.,-.2,5)])
        r=risk_panels(data,5)['panels']['nonoverlapping']
        self.assertEqual(r['coverage']['overlap_excluded_events'],1)
        self.assertEqual(r['coverage']['pending_forward_events'],1)
        self.assertIsNone(r['date_equal_pairs']['mae']['difference'])
    def test_no_endpoint_final_signal_stays_pending(self):
        r=risk_panels(frame([('a',0,1,1,None,None,None),('a',1,1,1,None,None,None)]),5)
        self.assertEqual(r['panels']['nonoverlapping']['coverage']['scheduled_baseline_events'],1)
        self.assertEqual(r['panels']['nonoverlapping']['coverage']['pending_forward_events'],1)
    def test_no_opposite_group_is_missing_not_zero(self):
        r=risk_panels(frame([('a',0,1,1,.1,-.1,5)]),5)
        for p in r['panels'].values():
            self.assertEqual(p['status'],'no_common_complete_dates')
            self.assertIsNone(p['date_equal_pairs']['mae']['difference'])
            self.assertIsNone(p['event_equal_mae_tail_difference'])
        self.assertIsNone(r['p_value']);self.assertFalse(r['alpha_verified'])
    def test_not_nested_returns_no_numbers(self):
        r=risk_panels(frame([('a',0,1,0,.1,-.1,5)]),5)
        self.assertEqual(r['status'],'not_a_nested_filter');self.assertEqual(r['panels'],{})
    def test_no_source_mutation_and_order_independence(self):
        data=frame([('a',0,1,1,.1,-.1,5),('b',0,0,1,0.,-.2,5)]);old=data.clone()
        self.assertEqual(risk_panels(data,5),risk_panels(data.reverse(),5));self.assertTrue(data.equals(old))
    def test_invalid_values_keys_and_endpoints_rejected(self):
        valid=frame([('a',0,1,1,.1,-.1,5)])
        for name,value in [('candidate',2.),('forward_5',float('nan')),('mae_5',float('-inf')),('mae_5',.1)]:
            with self.subTest(name=name,value=value),self.assertRaises(ValueError):risk_panels(valid.with_columns(pl.lit(value).alias(name)),5)
        for h in (True,0,1001):
            with self.assertRaises(ValueError):risk_panels(valid,h)
        with self.assertRaises(ValueError):risk_panels(pl.concat([valid,valid]),5)
        for e in (0,None):
            with self.assertRaises(ValueError):risk_panels(frame([('a',0,1,1,.1,-.1,e)]),5)
        with self.assertRaises(ValueError):risk_panels(valid.drop('mae_5'),5)
    def test_tail_retains_fixed_worst_five_percent_and_full_negative_values(self):
        rows=[(str(i),0,1,1,-i/100,-i/100,5) for i in range(40)]+[('b',0,0,1,0.,0.,5)]
        r=risk_panels(frame(rows),5)['panels']['all_signals']
        self.assertEqual(r['selected']['mae_tail']['tail_count'],2)
        self.assertAlmostEqual(r['selected']['mae_tail']['worst_5pct_mean'],-.385)


class RiskArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.ConditionalArchiveTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.out=self.fx.out;self.c=self.fx.candidate.run_id;self.b=self.fx.base.run_id
        self.args={'candidate_run_id':self.c,'baseline_run_id':self.b,'horizon':2}
    def test_native_api_returns_bounded_deterministic_readonly_evidence(self):
        before=[snapshot_tree(self.out,r) for r in (self.c,self.b)]
        api=ReadOnlyResearchAPI(self.out);r=api.call('audit_factor_risk',self.args)
        self.assertTrue(r['ok'],r);self.assertEqual(r,api.call('audit_factor_risk',self.args))
        self.assertLess(len(json.dumps(r)),24000);self.assertIn('nonoverlapping',r['data']['panels'])
        self.assertEqual(before,[snapshot_tree(self.out,x) for x in (self.c,self.b)])
        self.assertFalse((self.out/'_jobs').exists())
    def test_archive_key_loss_and_risk_mismatch_rejected(self):
        p=self.fx.candidate.artifact_path/'observations.parquet';old=pl.read_parquet(p)
        old.slice(1).write_parquet(p)
        with self.assertRaisesRegex(ValueError,'identical saved key'):audit_candidate_risk(self.out,**self.args)
        old.with_columns((pl.col('mae_2')-.01).alias('mae_2')).write_parquet(p)
        with self.assertRaisesRegex(ValueError,'MAE differs'):audit_candidate_risk(self.out,**self.args)
    def test_missing_risk_and_changed_source_before_return_rejected(self):
        p=self.fx.candidate.artifact_path/'observations.parquet';old=pl.read_parquet(p)
        old.drop('mae_2').write_parquet(p)
        with self.assertRaisesRegex(ValueError,'saved MAE'):audit_candidate_risk(self.out,**self.args)
        old.write_parquet(p)
        with patch('quantlab.agent.candidate_risk.verify_tree',side_effect=ValueError('source changed')):
            self.assertFalse(ReadOnlyResearchAPI(self.out).call('audit_factor_risk',self.args)['ok'])
    def test_malformed_request_and_unrelated_profiles_do_not_gain_tools(self):
        api=ReadOnlyResearchAPI(self.out)
        for args in ({**self.args,'execute':True},{**self.args,'candidate_run_id':'../escape'},{**self.args,'horizon':True}):
            self.assertFalse(api.call('audit_factor_risk',args)['ok'])
        from quantlab.agent.chat_runtime import ChatRuntime
        for profile in ('everyday','evidence'):
            runtime=ChatRuntime(self.out,self.fx.root,tool_profile=profile,local_data_only=True)
            self.assertNotIn('audit_factor_risk',{t['name'] for t in runtime.api.schemas()})
            self.assertFalse(runtime.api.call('audit_factor_risk',self.args)['ok'])
    def test_actual_chat_dispatch_without_queue_one_canonical_result(self):
        from quantlab.agent.chat_runtime import ChatRuntime
        from quantlab.agent.model_config import ModelConfig
        class Transport:
            def run(inner,system,messages,tools,dispatch,emit,stop):
                self.assertEqual([t['name'] for t in tools].count('audit_factor_risk'),1)
                r=dispatch('audit_factor_risk',self.args,'one-audit');self.assertTrue(r['ok'],r)
                return {'text':'仅有界读取原始证据。','provider':'fixture','model':'fixture'}
        runtime=ChatRuntime(self.out,self.fx.root,lambda:self.fail('queue acquired'),local_data_only=True)
        cid=runtime.store.create();r=runtime.send(cid,'风险核对',ModelConfig(max_context_chars=200000),allow_send=True,provider=Transport())
        self.assertEqual(r['tool_calls'],1)
        self.assertEqual(sum(e['kind']=='tool_result' for e in runtime.store.events(cid)['events']),1)
        self.assertFalse((self.out/'_jobs').exists())


if __name__=='__main__':unittest.main()
