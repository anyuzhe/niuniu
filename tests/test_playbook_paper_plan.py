import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.rules import MarketRules
from quantlab.trading.playbook_paper_plan import PlaybookPaperPlanError,PlaybookPaperPlanService
from quantlab.trading.playbook_store import PlaybookStore
from quantlab.trading.strategy_intent import StrategyIntentService

TZ=ZoneInfo('Asia/Shanghai')


def dt(value):return datetime.fromisoformat(value).replace(tzinfo=TZ)


class PlaybookPaperPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.clock=dt('2026-09-14T09:36:00')
        store=PlaybookStore(self.root,now_fn=lambda:self.clock)
        source=store.create_source(str(uuid4()),{'expert_key':'paper-test','title':'source','source_type':'PUBLIC_POST',
            'locator':'https://example.invalid/source','available_at':'2026-09-13T20:00:00+08:00','content_hash':'a'*64,
            'completeness':'VERIFIED','archive_ref':'local:test','notes':''})
        definition=store.create_definition(str(uuid4()),{'playbook_key':'paper-test','name':'Paper bridge','version':'v1','state':'DRAFT',
            'source_ids':[source['source_id']],'market_context':{},'eligibility':{'rule':'x'},'selection':{'rule':'y'},
            'veto':{},'entry':{},'confirm':{},'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':''})
        case=store.create_case(str(uuid4()),{'definition_id':definition['definition_id'],'trading_day':'2026-09-14','frame':'R1',
            'as_of':'2026-09-14T09:35:00+08:00','source_ids':[source['source_id']],
            'summary':'paper case','notes':''})
        cset=store.create_candidate_set(str(uuid4()),{'case_id':case['case_id'],'definition_id':definition['definition_id'],
            'trading_day':'2026-09-14','frame':'R1','as_of':'2026-09-14T09:35:00+08:00','completeness':'FULL',
            'pit_status':'STRICT_PIT','universe_source':'test','generation_method':'test','candidates':[
                {'symbol':'sh.600000','eligibility_reasons':['selected'],'features':{},'evidence_ids':['e1']}],
            'evidence_ids':['e1']})
        self.selection=store.create_selection(str(uuid4()),{'candidate_set_id':cset['candidate_set_id'],'kind':'SYSTEM_PREDICTION',
            'selected_symbols':['sh.600000'],'ranked_symbols':['sh.600000'],'reasons':{'sh.600000':['selected']},
            'evidence_ids':['model'],'as_of':'2026-09-14T09:35:00+08:00','notes':''})
        self.intent=StrategyIntentService(self.root,now_fn=lambda:dt('2026-09-14T10:31:00'))
        self.watch=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R1','action':'WATCH',
            'role_id':'system','ai_thesis':'system prediction selected','source':'paper-test'})
        self.ready=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R2','action':'READY',
            'role_id':'human','ai_thesis':'host confirms readiness','transition_reason':'人工确认准备','source':'paper-test'})
        self.plan=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R3','action':'PLAN_OPEN',
            'role_id':'human','ai_thesis':'host paper plan','confirm_trigger':'next open','transition_reason':'人工进入模拟开仓计划','source':'paper-test'})
        self.service=PlaybookPaperPlanService(self.root,now_fn=lambda:dt('2026-09-14T15:10:00'))
    def tearDown(self):self.temp.cleanup()

    def make_plan(self,**kwargs):
        args=dict(selection_id=self.selection['selection_id'],decision_ids=[self.plan['decision_id']],
            account_name='playbook_test',target_weights={'sh.600000':0.5},confirmed=True)
        args.update(kwargs);return self.service.create(**args)

    def bars(self):
        t=dt('2026-09-15T15:00:00')
        return pl.DataFrame({'symbol':['sh.600000'],'datetime':[t],'available_at':[t],'timeframe':['1d'],
            'open':[10.0],'high':[11.0],'low':[9.8],'close':[10.5],'volume':[100000.0],'turnover':[1000000.0]})

    def rules(self):
        return MarketRules([{'symbol':'sh.600000','effective_at':dt('2026-09-15T00:00:00'),
            'available_at':dt('2026-09-15T00:00:00'),'expires_at':dt('2026-09-16T00:00:00'),
            'suspended':False,'st':False,'limit_up':20.0,'limit_down':5.0,'commission_bps':3.0,
            'minimum_commission':5.0,'sell_tax_bps':5.0,'transfer_bps':0.1,'source':'synthetic official-rule fixture'}])

    def test_create_requires_confirmation_and_current_plan_open(self):
        with self.assertRaises(PlaybookPaperPlanError) as confirm:
            self.service.create(self.selection['selection_id'],[self.plan['decision_id']],'playbook_test',{'sh.600000':0.5})
        self.assertEqual(confirm.exception.code,'CONFIRMATION_REQUIRED')
        with self.assertRaises(PlaybookPaperPlanError) as action:
            self.service.create(self.selection['selection_id'],[self.ready['decision_id']],'playbook_test',{'sh.600000':0.5},confirmed=True)
        self.assertEqual(action.exception.code,'PLAN_OPEN_REQUIRED')

    def test_plan_is_idempotent_and_does_not_create_paper_account(self):
        plan=self.make_plan();again=self.make_plan()
        self.assertEqual(plan['plan_id'],again['plan_id']);self.assertEqual(plan['status'],'PENDING_MARKET_INPUT')
        self.assertFalse((self.root/'paper/playbook_test.json').exists())
        self.assertEqual(self.intent.state('sh.600000')['current_action'],'PLAN_OPEN')

    def test_superseded_decision_invalidates_existing_plan_before_execution(self):
        plan=self.make_plan()
        revised=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R3','action':'PLAN_OPEN',
            'role_id':'human','ai_thesis':'revised plan evidence','confirm_trigger':'next open','revision_of':self.plan['decision_id'],
            'source':'paper-test'})
        self.assertEqual(revised['action'],'PLAN_OPEN')
        with self.assertRaises(PlaybookPaperPlanError) as changed:
            self.service.execute(plan['plan_id'],self.bars(),self.rules(),confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        self.assertEqual(changed.exception.code,'SOURCE_CHANGED')

    def test_execute_requires_confirmation_and_exact_universe(self):
        plan=self.make_plan()
        with self.assertRaises(PlaybookPaperPlanError) as confirm:
            self.service.execute(plan['plan_id'],self.bars(),self.rules(),as_of=dt('2026-09-15T15:05:00'))
        self.assertEqual(confirm.exception.code,'CONFIRMATION_REQUIRED')
        extra=self.bars().vstack(self.bars().with_columns(pl.lit('sz.000001').alias('symbol')))
        with self.assertRaises(PlaybookPaperPlanError) as universe:
            self.service.execute(plan['plan_id'],extra,self.rules(),confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        self.assertEqual(universe.exception.code,'BARS_UNIVERSE_MISMATCH')

    def test_execution_creates_audited_fill_but_does_not_auto_open_intent(self):
        plan=self.make_plan();cfg=ExecutionConfig(initial_cash=100000,exposure=1,top_n=1,price_mode='account')
        result=self.service.execute(plan['plan_id'],self.bars(),self.rules(),cfg,confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        self.assertEqual(result['status'],'EXECUTED_WITH_FILL');self.assertTrue(result['execution']['new_fills'])
        self.assertTrue(result['execution']['new_order_ids']);self.assertEqual(result['execution']['account_revision'],1)
        self.assertEqual(self.intent.state('sh.600000')['current_action'],'PLAN_OPEN')
        same=self.service.execute(plan['plan_id'],self.bars(),self.rules(),cfg,confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        self.assertEqual(same['execution']['account_revision'],1)
        self.assertEqual(same['execution']['new_order_ids'],result['execution']['new_order_ids'])

    def test_existing_account_with_different_universe_is_rejected(self):
        # First create an unrelated fixed-universe account through the existing PaperAccount.
        from quantlab.execution.paper import PaperAccount
        t=dt('2026-09-15T15:00:00')
        bars=pl.DataFrame({'symbol':['sz.000001'],'datetime':[t],'available_at':[t],'timeframe':['1d'],
            'open':[10.0],'high':[10.5],'low':[9.8],'close':[10.2],'volume':[10000.0],'turnover':[100000.0]})
        targets=pl.DataFrame({'symbol':['sz.000001'],'datetime':[dt('2026-09-14T15:00:00')],
            'available_at':[dt('2026-09-14T15:00:00')],'weight':[0.5]})
        rules=MarketRules([{'symbol':'sz.000001','effective_at':dt('2026-09-15T00:00:00'),
            'available_at':dt('2026-09-15T00:00:00'),'expires_at':dt('2026-09-16T00:00:00'),
            'suspended':False,'st':False,'limit_up':20.0,'limit_down':5.0,'commission_bps':3.0,
            'minimum_commission':5.0,'sell_tax_bps':5.0,'transfer_bps':0.1,'source':'fixture'}])
        PaperAccount(self.root/'paper/playbook_test.json').advance(bars,targets,rules,ExecutionConfig(price_mode='account'),as_of=dt('2026-09-15T15:05:00'))
        plan=self.make_plan()
        with self.assertRaises(PlaybookPaperPlanError) as mismatch:
            self.service.execute(plan['plan_id'],self.bars(),self.rules(),ExecutionConfig(price_mode='account'),confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        self.assertEqual(mismatch.exception.code,'ACCOUNT_UNIVERSE_MISMATCH')

    def test_dynamic_execution_uses_separate_long_account_and_is_idempotent(self):
        plan=self.make_plan(account_name='long_playbook');cfg=ExecutionConfig(initial_cash=100000,exposure=1,top_n=1,price_mode='account')
        result=self.service.execute_dynamic(plan['plan_id'],self.bars(),self.rules(),cfg,confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        self.assertEqual(result['status'],'EXECUTED_WITH_FILL');self.assertEqual(result['execution']['mode'],'dynamic_v1')
        self.assertTrue((self.root/'paper_dynamic/long_playbook.json').exists())
        self.assertFalse((self.root/'paper/long_playbook.json').exists())
        self.assertEqual(result['execution']['portfolio_target'],{'sh.600000':0.5})
        same=self.service.execute_dynamic(plan['plan_id'],self.bars(),self.rules(),cfg,confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        self.assertEqual(same['execution']['account_revision'],1)
        self.assertEqual(same['execution']['new_order_ids'],result['execution']['new_order_ids'])


    def test_crash_after_account_write_recovers_fill_receipt(self):
        from unittest.mock import patch
        plan=self.make_plan();cfg=ExecutionConfig(initial_cash=100000,exposure=1,top_n=1,price_mode='account')
        original=self.service._save;calls={'n':0}
        def flaky(state):
            calls['n']+=1
            if calls['n']==2:raise OSError('simulated crash after paper account commit')
            return original(state)
        with patch.object(self.service,'_save',side_effect=flaky):
            with self.assertRaises(OSError):
                self.service.execute(plan['plan_id'],self.bars(),self.rules(),cfg,confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        # Account already contains the fill, while PaperPlan remains at the durable RESERVED checkpoint.
        from quantlab.execution.paper import PaperAccount
        committed=PaperAccount(self.root/'paper/playbook_test.json').read()
        self.assertEqual(committed['revision'],1);self.assertTrue(committed['fills'])
        reserved=self.service.get(plan['plan_id']);self.assertEqual(reserved['execution']['status'],'RESERVED')
        recovered=self.service.execute(plan['plan_id'],self.bars(),self.rules(),cfg,confirmed=True,as_of=dt('2026-09-15T15:05:00'))
        self.assertEqual(recovered['status'],'EXECUTED_WITH_FILL')
        self.assertEqual(len(recovered['execution']['new_fills']),len(committed['fills']))
        self.assertEqual(recovered['execution']['account_revision'],1)


if __name__=='__main__':unittest.main()
