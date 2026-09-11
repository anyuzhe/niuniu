from datetime import datetime,date
import unittest
import polars as pl
from quantlab.agent.refresh_readiness import latest_nominal_session,watch_readiness
from quantlab.agent.watchlist import WatchService
from quantlab.app import build_runner
from quantlab.workbench.jobs import prepare
import test_baostock_data as data_fixture
from test_baostock_data import SDK,plan


class CalendarReadinessTests(unittest.TestCase):
    def calendar(self):return pl.DataFrame(SDK().query_trade_dates(start_date='2025-01-01',end_date='2025-01-10').rows)
    def test_update_window_weekend_timezone_and_unknown_calendar(self):
        frame=self.calendar()
        self.assertEqual(latest_nominal_session(frame,datetime.fromisoformat('2025-01-06T17:50:00+08:00'),'qfq'),date(2025,1,3))
        self.assertEqual(latest_nominal_session(frame,datetime.fromisoformat('2025-01-06T10:30:00+00:00'),'qfq'),date(2025,1,6))
        self.assertEqual(latest_nominal_session(frame,datetime.fromisoformat('2025-01-05T20:00:00+08:00'),'raw'),date(2025,1,3))
        with self.assertRaisesRegex(ValueError,'缺日'):
            latest_nominal_session(frame.filter(pl.col('calendar_date')!='2025-01-04'),datetime.fromisoformat('2025-01-06T20:00:00+08:00'),'qfq')
        with self.assertRaisesRegex(ValueError,'不在'):
            latest_nominal_session(frame,datetime.fromisoformat('2026-01-06T20:00:00+08:00'),'qfq')
        with self.assertRaises(ValueError):latest_nominal_session(frame,datetime(2025,1,6),'raw')
    def test_watch_candidate_is_not_approval_or_execution(self):
        fixture=data_fixture.BaostockDataTests();fixture.setUp();self.addCleanup(fixture.doCleanups);fixture.imported()
        spec={'symbols':plan()['symbols'],'start':plan()['start'],'end':'2025-01-03','factor':'BASE.MOMENTUM',
            'parameters':{'lookback':1},'horizons':[1],'quantiles':3,'replay':True}
        cfg=prepare(spec).config;root=fixture.root;dataset=fixture.directory/'dataset'
        result=build_runner(dataset,root,cfg.data.symbols,'qfq').run(cfg)
        service=WatchService(root);watch=service.create('calendar-test',result.run_id,windows=[2],min_dates=1)
        wid=watch['watch_id'];args=(root,wid,fixture.identifier,'2025-01-06T20:00:00+08:00')
        checked=watch_readiness(*args)
        self.assertEqual(checked['status'],'candidate_for_refresh')
        self.assertEqual(checked['proposed_end'],'2025-01-06')
        self.assertEqual(set(checked['symbols_behind']),set(plan()['symbols']))
        self.assertEqual(checked['new_research_jobs'],0)
        self.assertFalse(list(root.glob('_jobs/*.json')))
        service.store.set_active(wid,False)
        self.assertEqual(watch_readiness(*args)['status'],'paused')
        service.store.set_active(wid,True)
        from unittest.mock import patch
        with patch('quantlab.experiments.runner.runtime_fingerprint',return_value={}):
            self.assertEqual(watch_readiness(*args)['status'],'baseline_rebuild_required')
        (result.artifact_path/'observations.parquet').write_bytes(b'changed-fixture')
        self.assertEqual(watch_readiness(*args)['status'],'source_unverified')

    def test_no_released_session_and_duplicate_days(self):
        frame=self.calendar().filter(pl.col('calendar_date')=='2025-01-01')
        stamp=datetime.fromisoformat('2025-01-01T12:00:00+08:00')
        self.assertIsNone(latest_nominal_session(frame,stamp,'raw'))
        with self.assertRaises(ValueError):latest_nominal_session(pl.concat([frame,frame]),stamp,'raw')
