"""F16 source/date coverage tests on synthetic isolated material."""
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import hashlib
import polars as pl
from quantlab.data.calendar_review import get_trading_calendar, check_daily_date_coverage


class CalendarReviewTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.base=self.root/'lake/bronze/provider=baostock'
        for folder in ('trade_calendar','stock_basic','stock_kline_daily'):(self.base/folder).mkdir(parents=True)
        self.calendar_path=self.base/'trade_calendar/calendar.parquet'
        self.basic_path=self.base/'stock_basic/stock_basic.parquet'
        self.bar_path=self.base/'stock_kline_daily/sh_600001.parquet'
        self.days=[date(2025,1,3)+timedelta(days=i) for i in range(5)]
        self.calendar=pl.DataFrame({'calendar_date':[str(d) for d in self.days],'is_trading_day':['1','0','0','1','1']})
        self.calendar.write_parquet(self.calendar_path)
        self.basic=pl.DataFrame({'code':['sh.600001'],'ipoDate':['2000-01-01'],'outDate':['']})
        self.basic.write_parquet(self.basic_path)
        self.bars=pl.DataFrame({'code':['sh.600001']*3,'date':[self.days[i] for i in (0,3,4)],
                              'tradestatus':['1']*3,'adjustflag':['3']*3})
        self.bars.write_parquet(self.bar_path)
        self.args=dict(source='baostock_bronze',capture_id='',start='2025-01-03',end='2025-01-07')
    def check(self,**changes):
        return check_daily_date_coverage(self.root,symbols='sh.600001',**{**self.args,**changes})
    def tree(self):
        return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
    def test_complete_is_date_presence_only_and_source_explicit(self):
        before=self.tree();value=self.check()
        self.assertEqual(value['status'],'complete');self.assertFalse(value['incomplete'])
        self.assertEqual(value['records'][0]['expected_dates_count'],3)
        self.assertEqual(value['records'][0]['missing_dates'],[])
        self.assertFalse(value['strict_pit']);self.assertFalse(value['tradability_verified'])
        self.assertFalse(value['f9_export_verified']);self.assertEqual(self.tree(),before)
        self.assertEqual(get_trading_calendar(self.root,**self.args),value['calendar'])
    def test_equal_counts_different_sets_are_incomplete(self):
        self.bars.with_columns(pl.Series('date',[self.days[0],self.days[1],self.days[4]])).write_parquet(self.bar_path)
        row=self.check()['records'][0]
        self.assertEqual(row['actual_dates_count'],row['expected_dates_count'])
        self.assertEqual(row['missing_dates'],['2025-01-06']);self.assertEqual(row['unexpected_dates'],['2025-01-04'])
        self.assertFalse(row['date_set_complete'])
    def test_stale_calendar_and_missing_weekend_block_before_bars(self):
        for excluded in ('2025-01-07','2025-01-04'):
            self.calendar.filter(pl.col('calendar_date')!=excluded).write_parquet(self.calendar_path)
            value=self.check();self.assertEqual(value['status'],'blocked');self.assertEqual(value['records'],[])
            self.assertEqual(value['calendar']['missing_calendar_dates'],[excluded]);self.assertIsNone(value['calendar']['trading_dates'])
        self.calendar.write_parquet(self.calendar_path)
        future=self.check(end='2025-01-08');self.assertEqual(future['calendar']['max_date'],'2025-01-07')
        self.assertIn('2025-01-08',future['calendar']['missing_calendar_dates'])
    def test_duplicates_not_hidden_by_sets(self):
        pl.concat([self.bars,self.bars.head(1)]).write_parquet(self.bar_path)
        value=self.check();self.assertTrue(value['incomplete']);self.assertEqual(value['records'][0]['missing_dates'],[])
        self.assertEqual(value['records'][0]['duplicate_dates'],['2025-01-03'])
    def test_listing_interval_does_not_invent_prelisting_gaps(self):
        self.basic.with_columns(pl.lit('2025-01-06').alias('ipoDate'),pl.lit('2025-01-07').alias('outDate')).write_parquet(self.basic_path)
        self.bars.tail(2).write_parquet(self.bar_path)
        value=self.check();row=value['records'][0]
        self.assertEqual(value['status'],'complete');self.assertEqual(row['expected_dates_count'],2)
        self.assertEqual(row['not_listed_dates'],['2025-01-03'])
        self.bars.write_parquet(self.bar_path);self.assertEqual(self.check()['records'][0]['unexpected_dates'],['2025-01-03'])
    def test_missing_or_ambiguous_lifecycle_not_assumed(self):
        for basic in (self.basic.head(0),pl.concat([self.basic,self.basic]),self.basic.with_columns(pl.lit(None,dtype=pl.String).alias('ipoDate'))):
            basic.write_parquet(self.basic_path);value=self.check()
            self.assertTrue(value['incomplete']);self.assertTrue(value['errors']);self.assertIsNone(value['records'][0]['missing_dates'])
    def test_suspension_and_unknown_separate_from_presence(self):
        self.bars.with_columns(pl.Series('tradestatus',['1','0',None])).write_parquet(self.bar_path)
        value=self.check();row=value['records'][0];self.assertEqual(value['status'],'complete')
        self.assertEqual(row['suspended_dates'],['2025-01-06']);self.assertEqual(row['unknown_state_dates'],['2025-01-07'])
        self.assertFalse(value['f9_export_verified']);self.assertIn('requested_nontrading_rows',row['f9_blockers'])
    def test_calendar_changes_content_identity(self):
        one=get_trading_calendar(self.root,**self.args)
        self.calendar.with_columns(pl.when(pl.col('calendar_date')=='2025-01-04').then(pl.lit('1')).otherwise(pl.col('is_trading_day')).alias('is_trading_day')).write_parquet(self.calendar_path)
        two=get_trading_calendar(self.root,**self.args)
        self.assertNotEqual(one['calendar_content_hash'],two['calendar_content_hash']);self.assertNotEqual(one['evidence'][0]['sha256'],two['evidence'][0]['sha256'])
    def test_bad_calendar_flags_duplicate_dates_rejected(self):
        for bad in (pl.concat([self.calendar,self.calendar.head(1)]),self.calendar.with_columns(pl.lit('?').alias('is_trading_day')),
                    self.calendar.with_columns(pl.lit('20250103').alias('calendar_date'))):
            bad.write_parquet(self.calendar_path)
            with self.assertRaises(ValueError):get_trading_calendar(self.root,**self.args)
    def test_source_selection_bounds_managed_root_never_fallback(self):
        for changes in ({'source':''},{'source':'latest'},{'capture_id':'../escape'},{'end':'2025-01-02'},
                        {'start':'20250103'},{'end':'2027-01-01'}):
            with self.subTest(changes=changes),self.assertRaises((ValueError,TypeError)):self.check(**changes)
        (self.root/'archived-daily-dataset.json').write_text('{}')
        with self.assertRaises(ValueError):self.check()
    def test_missing_bars_is_error_not_empty_complete(self):
        self.bar_path.unlink();value=self.check()
        self.assertTrue(value['incomplete']);self.assertTrue(value['errors']);self.assertIsNone(value['records'][0]['missing_dates'])
    def test_wrong_code_or_adjustment_rejected(self):
        for bad in (self.bars.with_columns(pl.lit('sh.699999').alias('code')),self.bars.with_columns(pl.lit('2').alias('adjustflag'))):
            bad.write_parquet(self.bar_path);value=self.check();self.assertTrue(value['incomplete']);self.assertTrue(value['errors'])
    def test_no_sessions_is_not_complete(self):
        self.bar_path.unlink();value=self.check(start='2025-01-04',end='2025-01-05')
        self.assertEqual(value['status'],'blocked');self.assertIn('no_calendar_trading_sessions',value['blockers'])
    def test_symlink_source_or_member_rejected(self):
        linked=self.root/'linked';linked.symlink_to(self.base,target_is_directory=True)
        with self.assertRaises(ValueError):get_trading_calendar(linked,**self.args)
        target=self.root/'original.parquet';self.calendar_path.rename(target);self.calendar_path.symlink_to(target)
        with self.assertRaises(ValueError):self.check()
    def test_complete_missing_list_is_not_examples_only(self):
        days=[date(2025,1,1)+timedelta(days=i) for i in range(31)]
        pl.DataFrame({'calendar_date':[str(d) for d in days],'is_trading_day':['1']*31}).write_parquet(self.calendar_path)
        self.bars.head(0).write_parquet(self.bar_path)
        value=self.check(start='2025-01-01',end='2025-01-31')
        self.assertEqual(value['records'][0]['missing_dates'],[str(d) for d in days])
        self.assertEqual(value['status'],'incomplete')
    def test_mutation_during_inspection_fails(self):
        from quantlab.data.calendar_review import _symbol_result
        def change(*a,**k):
            result=_symbol_result(*a,**k);self.calendar_path.write_bytes(b'changed');return result
        with patch('quantlab.data.calendar_review._symbol_result',side_effect=change),self.assertRaisesRegex(ValueError,'changed'):
            self.check()


