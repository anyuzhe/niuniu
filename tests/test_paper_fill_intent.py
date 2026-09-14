import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.rules import MarketRules
from quantlab.trading.paper_fill_intent import PaperFillIntentBridge,PaperFillIntentError
from quantlab.trading.paper_lifecycle import PaperLifecycleAnalytics
from quantlab.trading.playbook_paper_plan import PlaybookPaperPlanService
from quantlab.trading.playbook_store import PlaybookStore
from quantlab.trading.strategy_intent import StrategyIntentService

TZ=ZoneInfo('Asia/Shanghai')
def dt(value):return datetime.fromisoformat(value).replace(tzinfo=TZ)


class PaperFillIntentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        clock=dt('2026-09-14T09:36:00');store=PlaybookStore(self.root,now_fn=lambda:clock)
        source=store.create_source(str(uuid4()),{'expert_key':'fill-test','title':'source','source_type':'PUBLIC_POST',
            'locator':'https://example.invalid/fill','available_at':'2026-09-13T20:00:00+08:00','content_hash':'a'*64,
            'completeness':'VERIFIED','archive_ref':'local:test','notes':''})
        definition=store.create_definition(str(uuid4()),{'playbook_key':'fill-test','name':'Fill bridge','version':'v1','state':'DRAFT',
            'source_ids':[source['source_id']],'market_context':{},'eligibility':{'rule':'x'},'selection':{'rule':'y'},
            'veto':{},'entry':{},'confirm':{},'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':''})
        case=store.create_case(str(uuid4()),{'definition_id':definition['definition_id'],'trading_day':'2026-09-14','frame':'R1',
            'as_of':'2026-09-14T09:35:00+08:00','source_ids':[source['source_id']],'summary':'fill case','notes':''})
        cset=store.create_candidate_set(str(uuid4()),{'case_id':case['case_id'],'definition_id':definition['definition_id'],
            'trading_day':'2026-09-14','frame':'R1','as_of':'2026-09-14T09:35:00+08:00','completeness':'FULL','pit_status':'STRICT_PIT',
            'universe_source':'test','generation_method':'test','candidates':[{'symbol':'sh.600000','eligibility_reasons':['selected'],
            'features':{},'evidence_ids':['e1']}],'evidence_ids':['e1']})
        self.selection=store.create_selection(str(uuid4()),{'candidate_set_id':cset['candidate_set_id'],'kind':'SYSTEM_PREDICTION',
            'selected_symbols':['sh.600000'],'ranked_symbols':['sh.600000'],'reasons':{'sh.600000':['selected']},
            'evidence_ids':['model'],'as_of':'2026-09-14T09:35:00+08:00','notes':''})
        self.intent=StrategyIntentService(self.root,now_fn=lambda:dt('2026-09-14T15:00:00'))
        self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R1','action':'WATCH',
            'role_id':'system','ai_thesis':'selected','source':'fill-test'})
        self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R2','action':'READY',
            'role_id':'human','ai_thesis':'ready','transition_reason':'host ready','source':'fill-test'})
        self.plan_decision=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R3','action':'PLAN_OPEN',
            'role_id':'human','ai_thesis':'paper plan','confirm_trigger':'next open','transition_reason':'host plan','source':'fill-test'})
        self.plans=PlaybookPaperPlanService(self.root,now_fn=lambda:dt('2026-09-14T15:10:00'))
        self.plan=self.plans.create(self.selection['selection_id'],[self.plan_decision['decision_id']],'fill_test',{'sh.600000':0.5},confirmed=True)
        self.cfg=ExecutionConfig(initial_cash=100000,top_n=1,exposure=1,price_mode='account')
    def tearDown(self):self.temp.cleanup()

    def bars(self):
        t=dt('2026-09-15T15:00:00')
        return pl.DataFrame({'symbol':['sh.600000'],'datetime':[t],'available_at':[t],'timeframe':['1d'],
            'open':[10.0],'high':[10.5],'low':[9.8],'close':[10.2],'volume':[100000.0],'turnover':[1000000.0]})

    def rules(self,limit_up=20.0):
        return MarketRules([{'symbol':'sh.600000','effective_at':dt('2026-09-15T00:00:00'),'available_at':dt('2026-09-15T00:00:00'),
            'expires_at':dt('2026-09-16T00:00:00'),'suspended':False,'st':False,'limit_up':limit_up,'limit_down':5.0,
            'commission_bps':3.0,'minimum_commission':5.0,'sell_tax_bps':5.0,'transfer_bps':0.1,'source':'fill fixture'}])

    def execute(self,limit_up=20.0):
        return self.plans.execute(self.plan['plan_id'],self.bars(),self.rules(limit_up),self.cfg,confirmed=True,as_of=dt('2026-09-15T15:05:00'))

    def bridge(self):return PaperFillIntentBridge(self.root,now_fn=lambda:dt('2026-09-15T15:10:00'))

    def test_fill_requires_host_confirmation_then_records_open_at_fill_day_r1(self):
        self.execute();bridge=self.bridge()
        with self.assertRaises(PaperFillIntentError) as confirm:bridge.apply(self.plan['plan_id'])
        self.assertEqual(confirm.exception.code,'CONFIRMATION_REQUIRED')
        receipt=bridge.apply(self.plan['plan_id'],confirmed=True)
        self.assertEqual(receipt['open_recorded'],1);row=receipt['results'][0];self.assertEqual(row['status'],'OPEN_RECORDED')
        current=StrategyIntentService(self.root).state('sh.600000')['current_decision']
        self.assertEqual((current['trading_day'],current['frame'],current['action']),('2026-09-15','R1','OPEN'))
        self.assertEqual(current['role_id'],'system');self.assertEqual(current['source'],'paper_fill_intent_bridge')
        self.assertIn('paper_plan:',current['research_evidence_ids'][0])

    def test_no_fill_keeps_plan_open(self):
        executed=self.execute(limit_up=10.0);self.assertEqual(executed['status'],'EXECUTED_NO_FILL')
        receipt=self.bridge().apply(self.plan['plan_id'],confirmed=True)
        self.assertEqual(receipt['no_fill'],1);self.assertEqual(receipt['results'][0]['status'],'NO_FILL')
        self.assertEqual(StrategyIntentService(self.root).state('sh.600000')['current_action'],'PLAN_OPEN')
        lifecycle=PaperLifecycleAnalytics(self.root).build();self.assertEqual(lifecycle['paper_executions_no_fill'],1)
        self.assertEqual(lifecycle['paper_rejection_reasons'].get('session_price_limit'),1)

    def test_human_state_move_after_fill_wins(self):
        self.execute()
        service=StrategyIntentService(self.root,now_fn=lambda:dt('2026-09-15T10:00:00'))
        moved=service.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-15','frame':'R1','action':'INVALIDATED',
            'role_id':'human','ai_thesis':'human veto after execution test','invalidation':'manual risk veto',
            'transition_reason':'manual override','source':'human'})
        self.assertEqual(moved['action'],'INVALIDATED')
        receipt=self.bridge().apply(self.plan['plan_id'],confirmed=True)
        self.assertEqual(receipt['results'][0]['status'],'STATE_MOVED')
        self.assertEqual(StrategyIntentService(self.root).state('sh.600000')['current_action'],'INVALIDATED')

    def test_receipt_crash_after_decision_write_recovers_existing_open(self):
        self.execute();bridge=self.bridge()
        with patch('quantlab.trading.paper_fill_intent.write_checked',side_effect=OSError('receipt crash')):
            with self.assertRaises(OSError):bridge.apply(self.plan['plan_id'],confirmed=True)
        self.assertEqual(StrategyIntentService(self.root).state('sh.600000')['current_action'],'OPEN')
        recovered=bridge.apply(self.plan['plan_id'],confirmed=True)
        self.assertEqual(recovered['open_recorded'],1);self.assertEqual(recovered['results'][0]['status'],'OPEN_RECORDED')
        decisions=bridge.decisions.list(symbol='sh.600000',trading_day='2026-09-15',frame='R1',include_superseded=True,limit=20)['records']
        self.assertEqual(len([d for d in decisions if d.get('source')=='paper_fill_intent_bridge']),1)


if __name__=='__main__':unittest.main()
