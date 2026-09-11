from copy import deepcopy
from datetime import datetime,timedelta
from threading import Event
from unittest.mock import patch
import unittest
import polars as pl
import test_baostock_data as data_fixture
from quantlab.app import build_runner
from quantlab.workbench.jobs import prepare,JobQueue
from quantlab.agent.watchlist import WatchService
from quantlab.agent.tracking_authorization import preview_control,authorize_control
from quantlab.agent.tracking_control_store import ControlStore
from quantlab.agent.tracking_scheduler import TrackingScheduler
from quantlab.storage.codec import digest

NOW=datetime.fromisoformat('2025-01-06T20:00:00+08:00')


class TrackingSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=data_fixture.BaostockDataTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.fixture.imported()
        self.output=self.fixture.root;self.data=self.fixture.directory/'dataset'
        self.spec={'question':'scheduler fixture','symbols':data_fixture.plan()['symbols'],
            'start':'2025-01-01','end':'2025-01-03','factor':'BASE.MOMENTUM',
            'parameters':{'lookback':1},'horizons':[1],'quantiles':3,'replay':True}
        config=prepare(self.spec).config
        self.baseline=build_runner(self.data,self.output,config.data.symbols,'qfq').run(config)
        self.watches=WatchService(self.output,self.data)
        self.watch=self.watches.create('固定规则',self.baseline.run_id,windows=[3],min_dates=1)['watch_id']
        self.store=ControlStore(self.output)
    def plan(self,**kwargs):
        return preview_control(self.output,self.data,self.watch,self.fixture.identifier,
            '2025-01-10',(NOW+timedelta(days=7)).isoformat(),now=NOW,**kwargs)
    def grant(self,**kwargs):
        plan=self.plan(**kwargs)
        return authorize_control(self.output,self.data,plan,digest(plan),confirmed=True,now=NOW)
    def test_default_off_confirmation_and_frozen_scope(self):
        make=__import__('unittest.mock',fromlist=['Mock']).Mock()
        engine=TrackingScheduler(self.output,self.data,make)
        self.assertEqual(engine.tick(now=NOW)['controls'],[]);make.assert_not_called()
        self.assertFalse(self.store.root.exists())
        plan=self.plan()
        with self.assertRaisesRegex(ValueError,'明确授权'):
            authorize_control(self.output,self.data,plan,digest(plan),now=NOW)
        changed=deepcopy(plan);changed['spec']['parameters']={'lookback':9}
        with self.assertRaises(ValueError):
            authorize_control(self.output,self.data,changed,digest(changed),confirmed=True,now=NOW)
        self.assertIsNone(self.store.get(self.watch))
    def test_real_queue_auto_sync_reopen_budget_and_no_duplicates(self):
        self.grant(max_jobs=1);queue=JobQueue(self.output,self.data)
        engine=TrackingScheduler(self.output,self.data,lambda:queue)
        try:engine.tick(now=NOW)
        finally:queue.close()
        self.assertEqual(queue.list()[0]['status'],'completed',queue.list())
        again=TrackingScheduler(self.output,self.data,lambda:queue)
        again.tick(now=NOW+timedelta(hours=1));again.tick(now=NOW+timedelta(hours=2))
        self.assertEqual(len(queue.list()),1)
        self.assertEqual(self.watches.get(self.watch)['snapshot_count'],2)
        state=self.store.get(self.watch)
        self.assertFalse(state['enabled']);self.assertEqual(state['status'],'budget_exhausted')
        self.assertEqual(state['cycles'][0]['status'],'synced')
    def test_lost_submit_acknowledgement_reuses_job(self):
        self.grant();queue=JobQueue(self.output,self.data);submit=queue.submit
        def lose(*args,**kwargs):
            submit(*args,**kwargs);raise OSError('lost acknowledgement fixture')
        engine=TrackingScheduler(self.output,self.data,lambda:queue)
        try:
            with patch.object(queue,'submit',side_effect=lose):engine.tick(now=NOW)
        finally:queue.close()
        self.assertEqual(self.store.get(self.watch)['cycles'][0]['status'],'reserved')
        engine.tick(now=NOW+timedelta(minutes=1))
        self.assertEqual(len(queue.list()),1)
        self.assertEqual(self.watches.get(self.watch)['snapshot_count'],2)
    def test_revoke_and_expiry_do_not_start_new_jobs(self):
        self.grant();self.store.revoke(self.watch)
        engine=TrackingScheduler(self.output,self.data,lambda:(_ for _ in ()).throw(AssertionError('no queue')))
        engine.tick(now=NOW)
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
        self.grant();engine.tick(now=NOW+timedelta(days=8))
        self.assertFalse(self.store.get(self.watch)['enabled'])
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
    def test_paused_watch_and_changed_calendar_stop_admission(self):
        self.grant();self.watches.store.set_active(self.watch,False)
        engine=TrackingScheduler(self.output,self.data,lambda:(_ for _ in ()).throw(AssertionError('no queue')))
        engine.tick(now=NOW);self.assertFalse(self.store.get(self.watch)['enabled'])
        self.watches.store.set_active(self.watch,True);self.grant()
        source=self.data/'research/calendar.parquet';source.write_bytes(b'corrupt fixture')
        engine.tick(now=NOW)
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
    def test_missing_delivery_waits_and_notifications_are_cooled_down(self):
        self.grant();source=self.data/'lake/silver/qfq_kline_daily/sh_600000.parquet'
        source.write_bytes(source.read_bytes()+b'x')
        engine=TrackingScheduler(self.output,self.data,lambda:(_ for _ in ()).throw(AssertionError('no queue')))
        engine.tick(now=NOW);first=self.store.get(self.watch)
        self.assertEqual(first['status'],'blocked');self.assertEqual(len(first['cycles']),0)
        self.store.acknowledge(self.watch)
        engine.tick(now=NOW+timedelta(hours=1));again=self.store.get(self.watch)
        self.assertEqual(len(again['notices']),1)
        self.assertFalse(again['notices']['blocked']['unread'])
        self.assertEqual(again['notices']['blocked']['occurrences'],2)
    def test_input_changed_while_queued_is_rejected_before_computation(self):
        self.grant();queue=JobQueue(self.output,self.data);gate=Event()
        queue.executor.submit(lambda:gate.wait(10))
        engine=TrackingScheduler(self.output,self.data,lambda:queue)
        try:
            engine.tick(now=NOW)
            path=self.data/'lake/silver/qfq_kline_daily/sh_600000.parquet'
            path.write_bytes(path.read_bytes()+b'changed after admission')
        finally:gate.set();queue.close()
        self.assertEqual(queue.list()[0]['status'],'failed')
        self.assertIn('输入已变化',queue.list()[0]['error'])
        engine.tick(now=NOW+timedelta(minutes=1))
        self.assertEqual(self.watches.get(self.watch)['snapshot_count'],1)
    def test_wakeup_coalesces_missed_checks_into_one_latest_target(self):
        self.grant();queue=JobQueue(self.output,self.data)
        engine=TrackingScheduler(self.output,self.data,lambda:queue)
        try:engine.tick(now=NOW+timedelta(days=3))
        finally:queue.close()
        engine.tick(now=NOW+timedelta(days=3,minutes=1))
        self.assertEqual(len(queue.list()),1)
        self.assertEqual(queue.list()[0]['spec']['end'],'2025-01-09')
        self.assertEqual(self.watches.get(self.watch)['snapshot_count'],2)
    def test_read_only_tools_cannot_enable_grants(self):
        from quantlab.agent.market_data_tools import MarketDataResearchAPI
        api=MarketDataResearchAPI(self.output,self.data)
        self.assertEqual(api.call('get_tracking_control',{'watch_id':self.watch})['data']['status'],'not_authorized')
        for name in ('authorize_control','enable_tracking','approve_tracking','run_tracking'):
            self.assertFalse(api.call(name,{})['ok'])
        self.grant()
        result=api.call('get_tracking_control',{'watch_id':self.watch})
        self.assertTrue(result['ok']);self.assertEqual(result['data']['max_jobs'],3)
        self.assertFalse(result['data']['model_can_authorize'])
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
    def test_revoke_reserved_unsubmitted_job_never_replays_it(self):
        self.grant();queue=JobQueue(self.output,self.data)
        engine=TrackingScheduler(self.output,self.data,lambda:queue)
        try:
            with patch.object(queue,'submit',side_effect=OSError('before durable queue write')):
                engine.tick(now=NOW)
            self.store.revoke(self.watch);engine.tick(now=NOW+timedelta(hours=1))
        finally:queue.close()
        self.assertEqual(queue.list(),[])
        self.assertEqual(self.store.get(self.watch)['cycles'][0]['status'],'abandoned')
    def test_concurrent_ticks_share_one_receipt_and_one_job(self):
        from concurrent.futures import ThreadPoolExecutor
        self.grant();queue=JobQueue(self.output,self.data)
        entered=Event();release=Event()
        engine=TrackingScheduler(self.output,self.data,lambda:queue)
        original=engine.data_signature
        def block(*args):
            entered.set();release.wait(10);return original(*args)
        try:
            with patch.object(engine,'data_signature',side_effect=block),ThreadPoolExecutor(1) as executor:
                first=executor.submit(engine.tick,now=NOW)
                self.assertTrue(entered.wait(10))
                second=TrackingScheduler(self.output,self.data,lambda:queue).tick(now=NOW)
                self.assertEqual(second['controls'][0]['status'],'busy')
                release.set();first.result(timeout=20)
        finally:release.set();queue.close()
        self.assertEqual(len(queue.list()),1)

    def test_tick_reports_new_download_attempts(self):
        self.grant();engine=TrackingScheduler(self.output,self.data,lambda:(_ for _ in ()).throw(AssertionError('no queue')))
        def fake_advance(state,stamp):
            state.setdefault('data_updates',[]).append({'status':'downloading'})
            state['status']='fixture_download'
        with patch.object(engine,'advance',side_effect=fake_advance):
            result=engine.tick(now=NOW)
        self.assertEqual(result['network_requests'],1)
        self.assertEqual(result['controls'][0]['status'],'fixture_download')

    def test_auto_download_requires_fixed_series(self):
        with self.assertRaisesRegex(ValueError,'固定更新通道'):
            preview_control(self.output,self.data,self.watch,self.fixture.identifier,'2025-01-10',
                (NOW+timedelta(days=7)).isoformat(),auto_download=True,now=NOW)
        self.assertIsNone(self.store.get(self.watch))
