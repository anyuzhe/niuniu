from datetime import date, datetime, timedelta
import unittest
from unittest.mock import Mock, patch
import polars as pl
from quantlab.data.session_coverage import audit_daily_coverage, calendar_sessions


class SessionCoverageTests(unittest.TestCase):
    def setUp(self):
        self.start=date(2025,1,3);self.end=date(2025,1,7)
        self.clock=datetime.fromisoformat('2025-01-07T20:00:00+08:00')
        self.symbols=['sh.600000','sh.600519','sz.000001']
        self.calendar=pl.DataFrame({'calendar_date':['2025-01-03','2025-01-04',
            '2025-01-05','2025-01-06','2025-01-07'],'is_trading_day':['1','0','0','1','1']})
        rows=[]
        for symbol in self.symbols:
            for day in ('03','06','07'):
                at=datetime.fromisoformat('2025-01-'+day+'T15:00:00+08:00')
                rows.append({'symbol':symbol,'datetime':at,'available_at':at,'timeframe':'1d','volume':0.})
        self.bars=pl.DataFrame(rows)
    def audit(self,bars=None,calendar=None,clock=None):
        return audit_daily_coverage(self.bars if bars is None else bars,
            self.calendar if calendar is None else calendar,self.symbols,self.start,self.end,clock or self.clock)
    def test_complete_zero_volume_rows_and_weekends_are_preserved(self):
        before=self.bars.clone();value=self.audit()
        self.assertEqual(value['status'],'complete')
        self.assertEqual(value['expected_symbol_sessions'],9)
        self.assertTrue(self.bars.equals(before))
        self.assertEqual(calendar_sessions(self.calendar,self.start,self.end),(self.start,date(2025,1,6),self.end))
    def test_middle_gap_caught_despite_complete_latest_date(self):
        frame=self.bars.filter(~((pl.col('symbol')==self.symbols[0]) & (pl.col('datetime').dt.day()==6)))
        value=self.audit(frame);self.assertEqual(value['status'],'incomplete')
        self.assertEqual(value['symbols'][0]['missing_examples'],['2025-01-06'])
        self.assertEqual(value['symbols'][0]['missing_sessions'],1)
    def test_duplicates_non_sessions_extra_symbols_and_intraday_rows(self):
        for field,extra in [
            ('duplicate_sessions',self.bars.head(1)),
            ('unexpected_sessions',self.bars.head(1).with_columns(
                pl.col('datetime')+pl.duration(days=1),pl.col('available_at')+pl.duration(days=1))),
            ('off_close_rows',self.bars.head(1).with_columns(
                pl.col('datetime')+pl.duration(minutes=1),pl.col('available_at')+pl.duration(minutes=1)))]:
            value=self.audit(pl.concat([self.bars,extra]))
            self.assertEqual(value['status'],'incomplete');self.assertGreater(value['symbols'][0][field],0)
        extra=self.bars.head(1).with_columns(pl.lit('OTHER').alias('symbol'))
        self.assertEqual(self.audit(pl.concat([self.bars,extra]))['unexpected_symbol_count'],1)
    def test_delayed_rows_remain_missing_until_available(self):
        frame=self.bars.with_columns(pl.when(pl.col('datetime').dt.day()==7)
            .then(pl.col('available_at')+pl.duration(days=1)).otherwise(pl.col('available_at')).alias('available_at'))
        now=self.audit(frame);self.assertEqual(now['status'],'incomplete')
        self.assertEqual(now['symbols'][0]['not_yet_available_rows'],1)
        self.assertEqual(self.audit(frame,clock=self.clock+timedelta(days=1))['status'],'complete')
    def test_calendar_unknown_duplicate_and_missing_weekend_rejected(self):
        cases=[self.calendar.filter(pl.col('calendar_date')!='2025-01-04'),
            pl.concat([self.calendar,self.calendar.head(1)]),
            self.calendar.with_columns(pl.lit('?').alias('is_trading_day'))]
        for calendar in cases:
            with self.assertRaises(ValueError):self.audit(calendar=calendar)
    def test_timezone_conversion_and_invalid_timestamps(self):
        utc=self.bars.with_columns(pl.col('datetime','available_at').dt.convert_time_zone('UTC'))
        self.assertEqual(self.audit(utc)['status'],'complete')
        naive=self.bars.with_columns(pl.col('datetime','available_at').dt.replace_time_zone(None))
        with self.assertRaises(ValueError):self.audit(naive)
        with self.assertRaises(ValueError):self.audit(clock=datetime(2025,1,7))
        early=self.bars.with_columns(pl.col('available_at')-pl.duration(seconds=1))
        with self.assertRaises(ValueError):self.audit(early)
    def test_empty_input_and_missing_symbols_are_not_complete(self):
        result=self.audit(self.bars.head(0))
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(sum(v['missing_sessions'] for v in result['symbols']),9)
        with self.assertRaises(ValueError):audit_daily_coverage(self.bars,self.calendar,
            [self.symbols[0]]*2,self.start,self.end,self.clock)


