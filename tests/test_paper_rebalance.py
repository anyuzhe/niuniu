import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.dynamic_paper import DynamicPaperAccount
from quantlab.execution.rules import MarketRules
from quantlab.trading.paper_rebalance import PaperRebalanceError,PaperRebalancePlanService
from quantlab.trading.paper_rebalance_outcome import PaperRebalanceOutcomeBridge
from quantlab.trading.paper_lifecycle import PaperLifecycleAnalytics
from quantlab.trading.strategy_intent import StrategyIntentService

TZ=ZoneInfo('Asia/Shanghai')
def dt(value):return datetime.fromisoformat(value).replace(tzinfo=TZ)

def bar(day,price=10.0):
    at=dt(day+'T15:00:00')
    return pl.DataFrame({'symbol':['sh.600000'],'datetime':[at],'available_at':[at],'timeframe':['1d'],
        'open':[price],'high':[price+0.4],'low':[price-0.3],'close':[price+0.2],'volume':[100000.0],'turnover':[1000000.0]})

def rules(day):
    return MarketRules([{'symbol':'sh.600000','effective_at':dt(day+'T00:00:00'),'available_at':dt(day+'T00:00:00'),
        'expires_at':dt(day+'T23:59:59'),'suspended':False,'st':False,'limit_up':30.0,'limit_down':3.0,
        'commission_bps':3.0,'minimum_commission':5.0,'sell_tax_bps':5.0,'transfer_bps':0.1,'source':'rebalance fixture'}])


class PaperRebalanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.account_name='long'
        self.cfg=ExecutionConfig(initial_cash=100000,top_n=10,exposure=1,price_mode='account')
        self.account=DynamicPaperAccount(self.root/'paper_dynamic/long.json')
        self.account.advance(bar('2026-09-15'),rules('2026-09-15'),self.cfg,as_of=dt('2026-09-15T15:05:00'),
            target_at=dt('2026-09-14T15:10:00'),target_weights={'sh.600000':0.5},target_source_ref='initial')
        self.intent=StrategyIntentService(self.root,now_fn=lambda:dt('2026-09-14T15:00:00'))
        self.watch=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'PREP','action':'WATCH','role_id':'human','ai_thesis':'watch','source':'rebalance'})
        self.ready=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R1','action':'READY','role_id':'human','ai_thesis':'ready','transition_reason':'ready','source':'rebalance'})
        self.plan=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R2','action':'PLAN_OPEN','role_id':'human','ai_thesis':'plan','confirm_trigger':'open','transition_reason':'plan','source':'rebalance'})
        self.open=self.intent.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-14','frame':'R3','action':'OPEN','role_id':'human','ai_thesis':'opened','confirm_trigger':'fill','hold_reason':'paper open','transition_reason':'open','source':'rebalance'})
    def tearDown(self):self.temp.cleanup()

    def service(self,when):return PaperRebalancePlanService(self.root,now_fn=lambda:dt(when))

    def decision(self,action,day='2026-09-16',**extra):
        service=StrategyIntentService(self.root,now_fn=lambda:dt(day+'T16:00:00'))
        base={'symbol':'sh.600000','trading_day':day,'frame':'D1','action':action,'role_id':'human','ai_thesis':action,
            'transition_reason':action+' target','reference_decision_id':self.open['decision_id'],'source':'rebalance'}
        if action=='ADD':base.update(confirm_trigger='add fill',hold_reason='keep')
        if action=='REDUCE':base.update(exit_condition='reduce target')
        if action in ('EXIT','INVALIDATED'):base.update(exit_condition='exit target',invalidation='exit')
        base.update(extra);return service.transition(str(uuid4()),base)

    def test_add_requires_add_decision_and_executes_higher_target(self):
        add=self.decision('ADD');service=self.service('2026-09-16T16:05:00')
        plan=service.create(self.account_name,[add['decision_id']],{'sh.600000':0.7},confirmed=True)
        result=service.execute(plan['plan_id'],bar('2026-09-17',10.5),rules('2026-09-17'),self.cfg,confirmed=True,as_of=dt('2026-09-17T15:05:00'))
        self.assertEqual(result['status'],'EXECUTED_WITH_FILL');self.assertEqual(result['spec']['changes'][0]['kind'],'ADD')
        self.assertEqual(self.account.read()['target_events'][-1]['weights'],{'sh.600000':0.7})
        self.assertTrue(any(fill['side']=='buy' for fill in result['execution']['new_fills']))
        outcome=PaperRebalanceOutcomeBridge(self.root,now_fn=lambda:dt('2026-09-17T15:10:00')).apply(plan['plan_id'],confirmed=True)
        self.assertEqual(outcome['results'][0]['status'],'HOLD_RECORDED')
        self.assertEqual(StrategyIntentService(self.root).state('sh.600000')['current_action'],'HOLD')
        lifecycle=PaperLifecycleAnalytics(self.root).build();self.assertEqual(lifecycle['paper_rebalances'],1)
        self.assertEqual(lifecycle['paper_rebalance_executions'],1);self.assertGreater(lifecycle['paper_fill_count'],0)

    def test_wrong_action_and_new_symbol_are_blocked(self):
        service=self.service('2026-09-16T16:05:00')
        with self.assertRaises(PaperRebalanceError) as wrong:
            service.create(self.account_name,[self.open['decision_id']],{'sh.600000':0.3},confirmed=True)
        self.assertIn(wrong.exception.code,('DECISION_NOT_CURRENT','ACTION_MISMATCH'))
        add=self.decision('ADD')
        with self.assertRaises(PaperRebalanceError) as new:
            service.create(self.account_name,[add['decision_id']],{'sh.600000':0.5,'sz.000001':0.1},confirmed=True)
        self.assertEqual(new.exception.code,'NEW_ENTRY_REQUIRES_PLAYBOOK_PLAN')

    def test_exit_decision_can_target_cash_and_sell_position(self):
        exit_decision=self.decision('EXIT');service=self.service('2026-09-16T16:05:00')
        plan=service.create(self.account_name,[exit_decision['decision_id']],{},confirmed=True)
        result=service.execute(plan['plan_id'],bar('2026-09-17',10.5),rules('2026-09-17'),self.cfg,confirmed=True,as_of=dt('2026-09-17T15:05:00'))
        self.assertEqual(result['spec']['changes'][0]['kind'],'EXIT');self.assertEqual(result['execution']['summary']['ending_positions'],{})
        self.assertTrue(any(fill['side']=='sell' for fill in result['execution']['new_fills']))
        self.assertEqual(StrategyIntentService(self.root).state('sh.600000')['current_action'],'EXIT')
        outcome=PaperRebalanceOutcomeBridge(self.root,now_fn=lambda:dt('2026-09-17T15:10:00')).apply(plan['plan_id'],confirmed=True)
        self.assertEqual(outcome['results'][0]['status'],'EXIT_POSITION_CONFIRMED')
        self.assertEqual(StrategyIntentService(self.root).state('sh.600000')['current_action'],'EXIT')

    def test_reduce_fill_returns_intent_to_hold_when_position_remains(self):
        reduce_decision=self.decision('REDUCE');service=self.service('2026-09-16T16:05:00')
        plan=service.create(self.account_name,[reduce_decision['decision_id']],{'sh.600000':0.25},confirmed=True)
        result=service.execute(plan['plan_id'],bar('2026-09-17',10.5),rules('2026-09-17'),self.cfg,confirmed=True,as_of=dt('2026-09-17T15:05:00'))
        self.assertTrue(any(fill['side']=='sell' for fill in result['execution']['new_fills']))
        outcome=PaperRebalanceOutcomeBridge(self.root,now_fn=lambda:dt('2026-09-17T15:10:00')).apply(plan['plan_id'],confirmed=True)
        self.assertEqual(outcome['results'][0]['status'],'HOLD_RECORDED')
        self.assertEqual(StrategyIntentService(self.root).state('sh.600000')['current_action'],'HOLD')


    def test_crash_after_dynamic_account_commit_recovers_same_rebalance(self):
        add=self.decision('ADD');service=self.service('2026-09-16T16:05:00')
        plan=service.create(self.account_name,[add['decision_id']],{'sh.600000':0.7},confirmed=True)
        import quantlab.trading.paper_rebalance as module
        original=module.write_checked;calls={'n':0}
        def flaky(path,value):
            calls['n']+=1
            if calls['n']==2:raise OSError('simulated receipt crash')
            return original(path,value)
        with patch('quantlab.trading.paper_rebalance.write_checked',side_effect=flaky):
            with self.assertRaises(OSError):
                service.execute(plan['plan_id'],bar('2026-09-17',10.5),rules('2026-09-17'),self.cfg,confirmed=True,as_of=dt('2026-09-17T15:05:00'))
        self.assertEqual(self.account.read()['target_events'][-1]['weights'],{'sh.600000':0.7})
        reserved=service.get(plan['plan_id']);self.assertEqual(reserved['execution']['status'],'RESERVED')
        recovered=service.execute(plan['plan_id'],bar('2026-09-17',10.5),rules('2026-09-17'),self.cfg,confirmed=True,as_of=dt('2026-09-17T15:05:00'))
        self.assertEqual(recovered['status'],'EXECUTED_WITH_FILL');self.assertEqual(recovered['execution']['account_revision'],2)
        same=service.execute(plan['plan_id'],bar('2026-09-17',10.5),rules('2026-09-17'),self.cfg,confirmed=True,as_of=dt('2026-09-17T15:05:00'))
        self.assertEqual(same['execution']['account_revision'],2)



if __name__=='__main__':unittest.main()
