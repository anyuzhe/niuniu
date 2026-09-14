import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from quantlab.trading.decision_store import DecisionStore
from quantlab.trading.market_snapshot import MarketSnapshotStore
from quantlab.trading.playbook_decision_bridge import PlaybookDecisionBridge,PlaybookDecisionBridgeError
from quantlab.trading.playbook_store import PlaybookStore
from quantlab.trading.strategy_intent import StrategyIntentService


class PlaybookDecisionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.now=datetime.fromisoformat('2026-09-14T09:36:00+08:00')
        self.store=PlaybookStore(self.root,now_fn=lambda:self.now)
        source=self.store.create_source(str(uuid4()),{'expert_key':'pilot','title':'pilot','source_type':'PUBLIC_POST',
            'locator':'local:pilot','available_at':'2026-09-14T09:00:00+08:00','content_hash':'a'*64,
            'archive_ref':'','completeness':'VERIFIED','notes':''})
        self.definition=self.store.create_definition(str(uuid4()),{'playbook_key':'bridge-pilot','name':'Bridge Pilot',
            'version':'draft-1','state':'DRAFT','source_ids':[source['source_id']],'market_context':{},
            'eligibility':{'x':1},'selection':{'x':1},'veto':{},'entry':{},'confirm':{},'invalidation':{},
            'hold':{},'add':{},'reduce':{},'exit':{},'notes':''})

    def prediction(self,selected=None,kind='SYSTEM_PREDICTION',completeness='FULL',pit='STRICT_PIT'):
        selected=['sh.600001'] if selected is None else selected
        snapshot=MarketSnapshotStore(self.root,now_fn=lambda:self.now).create(str(uuid4()),{
            'trading_day':'2026-09-14','frame':'R1','as_of':'2026-09-14T09:35:30+08:00','provider':'fixture',
            'provider_ref':'fixture:r1','source_hash':'b'*64,'completeness':'FULL','instruments':[
                {'symbol':'sh.600001','previous_close':10,'open':10.1,'high':10.5,'low':10,'last':10.5,
                    'volume':1000,'amount':10000,'tradable':True,'execution_profile':'STANDARD_ACCESS','metrics':{}},
                {'symbol':'sh.600002','previous_close':10,'open':10,'high':10,'low':10,'last':10,
                    'volume':1000,'amount':10000,'tradable':True,'execution_profile':'QUEUE_DEPENDENT','metrics':{}},
            ],'market_metrics':{},'notes':''})
        case=self.store.create_case(str(uuid4()),{'definition_id':self.definition['definition_id'],'source_ids':self.definition['source_ids'],
            'trading_day':'2026-09-14','frame':'R1','as_of':'2026-09-14T09:35:30+08:00',
            'market_snapshot_ids':[snapshot['snapshot_id']],'summary':'fixture','notes':''})
        candidates=self.store.create_candidate_set(str(uuid4()),{'case_id':case['case_id'],'definition_id':self.definition['definition_id'],
            'trading_day':'2026-09-14','frame':'R1','as_of':'2026-09-14T09:35:30+08:00','completeness':completeness,
            'pit_status':pit,'universe_source':'fixture','generation_method':'fixture','candidates':[
                {'symbol':'sh.600001','eligibility_reasons':['fixture'],'features':{'execution_profile':'STANDARD_ACCESS'},'evidence_ids':[]},
                {'symbol':'sh.600002','eligibility_reasons':['fixture'],'features':{'execution_profile':'QUEUE_DEPENDENT'},'evidence_ids':[]},
            ],'evidence_ids':['fixture']})
        return self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],'kind':kind,
            'selected_symbols':selected,'ranked_symbols':['sh.600001','sh.600002'] if selected else [],
            'reasons':{'sh.600001':['主动增强']} if selected else {},'evidence_ids':['fixture'],
            'as_of':'2026-09-14T09:35:30+08:00','notes':'fixture'})

    def bridge(self):return PlaybookDecisionBridge(self.root,now_fn=lambda:self.now)

    def test_selected_system_prediction_creates_watch_not_open(self):
        selection=self.prediction();receipt=self.bridge().apply(selection['selection_id'])
        self.assertFalse(receipt['no_trade']);self.assertEqual(receipt['decisions'][0]['action'],'WATCH')
        decision=DecisionStore(self.root).get(receipt['decisions'][0]['decision_id'])
        self.assertEqual(decision['role_id'],'system');self.assertEqual(decision['source'],'playbook_system_prediction')
        self.assertIn('playbook_selection:'+selection['selection_id'],decision['research_evidence_ids'])
        self.assertIn('PLAYBOOK_SYSTEM_PREDICTION_NOT_FILL',decision['risk_flags'])
        self.assertEqual(decision['position_scope'],'strategy_intent')
        self.assertFalse((self.root/'paper').exists())

    def test_no_trade_creates_receipt_but_no_stock_decision(self):
        selection=self.prediction(selected=[]);receipt=self.bridge().apply(selection['selection_id'])
        self.assertTrue(receipt['no_trade']);self.assertEqual(receipt['decisions'],[])
        self.assertFalse((self.root/'_trading/decision_ledger.sqlite3').exists())

    def test_historical_reconstruction_cannot_enter_bridge(self):
        selection=self.prediction(kind='HUMAN_RECONSTRUCTION')
        with self.assertRaises(PlaybookDecisionBridgeError) as error:self.bridge().apply(selection['selection_id'])
        self.assertEqual(error.exception.code,'NOT_SYSTEM_PREDICTION')

    def test_existing_plan_or_position_is_not_overwritten(self):
        intent=StrategyIntentService(self.root,now_fn=lambda:datetime.fromisoformat('2026-09-14T09:10:00+08:00'))
        existing=intent.transition(str(uuid4()),{'symbol':'sh.600001','trading_day':'2026-09-14','frame':'PREP',
            'action':'PLAN_OPEN','role_id':'human','confirm_trigger':'人工确认','transition_reason':'人工已有计划','source':'manual'})
        selection=self.prediction();receipt=self.bridge().apply(selection['selection_id'])
        self.assertEqual(receipt['decisions'],[]);self.assertEqual(receipt['skipped'][0]['reason'],'EXISTING_PLAN_OR_POSITION')
        self.assertEqual(StrategyIntentService(self.root).current('sh.600001')['decision_id'],existing['decision_id'])

    def test_same_frame_manual_decision_is_not_auto_revised(self):
        intent=StrategyIntentService(self.root,now_fn=lambda:self.now)
        manual=intent.transition(str(uuid4()),{'symbol':'sh.600001','trading_day':'2026-09-14','frame':'R1','action':'WATCH',
            'role_id':'human','ai_thesis':'人工观察','source':'manual'})
        selection=self.prediction();receipt=self.bridge().apply(selection['selection_id'])
        self.assertEqual(receipt['decisions'],[]);self.assertEqual(receipt['skipped'][0]['reason'],'FRAME_OCCUPIED')
        self.assertEqual(receipt['skipped'][0]['decision_id'],manual['decision_id'])

    def test_existing_discovered_advances_to_watch_and_ready_is_preserved(self):
        first=StrategyIntentService(self.root,now_fn=lambda:datetime.fromisoformat('2026-09-14T08:00:00+08:00'))
        first.transition(str(uuid4()),{'symbol':'sh.600001','trading_day':'2026-09-14','frame':'PREP','action':'DISCOVERED',
            'role_id':'human','ai_thesis':'发现','source':'manual'})
        selection=self.prediction();receipt=self.bridge().apply(selection['selection_id'])
        self.assertEqual(receipt['decisions'][0]['action'],'WATCH')

    def test_lost_receipt_reuses_decision_instead_of_duplicate(self):
        selection=self.prediction();bridge=self.bridge()
        original='quantlab.trading.playbook_decision_bridge.write_checked'
        with patch(original,side_effect=OSError('lost receipt')):
            with self.assertRaises(OSError):bridge.apply(selection['selection_id'])
        decisions=DecisionStore(self.root).list(symbol='sh.600001',include_superseded=True,limit=20)['records']
        self.assertEqual(len(decisions),1)
        receipt=self.bridge().apply(selection['selection_id'])
        self.assertEqual(len(DecisionStore(self.root).list(symbol='sh.600001',include_superseded=True,limit=20)['records']),1)
        self.assertFalse(receipt['decisions'][0]['created'])

    def test_partial_or_queue_access_is_preserved_as_risk_not_upgraded(self):
        selection=self.prediction(selected=['sh.600002'],completeness='PARTIAL',pit='RETROSPECTIVE_REFERENCE')
        receipt=self.bridge().apply(selection['selection_id']);decision=DecisionStore(self.root).get(receipt['decisions'][0]['decision_id'])
        self.assertTrue({'CANDIDATE_SET_NOT_FULL','PIT_NOT_STRICT','QUEUE_DEPENDENT'}<=set(decision['risk_flags']))
        self.assertEqual(decision['action'],'WATCH')


if __name__=='__main__':unittest.main()
