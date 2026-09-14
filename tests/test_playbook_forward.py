import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from quantlab.trading.playbook_forward import forward_frame_status,freeze_forward_snapshot
from quantlab.trading.playbook_store import PlaybookError,PlaybookStore


class PlaybookForwardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.clock=datetime.fromisoformat('2026-09-14T09:26:00+08:00')
        store=PlaybookStore(self.root,now_fn=lambda:self.clock)
        source=store.create_source(str(uuid4()),{
            'expert_key':'qimofenshu','title':'live snapshot source','source_type':'PUBLIC_POST',
            'locator':'https://example.invalid/live','published_at':'2026-09-14T09:25:00+08:00',
            'available_at':'2026-09-14T09:25:00+08:00','content_hash':'a'*64,
            'archive_ref':'local:live','completeness':'VERIFIED','notes':'test'})
        definition=store.create_definition(str(uuid4()),{
            'playbook_key':'qimofenshu','name':'forward test','version':'forward-test-v1','state':'DRAFT',
            'source_ids':[source['source_id']],'market_context':{},'eligibility':{'rule':'test'},
            'selection':{'rule':'test'},'veto':{},'entry':{},'confirm':{},'invalidation':{},
            'hold':{},'add':{},'reduce':{},'exit':{},'notes':''})
        self.source_id=source['source_id'];self.definition_id=definition['definition_id']
    def tearDown(self):self.temp.cleanup()

    def payload(self,frame='AUCTION',as_of='2026-09-14T09:25:00+08:00'):
        return {'definition_id':self.definition_id,'trading_day':'2026-09-14','frame':frame,
            'as_of':as_of,'source_ids':[self.source_id],'summary':'live forward snapshot','notes':'',
            'candidate_set':{'completeness':'FULL','pit_status':'UNKNOWN','universe_source':'live-source',
                'generation_method':'frozen forward cohort','candidates':[
                    {'symbol':'sh.600000','eligibility_reasons':['eligible'],'features':{'rank':1},'evidence_ids':['live']},
                    {'symbol':'sz.000001','eligibility_reasons':['eligible'],'features':{'rank':2},'evidence_ids':['live']}],
                'evidence_ids':['live']},
            'prediction':{'selected_symbols':['sh.600000'],'ranked_symbols':['sh.600000','sz.000001'],
                'reasons':{'sh.600000':['stronger']},'evidence_ids':['live'],'notes':'forward'}}

    def test_auction_waits_for_final_0925_data_even_inside_decision_window(self):
        self.clock=datetime.fromisoformat('2026-09-14T09:20:00+08:00')
        status=forward_frame_status(self.root,'2026-09-14','AUCTION',lambda:self.clock)
        self.assertEqual(status['submission_status'],'ON_TIME')
        self.assertEqual(status['forward_status'],'WAIT_DATA');self.assertFalse(status['can_freeze'])
        with self.assertRaises(PlaybookError) as error:
            freeze_forward_snapshot(self.root,self.payload(),lambda:self.clock)
        self.assertEqual(error.exception.code,'FORWARD_FRAME_NOT_OPEN')

    def test_r1_waits_for_first_complete_five_minute_bar(self):
        self.clock=datetime.fromisoformat('2026-09-14T09:34:00+08:00')
        status=forward_frame_status(self.root,'2026-09-14','R1',lambda:self.clock)
        self.assertEqual(status['forward_status'],'WAIT_DATA')
        with self.assertRaises(PlaybookError) as error:
            freeze_forward_snapshot(self.root,self.payload('R1','2026-09-14T09:34:00+08:00'),lambda:self.clock)
        self.assertEqual(error.exception.code,'FORWARD_FRAME_NOT_OPEN')

    def test_same_payload_retries_resume_without_duplicate_records(self):
        first=freeze_forward_snapshot(self.root,self.payload(),lambda:self.clock)
        second=freeze_forward_snapshot(self.root,self.payload(),lambda:self.clock)
        self.assertEqual(first['case']['case_id'],second['case']['case_id'])
        self.assertEqual(first['candidate_set']['candidate_set_id'],second['candidate_set']['candidate_set_id'])
        self.assertEqual(first['prediction']['selection_id'],second['prediction']['selection_id'])
        self.assertEqual(second['resumed'],{'case':True,'candidate_set':True,'prediction':True})
        overview=PlaybookStore(self.root).overview()
        self.assertEqual(overview['cases'],1);self.assertEqual(overview['candidate_sets'],1)
        self.assertEqual(overview['selections'],1)

    def test_frozen_frame_rejects_changed_prediction(self):
        freeze_forward_snapshot(self.root,self.payload(),lambda:self.clock)
        changed=self.payload();changed['prediction']['selected_symbols']=['sz.000001']
        changed['prediction']['ranked_symbols']=['sz.000001','sh.600000']
        changed['prediction']['reasons']={'sz.000001':['changed after freeze']}
        self.clock=datetime.fromisoformat('2026-09-14T09:27:00+08:00')
        with self.assertRaises(PlaybookError) as error:
            freeze_forward_snapshot(self.root,changed,lambda:self.clock)
        self.assertEqual(error.exception.code,'FORWARD_FRAME_ALREADY_FROZEN')

    def test_live_snapshot_cannot_be_frozen_more_than_ten_minutes_late(self):
        self.clock=datetime.fromisoformat('2026-09-14T09:46:00+08:00')
        with self.assertRaises(PlaybookError) as error:
            freeze_forward_snapshot(self.root,self.payload('R1','2026-09-14T09:35:00+08:00'),lambda:self.clock)
        self.assertEqual(error.exception.code,'LOOKAHEAD_BLOCKED')


if __name__=='__main__':unittest.main()
