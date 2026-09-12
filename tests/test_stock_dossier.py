import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from quantlab.agent.watch_store import WatchStore
from quantlab.trading.decision_store import DecisionStore
from quantlab.trading.stock_dossier import StockDossier


class StockDossierTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=DecisionStore(self.root)
        self.symbol='sh.600000'

    def tearDown(self):
        self.temp.cleanup()

    def decision(self, **updates):
        value={'symbol':self.symbol,'trading_day':'2026-09-11','frame':'R1','action':'WATCH',
            'role_id':'human','theme':'银行','theme_role':'观察','ai_thesis':'等待确认'}
        value.update(updates);return value

    def add_run(self, symbols, question='相关实验'):
        run_id=str(uuid4());folder=self.root/run_id;folder.mkdir()
        record={'run_id':run_id,'status':'completed','created_at':'2026-09-12T00:00:00+00:00','kind':'factor',
            'manifest':{'config':{'research_question':question,'factor_id':'BASE.MOMENTUM',
                'data':{'symbols':symbols,'start':'2026-01-01','end':'2026-06-30','timeframe':'1d'}}}}
        (folder/'experiment.json').write_text(json.dumps(record));return run_id

    def add_watch(self, symbols):
        watch_id=str(uuid4());base_run_id=str(uuid4())
        definition={'watch_id':watch_id,'name':'银行观察','base_run_id':base_run_id,'windows':[20],
            'min_dates':5,'rule':{'adjustment':'qfq','config':{'factor_id':'BASE.MOMENTUM',
                'factor_version':'1.0.0','parameters':{'lookback':20},'data':{'symbols':symbols}}}}
        WatchStore(self.root).initialize(watch_id,definition);return watch_id

    def test_dossier_aggregates_decisions_experiments_and_watches_without_jobs(self):
        first=self.store.create(str(uuid4()),self.decision())
        self.store.create(str(uuid4()),self.decision(action='READY',revision_of=first['decision_id'],ai_thesis='条件改善'))
        run_id=self.add_run([self.symbol,'sz.000001'])
        self.add_run(['sz.000001'],'无关实验')
        watch_id=self.add_watch([self.symbol])
        dossier=StockDossier(self.root).get(self.symbol)
        self.assertEqual(dossier['symbol'],self.symbol)
        self.assertEqual(dossier['current_decision']['action'],'READY')
        self.assertEqual(dossier['counts']['decision_current'],1)
        self.assertEqual(dossier['counts']['decision_history'],2)
        self.assertEqual([r['run_id'] for r in dossier['experiments']],[run_id])
        self.assertEqual([w['watch_id'] for w in dossier['watches']],[watch_id])
        self.assertEqual(dossier['themes'],['银行'])
        self.assertFalse((self.root/'_jobs').exists())

    def test_current_decision_uses_business_frame_not_late_write_time(self):
        r3_store=DecisionStore(self.root,now_fn=lambda:datetime.fromisoformat('2026-09-11T15:10:00+08:00'))
        r3=r3_store.create(str(uuid4()),self.decision(frame='R3',ai_thesis='R3判断'))
        late_store=DecisionStore(self.root,now_fn=lambda:datetime.fromisoformat('2026-09-11T20:00:00+08:00'))
        late_store.create(str(uuid4()),self.decision(frame='R1',action='READY',ai_thesis='夜间补录R1'))
        dossier=StockDossier(self.root).get(self.symbol)
        self.assertEqual(dossier['current_decision']['decision_id'],r3['decision_id'])
        self.assertEqual(dossier['current_decision']['frame'],'R3')

    def test_dossier_with_no_decision_can_still_show_research_evidence(self):
        run_id=self.add_run([self.symbol]);self.add_watch([self.symbol])
        dossier=StockDossier(self.root).get(self.symbol)
        self.assertIsNone(dossier['current_decision'])
        self.assertEqual(dossier['experiments'][0]['run_id'],run_id)
        self.assertEqual(dossier['counts']['watches'],1)

    def test_invalid_symbol_is_rejected(self):
        with self.assertRaises(ValueError):StockDossier(self.root).get('600000')


if __name__=='__main__':unittest.main()
