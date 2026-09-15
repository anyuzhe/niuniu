import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from quantlab.trading.market_snapshot import MarketSnapshotError,MarketSnapshotStore
from quantlab.trading.playbook_forward import freeze_forward_snapshot
from quantlab.trading.playbook_scanner import DailyPlaybookScanner
from quantlab.trading.playbook_store import PlaybookStore
from quantlab.agent.playbook_scan_cli import main as scanner_cli


class MarketSnapshotScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.clock=datetime.fromisoformat('2026-09-14T09:26:00+08:00')
        self.market=MarketSnapshotStore(self.root,now_fn=lambda:self.clock)
        self.playbooks=PlaybookStore(self.root,now_fn=lambda:self.clock)
        self.source=self.playbooks.create_source(str(uuid4()),{
            'expert_key':'qimofenshu','title':'前瞻基准来源','source_type':'PUBLIC_POST','locator':'https://example.invalid/source',
            'published_at':'2026-09-13T20:00:00+08:00','available_at':'2026-09-13T20:00:00+08:00',
            'content_hash':'a'*64,'archive_ref':'local:test','completeness':'VERIFIED','notes':''})
        self.definition=self.playbooks.create_definition(str(uuid4()),{
            'playbook_key':'qimofenshu','name':'Meta v3 test','version':'test-v3','state':'DRAFT','source_ids':[self.source['source_id']],
            'market_context':{},'eligibility':{'route':'2_to_3'},'selection':{'rule':'active'},'veto':{},'entry':{},'confirm':{},
            'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':''})
        self.case=self.playbooks.create_case(str(uuid4()),{
            'definition_id':self.definition['definition_id'],'trading_day':'2026-09-14','frame':'PREP',
            'as_of':'2026-09-13T23:58:00+08:00','source_ids':[self.source['source_id']],
            'summary':'前一日晚冻结候选','notes':''})
        candidates=[]
        for symbol in ('sz.000823','sz.002201','sz.002912','sh.600876'):
            candidates.append({'symbol':symbol,'eligibility_reasons':['前一日恰好2连板'],'features':{},'evidence_ids':['prep']})
        self.base=self.playbooks.create_candidate_set(str(uuid4()),{
            'case_id':self.case['case_id'],'definition_id':self.definition['definition_id'],'trading_day':'2026-09-14','frame':'PREP',
            'as_of':'2026-09-13T23:58:00+08:00','completeness':'FULL','pit_status':'STRICT_PIT',
            'universe_source':'frozen prep universe','generation_method':'test','candidates':candidates,'evidence_ids':['prep']})

    def tearDown(self):self.temp.cleanup()

    def auction_payload(self):
        rows=[('sz.000823','超声电子',20.57,20.80,'STANDARD_ACCESS'),('sz.002201','九鼎新材',11.09,10.51,'STANDARD_ACCESS'),
            ('sz.002912','中新赛克',23.51,25.86,'QUEUE_DEPENDENT'),('sh.600876','凯盛新能',8.70,9.24,'STANDARD_ACCESS')]
        return {'trading_day':'2026-09-14','frame':'AUCTION','as_of':'2026-09-14T09:25:00+08:00',
            'provider':'test-live','provider_ref':'archive:auction','source_hash':'b'*64,'completeness':'FULL',
            'instruments':[{'symbol':s,'name':n,'previous_close':p,'auction_price':a,'tradable':True,
                'execution_profile':e,'metrics':{}} for s,n,p,a,e in rows],'market_metrics':{},'notes':''}

    def r1_payload(self,missing=''):
        rows=[
            ('sz.000823','超声电子',20.57,20.85,21.83,20.79,21.83,532490,1127941071,'STANDARD_ACCESS'),
            ('sz.002201','九鼎新材',11.09,10.64,11.07,10.62,10.73,166861,180448418,'STANDARD_ACCESS'),
            ('sz.002912','中新赛克',23.51,25.86,25.86,25.86,25.86,5796,14987550,'QUEUE_DEPENDENT'),
            ('sh.600876','凯盛新能',8.70,9.22,9.56,8.70,8.92,126453,115043170,'STANDARD_ACCESS'),
        ]
        instruments=[]
        for s,n,p,o,h,l,c,v,a,e in rows:
            if s==missing:continue
            instruments.append({'symbol':s,'name':n,'previous_close':p,'open':o,'high':h,'low':l,'last':c,
                'volume':v,'amount':a,'tradable':True,'execution_profile':e,'metrics':{}})
        return {'trading_day':'2026-09-14','frame':'R1','as_of':'2026-09-14T09:35:00+08:00',
            'provider':'test-live','provider_ref':'archive:r1','source_hash':'c'*64,
            'completeness':'FULL' if not missing else 'PARTIAL','instruments':instruments,'market_metrics':{},'notes':''}

    def create_auction(self):
        return self.market.create(str(uuid4()),self.auction_payload())

    def create_r1(self,missing=''):
        self.clock=datetime.fromisoformat('2026-09-14T09:36:00+08:00')
        return MarketSnapshotStore(self.root,now_fn=lambda:self.clock).create(str(uuid4()),self.r1_payload(missing))

    def create_later(self,frame,as_of,last_by_symbol):
        captured=datetime.fromisoformat(as_of)+__import__('datetime').timedelta(seconds=30);self.clock=captured
        instruments=[]
        for symbol,base in [('sz.000823',20.57),('sz.002201',11.09),('sz.002912',23.51),('sh.600876',8.70)]:
            last=last_by_symbol[symbol]
            instruments.append({'symbol':symbol,'name':symbol,'previous_close':base,'open':last*0.99,'high':last*1.01,
                'low':last*0.98,'last':last,'volume':200000,'amount':3000000,'tradable':True,
                'execution_profile':'STANDARD_ACCESS' if symbol!='sz.002912' else 'QUEUE_DEPENDENT','metrics':{}})
        payload={'trading_day':'2026-09-14','frame':frame,'as_of':as_of,'provider':'test-live',
            'provider_ref':'archive:'+frame.lower(),'source_hash':('d' if frame=='R2' else 'e')*64,'completeness':'FULL',
            'instruments':instruments,'market_metrics':{},'notes':''}
        return MarketSnapshotStore(self.root,now_fn=lambda:self.clock).create(str(uuid4()),payload)

    def test_live_snapshot_is_immutable_auditable_and_future_is_blocked(self):
        saved=self.create_auction()
        self.assertEqual(saved['capture_status'],'LIVE_NEAR_REALTIME');self.assertTrue(saved['strict_pit_eligible'])
        again=MarketSnapshotStore(self.root,now_fn=lambda:self.clock).create(saved['request_id'],self.auction_payload())
        self.assertEqual(again['snapshot_id'],saved['snapshot_id'])
        bad=self.auction_payload();bad['as_of']='2026-09-14T09:27:00+08:00'
        with self.assertRaises(MarketSnapshotError) as error:
            self.market.create(str(uuid4()),bad)
        self.assertEqual(error.exception.code,'FUTURE_SNAPSHOT')

    def test_auction_scanner_ranks_but_does_not_select(self):
        auction=self.create_auction();result=DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],auction['snapshot_id'])
        self.assertEqual(result['selected_symbols'],[])
        self.assertEqual(result['ranked_symbols'][0],'sz.002912')
        self.assertEqual(result['forward_payload']['frame'],'AUCTION')
        self.assertEqual(result['forward_payload']['market_snapshot_ids'],[auction['snapshot_id']])

    def test_r1_scanner_prefers_active_standard_access_over_locked_limit(self):
        auction=self.create_auction();r1=self.create_r1()
        result=DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],r1['snapshot_id'],auction['snapshot_id'])
        self.assertEqual(result['selected_symbols'],['sz.000823'])
        self.assertEqual(result['ranked_symbols'],['sz.000823','sz.002912','sh.600876','sz.002201'])
        candidates={c['symbol']:c for c in result['forward_payload']['candidate_set']['candidates']}
        self.assertEqual(candidates['sz.002912']['features']['execution_profile'],'QUEUE_DEPENDENT')
        self.assertTrue(candidates['sz.002912']['features']['one_price_first_window'])

    def test_missing_live_candidate_fails_closed_to_no_trade(self):
        auction=self.create_auction();r1=self.create_r1('sh.600876')
        result=DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],r1['snapshot_id'],auction['snapshot_id'])
        self.assertFalse(result['complete']);self.assertIn('sh.600876',result['missing_symbols'])
        self.assertEqual(result['selected_symbols'],[])
        self.assertEqual(result['forward_payload']['candidate_set']['completeness'],'PARTIAL')
        self.assertEqual(result['forward_payload']['candidate_set']['pit_status'],'UNKNOWN')

    def test_scanner_payload_can_freeze_live_prediction_and_bundle_snapshots(self):
        auction=self.create_auction();r1=self.create_r1()
        result=DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],r1['snapshot_id'],auction['snapshot_id'])
        self.clock=datetime.fromisoformat('2026-09-14T09:37:00+08:00')
        frozen=freeze_forward_snapshot(self.root,result['forward_payload'],now_fn=lambda:self.clock)
        self.assertEqual(frozen['prediction']['selected_symbols'],['sz.000823'])
        bundle=PlaybookStore(self.root,now_fn=lambda:self.clock).case_bundle(frozen['case']['case_id'])
        self.assertEqual([s['frame'] for s in bundle['market_snapshots']],['AUCTION','R1'])

    def test_r2_r3_only_continue_frozen_previous_prediction_and_do_not_add_new_symbol(self):
        auction=self.create_auction();r1=self.create_r1()
        r1_result=DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],r1['snapshot_id'],auction['snapshot_id'])
        self.assertEqual(r1_result['selected_symbols'],['sz.000823'])
        self.clock=datetime.fromisoformat('2026-09-14T09:37:00+08:00')
        r1_frozen=freeze_forward_snapshot(self.root,r1_result['forward_payload'],now_fn=lambda:self.clock)
        r2=self.create_later('R2','2026-09-14T11:30:00+08:00',{'sz.000823':21.5,'sz.002201':11.2,'sz.002912':25.5,'sh.600876':9.4})
        r2_result=DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],r2['snapshot_id'],
            previous_snapshot_id=r1['snapshot_id'],reference_prediction_id=r1_frozen['prediction']['selection_id'])
        self.assertEqual(r2_result['selected_symbols'],['sz.000823'])
        self.assertIn('本阶段禁止新增标的',r2_result['forward_payload']['prediction']['reasons']['sh.600876'][0])
        self.assertIn('playbook_selection:'+r1_frozen['prediction']['selection_id'],r2_result['forward_payload']['prediction']['evidence_ids'])
        self.clock=datetime.fromisoformat('2026-09-14T11:31:00+08:00')
        r2_frozen=freeze_forward_snapshot(self.root,r2_result['forward_payload'],now_fn=lambda:self.clock)
        r3=self.create_later('R3','2026-09-14T15:00:00+08:00',{'sz.000823':20.0,'sz.002201':11.5,'sz.002912':25.0,'sh.600876':9.6})
        r3_result=DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],r3['snapshot_id'],
            previous_snapshot_id=r2['snapshot_id'],reference_prediction_id=r2_frozen['prediction']['selection_id'])
        self.assertEqual(r3_result['selected_symbols'],[])
        self.assertEqual(r3_result['forward_payload']['frame'],'R3')

    def test_r2_requires_explicit_previous_snapshot_and_frozen_prediction(self):
        r2=self.create_later('R2','2026-09-14T11:30:00+08:00',{'sz.000823':21.5,'sz.002201':11.2,'sz.002912':25.5,'sh.600876':9.4})
        with self.assertRaises(Exception) as missing_previous:
            DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],r2['snapshot_id'])
        self.assertEqual(getattr(missing_previous.exception,'code',None),'PREVIOUS_SNAPSHOT_REQUIRED')
        auction=self.create_auction();r1=self.create_r1()
        with self.assertRaises(Exception) as missing_prediction:
            DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],r2['snapshot_id'],previous_snapshot_id=r1['snapshot_id'])
        self.assertEqual(getattr(missing_prediction.exception,'code',None),'REFERENCE_PREDICTION_REQUIRED')

    def test_host_cli_supports_r2_with_auditable_previous_prediction(self):
        auction=self.create_auction();r1=self.create_r1()
        r1_result=DailyPlaybookScanner(self.root).scan(self.base['candidate_set_id'],r1['snapshot_id'],auction['snapshot_id'])
        self.clock=datetime.fromisoformat('2026-09-14T09:37:00+08:00')
        frozen=freeze_forward_snapshot(self.root,r1_result['forward_payload'],now_fn=lambda:self.clock)
        r2=self.create_later('R2','2026-09-14T11:30:00+08:00',{'sz.000823':21.5,'sz.002201':11.2,'sz.002912':25.5,'sh.600876':9.4})
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=scanner_cli(['--output',str(self.root),'--candidate-set-id',self.base['candidate_set_id'],
                '--market-snapshot-id',r2['snapshot_id'],'--previous-snapshot-id',r1['snapshot_id'],
                '--reference-prediction-id',frozen['prediction']['selection_id']])
        value=json.loads(out.getvalue());self.assertEqual(code,0);self.assertTrue(value['ok'])
        self.assertEqual(value['data']['frame'],'R2');self.assertEqual(value['data']['selected_symbols'],['sz.000823'])

    def test_snapshot_tamper_is_detected(self):
        saved=self.create_auction();db=sqlite3.connect(self.market.path)
        db.execute("UPDATE market_snapshots SET payload='{}' WHERE id=?",(saved['snapshot_id'],));db.commit();db.close()
        with self.assertRaises(MarketSnapshotError) as error:MarketSnapshotStore(self.root).get(saved['snapshot_id'])
        self.assertEqual(error.exception.code,'CORRUPT_SNAPSHOT')


if __name__=='__main__':unittest.main()
