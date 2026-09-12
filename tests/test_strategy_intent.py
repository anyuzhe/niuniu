import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from quantlab.trading.decision_store import DecisionError,DecisionStore
from quantlab.trading.strategy_intent import StrategyIntentService,allowed_next


def payload(**updates):
    value={'symbol':'sh.600000','trading_day':'2026-09-11','frame':'PREP','action':'WATCH','role_id':'human','theme':'银行','ai_thesis':'开始观察','source':'intent-test'}
    value.update(updates);return value


class StrategyIntentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def service(self,iso='2026-09-11T10:00:00+08:00'):
        moment=datetime.fromisoformat(iso)
        return StrategyIntentService(self.root,now_fn=lambda:moment)

    def transition(self,service,**updates):
        return service.transition(str(uuid4()),payload(**updates))

    def test_allowed_next_contract(self):
        self.assertEqual(allowed_next(None),['DISCOVERED','WATCH'])
        self.assertIn('READY',allowed_next('WATCH'));self.assertNotIn('OPEN',allowed_next('WATCH'))
        self.assertIn('EXIT',allowed_next('HOLD'));self.assertIn('WATCH',allowed_next('EXIT'))

    def test_full_strategy_intent_lifecycle(self):
        service=self.service()
        prep=self.transition(service,frame='PREP',action='WATCH')
        ready=self.transition(service,frame='R1',action='READY',ai_thesis='确认增强')
        plan=self.transition(service,frame='R2',action='PLAN_OPEN',confirm_trigger='突破前高',ai_thesis='准备开仓')
        opened=self.transition(service,frame='R3',action='OPEN',confirm_trigger='突破已确认',hold_reason='收盘结构成立',ai_thesis='开仓条件满足')
        d1=self.transition(self.service('2026-09-14T10:00:00+08:00'),trading_day='2026-09-14',frame='D1',action='HOLD',hold_reason='D1结构未破坏',reference_decision_id=opened['decision_id'])
        d2=self.transition(self.service('2026-09-15T10:00:00+08:00'),trading_day='2026-09-15',frame='D2',action='REDUCE',exit_condition='强度下降',ai_thesis='降低暴露',reference_decision_id=opened['decision_id'])
        d3=self.transition(self.service('2026-09-16T10:00:00+08:00'),trading_day='2026-09-16',frame='D3_PLUS',action='EXIT',exit_condition='趋势破坏',ai_thesis='退出',reference_decision_id=opened['decision_id'])
        self.assertEqual([x['intent_transition_kind'] for x in (prep,ready,plan,opened,d1,d2,d3)],['INITIAL','ADVANCE','ADVANCE','ADVANCE','ADVANCE','ADVANCE','ADVANCE'])
        self.assertEqual(self.service().state('sh.600000')['current_action'],'EXIT')
        self.assertEqual(d1['position_scope'],'strategy_intent')
        self.assertFalse((self.root/'paper').exists())

    def test_illegal_transition_and_bootstrap(self):
        service=self.service();self.transition(service,action='WATCH')
        with self.assertRaises(DecisionError) as error:
            self.transition(service,frame='R1',action='OPEN',confirm_trigger='直接开仓',hold_reason='不允许跳级')
        self.assertEqual(error.exception.code,'INVALID_TRANSITION')
        other=StrategyIntentService(self.root,now_fn=lambda:datetime.fromisoformat('2026-09-11T10:00:00+08:00'))
        boot=other.transition(str(uuid4()),payload(symbol='sz.000001',action='HOLD',hold_reason='导入已有人工持仓',transition_reason='初始化已有状态'))
        self.assertEqual(boot['intent_transition_kind'],'BOOTSTRAP')

    def test_same_frame_requires_revision_and_historical_insert_blocked(self):
        service=self.service();first=self.transition(service,frame='R3',action='WATCH')
        with self.assertRaises(DecisionError) as same:
            self.transition(service,frame='R3',action='WATCH',ai_thesis='第二条同Frame')
        self.assertEqual(same.exception.code,'FRAME_ALREADY_HAS_CURRENT_DECISION')
        with self.assertRaises(DecisionError) as backfill:
            self.transition(self.service('2026-09-11T16:00:00+08:00'),frame='R1',action='WATCH',ai_thesis='事后补早盘')
        self.assertEqual(backfill.exception.code,'HISTORICAL_INSERT_BLOCKED')
        revised=service.transition(str(uuid4()),payload(frame='R3',action='WATCH',ai_thesis='补充证据',revision_of=first['decision_id']))
        self.assertEqual(revised['intent_transition_kind'],'REVISION_SAME_STATE')

    def test_revision_cannot_rewrite_state_under_later_decision(self):
        service=self.service();prep=self.transition(service,frame='PREP',action='WATCH')
        self.transition(service,frame='R1',action='READY',ai_thesis='确认')
        with self.assertRaises(DecisionError) as error:
            service.transition(str(uuid4()),payload(frame='PREP',action='READY',ai_thesis='事后改动作',revision_of=prep['decision_id']))
        self.assertEqual(error.exception.code,'HISTORICAL_STATE_REWRITE')

    def test_model_tool_boundary_has_no_intent_write(self):
        from quantlab.agent.market_data_tools import MarketDataResearchAPI
        api=MarketDataResearchAPI(self.root,None);names={tool['name'] for tool in api.schemas()}
        self.assertFalse({'create_decision','transition_strategy_intent','set_position_intent'} & names)
        self.assertFalse(api.call('transition_strategy_intent',{})['ok'])

    def test_business_time_beats_database_write_time(self):
        early=DecisionStore(self.root,now_fn=lambda:datetime.fromisoformat('2026-09-11T15:10:00+08:00'))
        r3=early.create(str(uuid4()),payload(frame='R3',action='WATCH',ai_thesis='R3'))
        late=DecisionStore(self.root,now_fn=lambda:datetime.fromisoformat('2026-09-11T20:00:00+08:00'))
        late.create(str(uuid4()),payload(frame='R1',action='READY',ai_thesis='晚上补录R1'))
        self.assertEqual(late.latest_current('sh.600000')['decision_id'],r3['decision_id'])
        self.assertEqual(late.latest_by_symbol()[0]['frame'],'R3')


if __name__=='__main__':unittest.main()
