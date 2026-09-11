from copy import deepcopy
from datetime import date
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import contextlib
import io
import tempfile
import unittest
import polars as pl
import test_baostock_data as fixtures
from quantlab.data.baostock_ingest import collect, import_root
from quantlab.data.baostock_series import SeriesService, BaostockSeriesProvider, delivery, MARKER
from quantlab.data.base import DataRequest
from quantlab.data.provider import local_data_provider
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest


class BaostockSeriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.service=SeriesService(self.root)
    def batch(self,end='2025-01-03',sdk=None):
        spec={**fixtures.plan(),'datasets':['daily_raw','daily_qfq','calendar'], 'quarters':[], 'end':end}
        identifier=str(uuid4()); folder=import_root(self.root)/identifier
        with contextlib.redirect_stdout(io.StringIO()): result=collect(spec,folder,sdk or fixtures.SDK(),interval=0)
        self.assertTrue(result['dataset_ready'],result)
        return identifier
    def series(self):
        old=self.batch(); state=self.service.create('固定数据通道',old,confirmed=True)
        return state['series_id'],old
    def request(self,end='2025-01-03'):
        return DataRequest(tuple(fixtures.plan()['symbols']),Timeframe.DAILY,date(2025,1,1),date.fromisoformat(end))
    def test_explicit_confirmation_and_absent_reads_do_not_create(self):
        self.assertEqual(self.service.list(),{'series':[],'errors':[]})
        self.assertEqual(list(self.root.iterdir()),[])
        with self.assertRaises(ValueError): self.service.create('x',str(uuid4()))
        with self.assertRaises(ValueError): self.service.folder('../escape')
    def test_rollover_preserves_old_batches_stable_root_and_repeated_acceptance(self):
        sid,old=self.series(); path=self.service.folder(sid); inode=path.stat().st_ino
        original={str(p):p.read_bytes() for p in (import_root(self.root)/old).rglob('*') if p.is_file()}
        before=local_data_provider(path,'qfq').load(self.request())
        new=self.batch('2025-01-10'); plan=self.service.preview(sid,new)
        self.assertFalse(plan['revisions_require_confirmation'])
        self.assertEqual(plan['comparisons']['qfq']['added_rows'],15)
        with self.assertRaises(ValueError):self.service.accept(plan,digest(plan))
        result=self.service.accept(plan,digest(plan),confirmed=True)
        self.assertTrue(result['created']);self.assertEqual(path.stat().st_ino,inode)
        self.assertFalse(SeriesService(self.root).accept(plan,digest(plan),confirmed=True)['created'])
        after=local_data_provider(path,'qfq').load(self.request('2025-01-10'))
        self.assertEqual(after.bars.height,24);self.assertNotEqual(before.snapshot.snapshot_id,after.snapshot.snapshot_id)
        self.assertEqual(after.snapshot.source,before.snapshot.source)
        self.assertTrue(all(Path(p).read_bytes()==raw for p,raw in original.items()))
        self.assertFalse((self.root/'_jobs').exists())
    def test_middle_day_gap_is_rejected_even_when_latest_date_exists(self):
        class Missing(fixtures.SDK):
            def query_history_k_data_plus(self,**kw):
                r=super().query_history_k_data_plus(**kw)
                r.rows=[v for v in r.rows if v['date']!='2025-01-07'];return r
        sid,_=self.series(); new=self.batch('2025-01-10',Missing())
        with self.assertRaisesRegex(ValueError,'daily gap'):self.service.preview(sid,new)
        self.assertEqual(self.service.get(sid)['generation'],1)
    def test_revisions_require_additional_consent_and_keep_original_history(self):
        class Revised(fixtures.SDK):
            def query_history_k_data_plus(self,**kw):
                r=super().query_history_k_data_plus(**kw)
                for row in r.rows:
                    if row['date']=='2025-01-02':
                        for k in ('open','high','low','close'):row[k]=str(float(row[k])*1.01)
                return r
        sid,_=self.series(); original=self.service.get(sid)['history'][0]
        new=self.batch('2025-01-10',Revised()); plan=self.service.preview(sid,new)
        self.assertTrue(plan['revisions_require_confirmation'])
        self.assertEqual(plan['comparisons']['raw']['revised_rows'],3)
        with self.assertRaisesRegex(ValueError,'separate confirmation'):
            self.service.accept(plan,digest(plan),confirmed=True)
        self.service.accept(plan,digest(plan),confirmed=True,accept_revisions=True)
        self.assertEqual(self.service.get(sid)['history'][0],original)
    def test_stale_plan_and_tampered_batch_or_marker_never_fall_back(self):
        sid,_=self.series(); incoming=self.batch('2025-01-10'); plan=self.service.preview(sid,incoming)
        changed=deepcopy(plan);changed['incoming']['end']='2025-01-11'
        with self.assertRaisesRegex(ValueError,'Stale'):self.service.accept(changed,digest(changed),confirmed=True)
        path=import_root(self.root)/incoming/'dataset/lake/silver/qfq_kline_daily/sh_600000.parquet'
        path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaises(ValueError):self.service.accept(plan,digest(plan),confirmed=True)
        root=self.service.folder(sid);(root/MARKER).write_text('{}')
        with self.assertRaises(ValueError):local_data_provider(root,'qfq').load(self.request())
    def test_read_during_publication_change_is_rejected(self):
        sid,_=self.series(); provider=BaostockSeriesProvider(self.service.folder(sid))
        from quantlab.data.baostock_series import read_series
        first=read_series(provider.root);second=deepcopy(first);second['name']='changed'
        with patch('quantlab.data.baostock_series.read_series',side_effect=[first,second]):
            with self.assertRaisesRegex(ValueError,'during loading'):provider.load(self.request())
    def test_history_rewind_and_conflicting_create_rejected(self):
        sid,old=self.series(); incoming=self.batch('2025-01-10');plan=self.service.preview(sid,incoming)
        self.service.accept(plan,digest(plan),confirmed=True)
        with self.assertRaisesRegex(ValueError,'backwards'):self.service.preview(sid,old)
        with self.assertRaisesRegex(ValueError,'different origin'):
            self.service.create('different',old,series_id=sid,confirmed=True)
    def test_series_lock_prevents_competing_publications(self):
        sid,_=self.series(); incoming=self.batch('2025-01-10');plan=self.service.preview(sid,incoming)
        with self.service.locked(sid):
            with self.assertRaises(BlockingIOError):self.service.accept(plan,digest(plan),confirmed=True)
        self.assertEqual(self.service.get(sid)['generation'],1)
    def test_original_queue_frozen_replay_and_same_grant_across_batches(self):
        from datetime import datetime, timedelta
        from quantlab.workbench.jobs import prepare, execute, JobQueue
        from quantlab.agent.watchlist import WatchService
        from quantlab.agent.tracking_authorization import preview_control, authorize_control
        from quantlab.agent.tracking_scheduler import TrackingScheduler
        from quantlab.storage.bundle import reproduce_artifact
        sid,_=self.series();data=self.service.folder(sid);new=self.batch('2025-01-10')
        spec={'question':'series fixture','symbols':fixtures.plan()['symbols'],'start':'2025-01-01',
            'end':'2025-01-03','factor':'BASE.MOMENTUM','parameters':{'lookback':1},
            'horizons':[1],'quantiles':3,'replay':True}
        baseline=execute(prepare(spec),data,self.root)
        watch=WatchService(self.root,data).create('series watch',baseline.run_id,windows=[3],min_dates=1)['watch_id']
        now=__import__('datetime').datetime.fromisoformat('2025-01-06T20:00:00+08:00')
        grant=preview_control(self.root,data,watch,new,'2025-01-10',(now+timedelta(days=3)).isoformat(),now=now)
        authorize_control(self.root,data,grant,digest(grant),confirmed=True,now=now)
        queue=JobQueue(self.root,data);engine=TrackingScheduler(self.root,data,lambda:queue)
        try:
            blocked=engine.tick(now=now);self.assertEqual(len(queue.list()),0)
            plan=self.service.preview(sid,new);self.service.accept(plan,digest(plan),confirmed=True)
            engine.tick(now=now+timedelta(hours=1))
        finally:queue.close()
        self.assertEqual(queue.list()[0]['status'],'completed',queue.list())
        engine.tick(now=now+timedelta(hours=1,minutes=1))
        self.assertEqual(WatchService(self.root,data).get(watch)['snapshot_count'],2)
        with patch.object(BaostockSeriesProvider,'load',side_effect=AssertionError('no live series')):
            self.assertEqual(reproduce_artifact(baseline.artifact_path,self.root/'replayed')['status'],'numerically_matched')
    def test_model_reads_publications_but_cannot_publish_or_download(self):
        from quantlab.agent.market_data_tools import MarketDataResearchAPI
        sid,_=self.series();api=MarketDataResearchAPI(self.root)
        result=api.call('list_baostock_series',{'offset':0,'limit':20})
        self.assertTrue(result['ok'],result);self.assertEqual(result['data']['total'],1)
        detail=api.call('get_baostock_series',{'series_id':sid})
        self.assertTrue(detail['ok'],detail);self.assertFalse(detail['data']['source_files_verified'])
        for name in ('accept_series','create_series','download_series'):
            self.assertFalse(api.call(name,{})['ok'])
        self.assertEqual(self.service.get(sid)['generation'],1)
    def test_publication_change_after_queue_admission_fails_closed(self):
        from threading import Event
        from quantlab.workbench.jobs import JobQueue
        from quantlab.experiments.campaign_state import input_signature
        from quantlab.experiments.runner import runtime_fingerprint
        sid,_=self.series();data=self.service.folder(sid);new=self.batch('2025-01-10')
        plan=self.service.preview(sid,new)
        spec={'symbols':fixtures.plan()['symbols'],'start':'2025-01-01','end':'2025-01-03',
            'factor':'BASE.MOMENTUM','parameters':{'lookback':1},'horizons':[1],'quantiles':3,'replay':True}
        guard={'runtime':runtime_fingerprint(),'cooperative_seconds':300,'max_active_jobs':4,
            'input_signature':digest(input_signature(spec,data))}
        queue=JobQueue(self.root,data);gate=Event();queue.executor.submit(lambda:gate.wait(10))
        try:
            queue.submit(str(uuid4()),spec,execution_guard=guard)
            self.service.accept(plan,digest(plan),confirmed=True)
        finally:gate.set();queue.close()
        self.assertEqual(queue.list()[0]['status'],'failed',queue.list())
        self.assertIn('输入已变化',queue.list()[0]['error'])
