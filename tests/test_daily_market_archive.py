from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from quantlab.data.daily_market_archive import DailyMarketArchive,DailyMarketArchiveError,EXPECTED_FIELDS


class Response:
    error_code='0';error_msg='success'
    def __init__(self,rows,fields=EXPECTED_FIELDS):
        self.fields=list(fields);self.rows=rows;self.index=-1
    def next(self):self.index+=1;return self.index<len(self.rows)
    def get_row_data(self):return [self.rows[self.index][k] for k in self.fields]


def market_row(day,code,close='10.50'):
    row={key:'1' for key in EXPECTED_FIELDS}
    row.update(date=day,code=code,open='10.00',high='11.00',low='9.50',close=close,
        preclose='10.00',volume='1000',amount='10000',adjustflag='3',turn='2.0',
        tradestatus='1',pctChg='5.0',peTTM='12',pbMRQ='1.2',psTTM='2.3',pcfNcfTTM='3.4',isST='0')
    return row


class SDK:
    __version__='0.9.3'
    def __init__(self,rows,fields=EXPECTED_FIELDS):self.rows=rows;self.fields=fields;self.logouts=0
    def login(self):return Response([{'ok':'1'}],['ok'])
    def logout(self):self.logouts+=1
    def query_daily_history_k_AStock(self,date=''):return Response(self.rows,self.fields)


class DailyMarketArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.output=self.root/'artifacts';self.output.mkdir()
        self.now=lambda:datetime(2026,9,14,10,tzinfo=timezone.utc)
        self.store=DailyMarketArchive(self.output,now_fn=self.now)
        self.day='2026-09-11'
        self.rows=[market_row(self.day,'sh.600000'),market_row(self.day,'sz.000001','11.00')]

    def test_first_capture_is_accepted_and_same_content_is_idempotent(self):
        sdk=SDK(self.rows);first=self.store.capture(self.day,sdk=sdk)
        self.assertTrue(first['created']);self.assertFalse(first['revision_detected'])
        second=self.store.capture(self.day,sdk=SDK(self.rows))
        self.assertFalse(second['created']);self.assertEqual(first['snapshot_id'],second['snapshot_id'])
        frame,manifest=self.store.read_frame(self.day)
        self.assertEqual(frame.height,2);self.assertEqual(manifest['rows'],2)
        self.assertEqual(self.store.overview()['accepted_days'],1)
        folders=[p for p in self.store.day_root(self.day).iterdir() if p.is_dir()]
        self.assertEqual(len(folders),1);self.assertEqual(sdk.logouts,1)

    def test_revision_is_saved_but_does_not_replace_without_confirmation(self):
        first=self.store.capture(self.day,sdk=SDK(self.rows))
        changed=[dict(row) for row in self.rows];changed[0]['close']='10.60'
        revision=self.store.capture(self.day,sdk=SDK(changed))
        self.assertTrue(revision['revision_detected']);self.assertEqual(revision['revision_of'],first['snapshot_id'])
        self.assertEqual(self.store.accepted(self.day)['snapshot_id'],first['snapshot_id'])
        with self.assertRaises(DailyMarketArchiveError):self.store.accept_revision(self.day,revision['snapshot_id'])
        accepted=self.store.accept_revision(self.day,revision['snapshot_id'],confirmed=True)
        self.assertTrue(accepted['changed']);self.assertEqual(self.store.accepted(self.day)['snapshot_id'],revision['snapshot_id'])
        self.assertEqual(self.store.list_days(limit=10)[0]['revision_candidates'],0)

    def test_tamper_and_schema_change_fail_closed(self):
        saved=self.store.capture(self.day,sdk=SDK(self.rows))
        raw=self.store._snapshot_root(self.day,saved['snapshot_id'])/'raw.json'
        raw.write_text(raw.read_text()+' ')
        with self.assertRaises(DailyMarketArchiveError) as corrupt:self.store.accepted(self.day)
        self.assertEqual(corrupt.exception.code,'CORRUPT_ARCHIVE')
        other=DailyMarketArchive(self.root/'other' if False else self.output)

    def test_provider_field_change_is_rejected_and_logout_still_runs(self):
        fields=tuple(EXPECTED_FIELDS[:-1]);rows=[{k:v for k,v in self.rows[0].items() if k in fields}]
        sdk=SDK(rows,fields)
        with self.assertRaises(DailyMarketArchiveError) as error:self.store.capture(self.day,sdk=sdk)
        self.assertEqual(error.exception.code,'DATA_SCHEMA');self.assertEqual(sdk.logouts,1)

    def test_non_trading_rows_can_preserve_status_without_inventing_prices(self):
        row=market_row(self.day,'sh.600000');row.update(tradestatus='0',open='',high='',low='',close='',volume='')
        saved=self.store.capture(self.day,sdk=SDK([row]));frame,_=self.store.read_frame(self.day)
        self.assertEqual(saved['rows'],1);self.assertEqual(frame['tradestatus'][0],'0')
        self.assertIsNone(frame['close'][0])


if __name__=='__main__':unittest.main()
