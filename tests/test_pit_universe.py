import hashlib,json,tempfile,unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.agent.pit_universe_cli import main as universe_cli
from quantlab.data.pit_universe import (
    PITUniverseError,archive_pit_universe,audit_pit_universe,load_pit_universe_snapshot,
)
from quantlab.experiments.campaign_state import read_checked,write_checked


class PITUniverseReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.document=self.root/'sse-list.json'
        self.document.write_bytes(b'{"official":"SSE full A-share list fixture"}')

    def plan(self,session='2026-09-10'):
        return {'format':'niuniu-pit-universe-plan-v1','effective_session':session,
            'cutoff_at':session+'T09:15:00+08:00','scope':{'market':'CN_A_SHARE',
                'exchanges':['SSE'],'instrument_types':['A_SHARE'],'completeness':'FULL_OFFICIAL_LIST'},
            'sources':[{'source_id':'sse-a-share-list','exchange':'SSE',
                'url':'https://www.sse.com.cn/assortment/stock/list/share/',
                'published_at':'2026-09-09T15:30:00+08:00','available_at':'2026-09-09T15:35:00+08:00',
                'document':str(self.document),'sha256':hashlib.sha256(self.document.read_bytes()).hexdigest()}],
            'members':[{'symbol':'sh.600001','source_id':'sse-a-share-list'},
                {'symbol':'sh.600002','source_id':'sse-a-share-list'}]}

    def archive(self,plan=None,now='2026-09-09T16:00:00+08:00'):
        return archive_pit_universe(self.root,plan or self.plan(),confirm_publication_times=True,
            confirm_semantic_mapping=True,confirm_complete_official_universe=True,
            now_fn=lambda:datetime.fromisoformat(now))

    def test_append_only_receipt_is_idempotent_and_deeply_audited(self):
        first=self.archive();second=self.archive(now='2026-09-11T12:00:00+08:00')
        self.assertTrue(first['created']);self.assertFalse(second['created'])
        self.assertEqual(first['universe_snapshot'],second['universe_snapshot'])
        receipt=load_pit_universe_snapshot(self.root,first['universe_snapshot'],effective_session='2026-09-10')
        self.assertEqual(receipt['member_count'],2);self.assertTrue(receipt['strict_pit_eligible'])
        self.assertEqual([row['symbol'] for row in receipt['members']],['sh.600001','sh.600002'])
        audit=audit_pit_universe(self.root)
        self.assertEqual(audit['verified_receipts'],1);self.assertEqual(audit['invalid_receipts'],0)
        self.assertEqual(audit['effective_sessions'],1);self.assertEqual(audit['member_records'],2)

    def test_confirmation_timing_scope_and_member_binding_are_hard_gates(self):
        with self.assertRaisesRegex(PITUniverseError,'confirm'):
            archive_pit_universe(self.root,self.plan())
        with self.assertRaisesRegex(PITUniverseError,'historical backfill'):
            self.archive(now='2026-09-10T09:16:00+08:00')
        bad=self.plan();bad['sources'][0]['url']='https://example.com/list'
        with self.assertRaisesRegex(PITUniverseError,'host must match'):self.archive(bad)
        bad=self.plan();bad['members'][0]['symbol']='sz.000001'
        with self.assertRaisesRegex(PITUniverseError,'binding'):self.archive(bad)
        bad=self.plan();bad['sources'][0]['available_at']='2026-09-10T09:16:00+08:00'
        with self.assertRaisesRegex(PITUniverseError,'cutoff'):self.archive(bad)

    def test_document_or_receipt_tampering_fails_closed(self):
        result=self.archive();receipt=read_checked(Path(result['path']))
        document=self.root/receipt['sources'][0]['document']['path'];original=document.read_bytes()
        document.write_bytes(b'tampered')
        audit=audit_pit_universe(self.root)
        self.assertEqual(audit['verified_receipts'],0);self.assertEqual(audit['invalid_receipts'],1)
        with self.assertRaises(PITUniverseError):load_pit_universe_snapshot(self.root,result['universe_snapshot'])
        document.write_bytes(original);path=Path(result['path']);value=read_checked(path);value['member_count']=1;write_checked(path,value)
        audit=audit_pit_universe(self.root);self.assertEqual(audit['invalid_receipts'],1)

    def test_approval_input_freeze_preserves_receipt_membership_and_version(self):
        import polars as pl
        from quantlab.data.universe import UniverseConfig,build_universe
        from quantlab.storage.frozen_inputs import freeze_inputs,load_frozen_inputs
        result=self.archive();config=UniverseConfig(mode='pit',pit_snapshot_ids=(result['universe_snapshot'],))
        universe=build_universe(self.root,('sh.600001','sh.600099'),config)
        bars=pl.DataFrame({'symbol':['sh.600001','sh.600099'],
            'datetime':[datetime.fromisoformat('2026-09-10T15:00:00+08:00')]*2})
        self.assertEqual(universe.mask(bars)['eligible'].to_list(),[True,False])
        manifest={};frames=freeze_inputs(type('Captured',(),{'loads':[]})(),universe,manifest)
        frozen=self.root/'frozen';frozen.mkdir()
        for name,frame in frames.items():frame.write_parquet(frozen/name)
        _,restored=load_frozen_inputs(frozen,manifest)
        self.assertEqual(restored.version,universe.version)
        self.assertEqual(restored.mask(bars)['eligible'].to_list(),[True,False])

    def test_cli_requires_all_host_confirmations_and_is_readable(self):
        plan=self.plan('2099-01-05');plan['sources'][0]['published_at']='2020-01-01T00:00:00+08:00'
        plan['sources'][0]['available_at']='2020-01-01T00:01:00+08:00'
        path=self.root/'plan.json';path.write_text(json.dumps(plan))
        base=['--data-root',str(self.root),'--call','archive','--plan',str(path)]
        stream=StringIO()
        with redirect_stdout(stream):code=universe_cli(base)
        self.assertEqual(code,2);self.assertFalse(json.loads(stream.getvalue())['ok'])
        stream=StringIO()
        with redirect_stdout(stream):code=universe_cli([*base,'--confirm-publication-times',
            '--confirm-semantic-mapping','--confirm-complete-official-universe'])
        self.assertEqual(code,0);snapshot=json.loads(stream.getvalue())['data']['universe_snapshot']
        stream=StringIO()
        with redirect_stdout(stream):code=universe_cli(['--data-root',str(self.root),'--call','get',
            '--snapshot',snapshot,'--effective-session','2099-01-05'])
        self.assertEqual(code,0);self.assertEqual(json.loads(stream.getvalue())['data']['member_count'],2)


if __name__=='__main__':unittest.main()