class SchedulerCoverageTests(unittest.TestCase):
    def setup_workspace(self,missing=False,end='2025-01-10'):
        import test_baostock_data as fixtures
        from quantlab.app import build_runner
        from quantlab.workbench.jobs import prepare
        from quantlab.agent.watchlist import WatchService
        from quantlab.agent.tracking_control_store import ControlStore
        class SDK(fixtures.SDK):
            def query_history_k_data_plus(self,**kwargs):
                response=super().query_history_k_data_plus(**kwargs)
                if missing and kwargs['code']=='sh.600000':
                    response.rows=[r for r in response.rows if r['date']!='2025-01-07']
                return response
        fixture=fixtures.BaostockDataTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        receipt=fixture.imported({**fixtures.plan(),'end':end},SDK())
        self.assertTrue(receipt['dataset_ready'],receipt)
        self.root=fixture.root;self.data=fixture.directory/'dataset';self.import_id=fixture.identifier
        self.spec={'question':'calendar coverage fixture','symbols':fixtures.plan()['symbols'],
            'start':'2025-01-01','end':'2025-01-03','factor':'BASE.MOMENTUM',
            'parameters':{'lookback':1},'horizons':[1],'quantiles':3,'replay':True}
        cfg=prepare(self.spec).config
        baseline=build_runner(self.data,self.root,cfg.data.symbols,'qfq').run(cfg)
        self.watch=WatchService(self.root,self.data).create('覆盖测试',baseline.run_id,windows=[3],min_dates=1)['watch_id']
        self.store=ControlStore(self.root)
        self.clock=datetime.fromisoformat('2025-01-10T20:00:00+08:00')
        from quantlab.agent.tracking_authorization import preview_control,authorize_control
        from quantlab.storage.codec import digest
        plan=preview_control(self.root,self.data,self.watch,self.import_id,end,
            (self.clock+timedelta(days=2)).isoformat(),now=self.clock)
        authorize_control(self.root,self.data,plan,digest(plan),confirmed=True,now=self.clock)
    def test_middle_gap_blocks_before_queue_and_reports_precise_dates(self):
        from quantlab.agent.tracking_scheduler import TrackingScheduler
        from quantlab.agent.market_data_tools import MarketDataResearchAPI
        self.setup_workspace(missing=True)
        queue=Mock(side_effect=AssertionError('Incomplete data must not create a queue'))
        result=TrackingScheduler(self.root,self.data,queue).tick(now=self.clock)
        self.assertEqual(result['controls'][0]['status'],'blocked');queue.assert_not_called()
        state=self.store.get(self.watch);self.assertEqual(state['cycles'],[])
        self.assertEqual(state['delivery_audit']['symbols'][0]['missing_examples'],['2025-01-07'])
        tool=MarketDataResearchAPI(self.root,self.data).call('get_tracking_control',{'watch_id':self.watch})
        self.assertTrue(tool['ok'],tool)
        self.assertEqual(tool['data']['delivery_audit']['status'],'incomplete')
    def test_weekend_end_cap_uses_last_trading_session_and_stops(self):
        from quantlab.agent.tracking_scheduler import TrackingScheduler
        from quantlab.workbench.jobs import JobQueue
        from quantlab.agent.watchlist import WatchService
        self.setup_workspace(end='2025-01-12')
        queue=JobQueue(self.root,self.data);engine=TrackingScheduler(self.root,self.data,lambda:queue)
        try:engine.tick(now=self.clock)
        finally:queue.close()
        self.assertEqual(len(queue.list()),1)
        self.assertEqual(queue.list()[0]['status'],'completed',queue.list())
        self.assertEqual(queue.list()[0]['spec']['end'],'2025-01-10')
        engine.tick(now=self.clock+timedelta(hours=1))
        state=self.store.get(self.watch)
        self.assertEqual(state['status'],'end_cap_reached');self.assertFalse(state['enabled'])
        self.assertEqual(state['delivery_audit']['status'],'complete')
        self.assertEqual(WatchService(self.root,self.data).get(self.watch)['snapshot_count'],2)
    def test_changed_input_between_audit_and_signature_is_blocked(self):
        from quantlab.agent.tracking_scheduler import TrackingScheduler
        from quantlab.experiments.campaign_state import input_signature
        self.setup_workspace();queue=Mock(side_effect=AssertionError('No queue'))
        def changed(spec,root):
            value=input_signature(spec,root);value['inputs'][0]['bars_hash']='changed'
            return value
        with patch('quantlab.agent.tracking_scheduler.input_signature',side_effect=changed):
            result=TrackingScheduler(self.root,self.data,queue).tick(now=self.clock)
        self.assertEqual(result['controls'][0]['status'],'blocked');queue.assert_not_called()
        self.assertEqual(self.store.get(self.watch)['cycles'],[])
        self.assertIn('输入已变化',self.store.get(self.watch)['notices']['blocked']['detail'])
