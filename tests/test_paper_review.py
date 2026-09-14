import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.dynamic_paper import DynamicPaperAccount
from quantlab.execution.rules import MarketRules
from quantlab.trading.paper_review import PaperReviewService
from quantlab.trading.paper_lifecycle import PaperLifecycleAnalytics
from quantlab.trading.playbook_paper_plan import PlaybookPaperPlanService
from quantlab.trading.playbook_store import PlaybookStore
from quantlab.trading.strategy_intent import StrategyIntentService

TZ=ZoneInfo('Asia/Shanghai')
def dt(value):return datetime.fromisoformat(value).replace(tzinfo=TZ)

def day_bar(day,close):
    at=dt(day+'T15:00:00')
    return pl.DataFrame({'symbol':['sh.600000'],'datetime':[at],'available_at':[at],'timeframe':['1d'],
        'open':[close-0.2],'high':[close+0.3],'low':[close-0.4],'close':[close],'volume':[100000.0],'turnover':[1000000.0]})

def rules(day):
    return MarketRules([{'symbol':'sh.600000','effective_at':dt(day+'T00:00:00'),'available_at':dt(day+'T00:00:00'),
        'expires_at':dt(day+'T23:59:59'),'suspended':False,'st':False,'limit_up':30.0,'limit_down':3.0,
        'commission_bps':3.0,'minimum_commission':5.0,'sell_tax_bps':5.0,'transfer_bps':0.1,'source':'review fixture'}])


class PaperReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);clock=dt('2026-09-14T09:36:00')
        store=PlaybookStore(self.root,now_fn=lambda:clock)
        src=store.create_source(str(uuid4()),{'expert_key':'review-test','title':'source','source_type':'PUBLIC_POST',
            'locator':'https://example.invalid/review','available_at':'2026-09-13T20:00:00+08:00','content_hash':'a'*64,
            'completeness':'VERIFIED','archive_ref':'local:test','notes':''})
        definition=store.create_definition(str(uuid4()),{'playbook_key':'review-test','name':'Review','version':'v1','state':'DRAFT',
            'source_ids':[src['source_id']],'market_context':{},'eligibility':{'rule':'x'},'selection':{'rule':'y'},
            'veto':{},'entry':{},'confirm':{},'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':''})
        case=store.create_case(str(uuid4()),{'definition_id':definition['definition_id'],'trading_day':'2026-09-14','frame':'R1',
            'as_of':'2026-09-14T09:35:00+08:00','source_ids':[src['source_id']],'summary':'review case','notes':''})
        cs=store.create_candidate_set(str(uuid4()),{'case_id':case['case_id'],'definition_id':definition['definition_id'],
            'trading_day':'2026-09-14','frame':'R1','as_of':'2026-09-14T09:35:00+08:00','completeness':'FULL','pit_status':'STRICT_PIT',
            'universe_source':'test','generation_method':'test','candidates':[{'symbol':'sh.600000','eligibility_reasons':['selected'],
            'features':{},'evidence_ids':['e']}],'evidence_ids':['e']})
        self.selection=store.create_selection(str(uuid4()),{'candidate_set_id':cs['candidate_set_id'],'kind':'SYSTEM_PREDICTION',
            'selected_symbols':['sh.600000'],'ranked_symbols':['sh.600000'],'reasons':{'sh.600000':['selected']},
            'evidence_ids':['m'],'as_of':'2026-09-14T09:35:00+08:00','notes':''})
        self.intent=StrategyIntentService(self.root,now_fn=lambda:dt('2026-09-14T15:00:00'))
        self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R1','action':'WATCH','role_id':'system','ai_thesis':'watch','source':'review'})
        self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R2','action':'READY','role_id':'human','ai_thesis':'ready','transition_reason':'ready','source':'review'})
        self.plan_decision=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R3','action':'PLAN_OPEN','role_id':'human',
            'ai_thesis':'plan','confirm_trigger':'next open','transition_reason':'plan','source':'review'})
        self.plans=PlaybookPaperPlanService(self.root,now_fn=lambda:dt('2026-09-14T15:10:00'))
        self.plan=self.plans.create(self.selection['selection_id'],[self.plan_decision['decision_id']],'review_long',{'sh.600000':0.5},confirmed=True)
        self.cfg=ExecutionConfig(initial_cash=100000,top_n=1,exposure=1,price_mode='account')
        self.plans.execute_dynamic(self.plan['plan_id'],day_bar('2026-09-15',10.2),rules('2026-09-15'),self.cfg,
            confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        self.reviews=PaperReviewService(self.root,now_fn=lambda:dt('2026-09-18T16:00:00'))
    def tearDown(self):self.temp.cleanup()

    def account(self):return DynamicPaperAccount(self.root/'paper_dynamic/review_long.json')

    def test_d1_hash_is_invariant_after_d2_d3_data_arrive(self):
        d1=self.reviews.build(self.plan['plan_id'],'2026-09-15');self.assertEqual(d1['review_frame'],'D1')
        self.account().advance(day_bar('2026-09-16',10.8),rules('2026-09-16'),self.cfg,as_of=dt('2026-09-16T15:05:00'))
        self.account().advance(day_bar('2026-09-17',9.9),rules('2026-09-17'),self.cfg,as_of=dt('2026-09-17T15:05:00'))
        reviews=self.reviews.auto(self.plan['plan_id'])
        self.assertEqual([(r['review_day'],r['review_frame']) for r in reviews],
            [('2026-09-15','D1'),('2026-09-16','D2'),('2026-09-17','D3_PLUS')])
        self.assertEqual(reviews[0]['review_hash'],d1['review_hash'])
        self.assertFalse(any(r['future_data_used'] for r in reviews))
        self.assertAlmostEqual(reviews[0]['symbols'][0]['review_close'],10.2)
        self.assertAlmostEqual(reviews[1]['symbols'][0]['review_close'],10.8)
        self.assertAlmostEqual(reviews[2]['symbols'][0]['review_close'],9.9)

    def test_review_is_outcome_evidence_and_does_not_change_intent(self):
        before=self.intent.state('sh.600000')['current_decision']['decision_id']
        review=self.reviews.build(self.plan['plan_id'],'2026-09-15')
        after=self.intent.state('sh.600000')['current_decision']['decision_id']
        self.assertEqual(before,after);self.assertEqual(self.intent.state('sh.600000')['current_action'],'PLAN_OPEN')
        self.assertIn('Outcome evidence only',review['scope_note'])
        self.assertGreater(review['symbols'][0]['plan_fill_quantity'],0)

    def test_lifecycle_analytics_keeps_prediction_execution_and_review_separate(self):
        self.reviews.build(self.plan['plan_id'],'2026-09-15')
        value=PaperLifecycleAnalytics(self.root).build()
        self.assertEqual(value['system_predictions'],1);self.assertEqual(value['selected_predictions'],1)
        self.assertEqual(value['paper_plans'],1);self.assertEqual(value['paper_executions'],1)
        self.assertEqual(value['paper_executions_with_fill'],1);self.assertEqual(value['paper_executions_no_fill'],0)
        self.assertEqual(value['paper_reviews_by_frame'],{'D1':1});self.assertEqual(value['dynamic_account_count'],1)
        self.assertGreater(value['paper_fill_count'],0);self.assertGreaterEqual(value['paper_costs'].get('commission',0),0)
        self.assertFalse(value['automatic_real_trade'])



if __name__=='__main__':unittest.main()
