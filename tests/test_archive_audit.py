import unittest
from dataclasses import replace
from datetime import date,timedelta
import polars as pl
import test_core
from quantlab.data.archive import BarArchive
from quantlab.data.audit import audit_market
from quantlab.domain import Timeframe


class ArchiveAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.calendar=self.fixture.root/'lake/bronze/provider=baostock/trade_calendar/calendar.parquet'
        self.calendar.parent.mkdir()
        pl.DataFrame({'calendar_date':['2025-01-01','2025-01-02','2025-01-03'],'is_trading_day':['1','1','1']}).write_parquet(self.calendar)

    def test_fixed_archive_reports_missing_session_and_slot(self):
        request=replace(self.fixture.request,timeframe=Timeframe.MIN5,end=date(2025,1,3))
        bars=self.fixture.provider.load(request).bars
        # One actual slot per day; remove the middle session completely.
        bars=bars.filter(pl.col('datetime').dt.day()!=2)
        version=BarArchive(self.fixture.root/'versions').publish(bars,{'adjustment':'raw','source':'fixture'},observed_at=bars['datetime'].max()+timedelta(days=1))
        audit=audit_market(self.fixture.root,request,version['manifest'])
        self.assertEqual(audit['expected_symbol_sessions'],15)
        self.assertEqual(audit['complete_symbol_sessions'],0)
        first=audit['results'][0]
        self.assertEqual(first['session_coverage'][0]['observed_slots'],1)
        self.assertEqual(len(first['session_coverage'][0]['missing_slots']),47)
        self.assertNotIn('09:35',first['session_coverage'][0]['missing_slots'])
        self.assertEqual(first['session_coverage'][1]['status'],'missing')
        self.assertEqual(first['unexplained_calendar_gaps'],[date(2025,1,2)])
        self.assertEqual(audit['files'][0]['version_id'],version['version_id'])
        # Missing requested range is an audit result rather than a provider load error.
        empty=audit_market(self.fixture.root,replace(request,start=date(2025,1,2),end=date(2025,1,2)),version['manifest'])
        self.assertTrue(all(r['status']=='no_data' for r in empty['results']))

    def test_calendar_hole_is_unknown_not_nontrading_or_pass(self):
        complete_calendar=self.fixture.root/'complete-calendar.parquet'
        pl.read_parquet(self.calendar).write_parquet(complete_calendar)
        pl.read_parquet(self.calendar).filter(pl.col('calendar_date')!='2025-01-02').write_parquet(self.calendar)
        request=replace(self.fixture.request,end=date(2025,1,3))
        audit=audit_market(self.fixture.root,request)
        self.assertEqual(audit['calendar_missing_dates'],[date(2025,1,2)])
        self.assertEqual(audit['status'],'issues')
        self.assertEqual(audit['results'][0]['nontrading_dates'],[])
        self.assertEqual(audit['results'][0]['unknown_calendar_dates'],[date(2025,1,2)])
        self.assertEqual(audit['results'][0]['status'],'issues')
        repaired=audit_market(self.fixture.root,request,calendar_file=complete_calendar)
        self.assertEqual(repaired['status'],'checked')
        self.assertEqual(repaired['expected_symbol_sessions'],15)
        self.assertEqual(repaired['complete_symbol_sessions'],15)
        self.assertNotEqual(audit['calendar_sha256'],repaired['calendar_sha256'])

    def test_duplicate_calendar_dates_rejected(self):
        calendar=pl.read_parquet(self.calendar)
        pl.concat([calendar,calendar.head(1)]).write_parquet(self.calendar)
        with self.assertRaisesRegex(ValueError,'unique dates'):
            audit_market(self.fixture.root,self.fixture.request)