class ArchivedCalendarReviewTests(TestCase):
    def fixture(self):
        import test_archived_daily_dataset as fixtures
        f=fixtures.ArchivedDailyDatasetTests();self.addCleanup(f.doCleanups);f.setUp();return f
    def test_retro_source_bound_and_packed_no_writes(self):
        f=self.fixture();args=dict(source='retro_capture',capture_id=f.capture_id,start=f.start,end=f.end,source_workspace=f.source)
        before=f._tree_bytes(f.source);cal=get_trading_calendar(None,**args)
        self.assertEqual(cal['source_calendar_content_hash'],f.store.plan(f.capture_id)['calendar_content_hash'])
        value=check_daily_date_coverage(None,symbols=f.symbols,**args)
        self.assertTrue(cal['range_covered']);self.assertEqual(value['status'],'complete');self.assertEqual(f._tree_bytes(f.source),before)
        f.store.consolidate(f.capture_id,confirmed=True,remove_originals=True)
        packed=check_daily_date_coverage(None,symbols=f.symbols,**args)
        self.assertEqual(packed['records'],value['records']);self.assertEqual(packed['calendar']['calendar_content_hash'],cal['calendar_content_hash'])
        with self.assertRaises(ValueError):get_trading_calendar(None,**{**args,'capture_id':''})
    def test_dataset_uses_own_calendar_after_original_offline(self):
        f=self.fixture();dataset,_,_=f._export();f.source.rename(f.root/'offline')
        args=dict(source='archived_dataset',capture_id='',start=f.start,end=f.end)
        value=check_daily_date_coverage(dataset,symbols=f.symbols,**args)
        self.assertEqual(value['status'],'complete');self.assertTrue(value['calendar']['dataset_id'])
        self.assertEqual(check_daily_date_coverage(dataset,symbols=f.symbols,**{**args,'end':'2026-09-14'})['status'],'blocked')
        with self.assertRaises(ValueError):get_trading_calendar(dataset,**{**args,'source':'baostock_bronze'})
    def test_source_choice_uses_selected_calendar_not_newer_neighbor(self):
        f=self.fixture()
        base=CalendarReviewTests();self.addCleanup(base.doCleanups);base.setUp()
        args=dict(capture_id='',start=f.start,end=f.end)
        old=get_trading_calendar(base.root,source='baostock_bronze',source_workspace=f.source,**args)
        selected=get_trading_calendar(base.root,source='retro_capture',source_workspace=f.source,
            **{**args,'capture_id':f.capture_id})
        self.assertFalse(old['range_covered']);self.assertTrue(selected['range_covered'])
        self.assertNotEqual(old['calendar_content_hash'],selected['calendar_content_hash'])
    def test_retro_suspension_visible_without_relaxing_f9(self):
        import test_qm50_archived_inputs as fixtures
        from quantlab.data.archived_daily_dataset import preview_archived_daily_dataset
        f=fixtures.ArchivedQM50Tests();self.addCleanup(f.doCleanups);f.setUp()
        value=check_daily_date_coverage(None,source='retro_capture',capture_id=f.cap,symbols='sz.000001',start=f.start,end=f.end,source_workspace=f.source)
        self.assertEqual(value['status'],'complete');self.assertTrue(value['records'][0]['suspended_dates'])
        with self.assertRaises(ValueError):preview_archived_daily_dataset(f.source,f.cap,'sz.000001',f.start,f.end)
