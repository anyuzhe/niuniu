import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from quantlab.agent.watch_store import WatchStore
from quantlab.trading.cockpit import TradingCockpitService
from quantlab.trading.strategy_intent import StrategyIntentService
from quantlab.trading.theme_store import ThemeStore


class TradingCockpitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def intent(self,iso,symbol,frame,action,**extra):
        moment=datetime.fromisoformat(iso);service=StrategyIntentService(self.root,now_fn=lambda:moment)
        payload={'symbol':symbol,'trading_day':'2026-09-11','frame':frame,'action':action,'role_id':'human','theme':'银行','ai_thesis':'判断','source':'cockpit-test',**extra}
        return service.transition(str(uuid4()),payload)

    def add_watch(self):
        wid=str(uuid4());definition={'watch_id':wid,'name':'银行观察','base_run_id':str(uuid4()),'windows':[20],'min_dates':5,'rule':{'adjustment':'qfq','config':{'factor_id':'BASE.MOMENTUM','factor_version':'1.0.0','parameters':{'lookback':20},'data':{'symbols':['sh.600000']}}}}
        WatchStore(self.root).initialize(wid,definition);return wid

    def test_cockpit_aggregates_durable_evidence_without_side_effects(self):
        self.intent('2026-09-11T10:00:00+08:00','sh.600000','R1','WATCH')
        self.intent('2026-09-11T09:00:00+08:00','sz.000001','PREP','WATCH')
        self.intent('2026-09-11T10:00:00+08:00','sz.000001','R1','READY',transition_reason='确认')
        self.intent('2026-09-11T12:00:00+08:00','sz.000001','R2','PLAN_OPEN',confirm_trigger='突破',transition_reason='准备')
        ThemeStore(self.root).create(str(uuid4()),{'theme':'银行','trading_day':'2026-09-11','frame':'R2','machine_state':'START','ai_state':'PREHEAT','facts':{'limit_up_count':3,'amount_billion':88.8,'leader_symbol':'sh.600000'},'facts_source':'fixture:theme','facts_as_of':'2026-09-11T12:00:00+08:00','risk_review':'注意分歧','source':'test'})
        ThemeStore(self.root).create(str(uuid4()),{'theme':'软件AI','trading_day':'2026-09-10','frame':'R3','machine_state':'DECLINE','ai_state':'UNKNOWN','source':'test'})
        self.add_watch();jobs=self.root/'_jobs';jobs.mkdir();(jobs/'failed.json').write_text(json.dumps({'job_id':'fixture-failed','status':'failed','error':'fixture error','spec':{'question':'失败任务'}}))
        before=len(list(jobs.glob('*.json')));value=TradingCockpitService(self.root).build('2026-09-11');after=len(list(jobs.glob('*.json')))
        self.assertEqual(value['trading_day'],'2026-09-11');self.assertEqual(value['day_source'],'explicit')
        self.assertEqual(value['latest_saved_frame'],'R2');self.assertEqual([d['symbol'] for d in value['candidates']],['sh.600000'])
        self.assertEqual([d['symbol'] for d in value['plans']],['sz.000001'])
        self.assertEqual([t['theme'] for t in value['themes']],['银行']);self.assertEqual(value['theme_fact_snapshots'],1)
        self.assertEqual(value['watches']['rows'][0]['name'],'银行观察');self.assertGreaterEqual(value['agenda']['total'],1)
        self.assertEqual(before,after);self.assertEqual(value['new_research_jobs'],0);self.assertFalse(value['automatic_execution'])
        self.assertIn('不跨主题加总',value['market_facts_policy'])

    def test_default_day_uses_latest_workspace_evidence_not_fake_live_day(self):
        self.intent('2026-09-11T10:00:00+08:00','sh.600000','R1','WATCH')
        value=TradingCockpitService(self.root).build()
        self.assertEqual(value['trading_day'],'2026-09-11');self.assertEqual(value['day_source'],'latest_workspace_evidence')


if __name__=='__main__':unittest.main()
