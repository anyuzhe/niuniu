from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import unittest

import polars as pl

from quantlab.agent.retro_daily_cli import main as cli_main
from quantlab.data.retro_daily import (
    BASIC_FIELDS, CALENDAR_FIELDS, FIELDS, RetroDailyError, RetroDailyStore, normalize_symbol_rows, shard_of,
)


class Resp:
    def __init__(self, fields, rows, error_code='0', error_msg='success'):
        self.fields = list(fields); self.rows = [list(r) for r in rows]; self.i = -1
        self.error_code = error_code; self.error_msg = error_msg
    def next(self):
        self.i += 1; return self.i < len(self.rows)
    def get_row_data(self):
        return list(self.rows[self.i])


CALENDAR = [('2026-09-07', '1'), ('2026-09-08', '1'), ('2026-09-09', '1'), ('2026-09-10', '1'),
            ('2026-09-11', '1'), ('2026-09-12', '0'), ('2026-09-13', '0')]
BASIC = [('sh.600001', '甲', '2000-01-01', '', '1', '1'),
         ('sz.000002', '乙', '2026-09-09', '', '1', '1'),
         ('sz.300003', '丙', '2010-01-01', '2026-09-06', '1', '0'),
         ('sz.300004', '丁', '2010-01-01', '2026-09-08', '1', '0'),
         ('sh.000001', '上证指数', '1991-07-15', '', '2', '1'),
         ('bj.920001', '北交', '2024-01-02', '', '1', '1'),
         ('sh.600005', '戊', '2026-09-14', '', '1', '1')]


def bar(day, code, close, pre, tradestatus='1', st='0'):
    if tradestatus == '0':
        return (day, code, '', '', '', '', str(pre), '0', '', '3', '', '0', '', st)
    return (day, code, str(close), str(close), str(close), str(close), str(pre), '1000', str(1000 * close), '3',
            '1.5', tradestatus, str(round((close / pre - 1) * 100, 4)), st)


def default_bars():
    return {'sh.600001': [bar('2026-09-07', 'sh.600001', 10.0, 9.9), bar('2026-09-08', 'sh.600001', 11.0, 10.0),
                          bar('2026-09-09', 'sh.600001', 0, 11.0, tradestatus='0'),
                          bar('2026-09-10', 'sh.600001', 12.1, 11.0, st='1'), bar('2026-09-11', 'sh.600001', 12.0, 12.1)],
            'sz.000002': [bar('2026-09-09', 'sz.000002', 20.0, 10.0), bar('2026-09-10', 'sz.000002', 22.0, 20.0)]}


class FakeSDK:
    __version__ = '0.9.3'
    def __init__(self, basic=None, calendar=None, bars=None, errors=(), login_error=False):
        self.basic = BASIC if basic is None else basic; self.calendar = CALENDAR if calendar is None else calendar
        self.bars = default_bars() if bars is None else bars; self.errors = set(errors); self.login_error = login_error
        self.calls = []; self.logouts = 0
    def login(self):
        return Resp((), [], error_code='10001' if self.login_error else '0')
    def logout(self):
        self.logouts += 1
    def query_stock_basic(self):
        return Resp(BASIC_FIELDS, self.basic)
    def query_trade_dates(self, start_date, end_date):
        return Resp(CALENDAR_FIELDS, [r for r in self.calendar if start_date <= r[0] <= end_date])
    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        assert fields == ','.join(FIELDS) and frequency == 'd' and adjustflag == '3'
        self.calls.append(code)
        if code in self.errors:
            return Resp(FIELDS, [], error_code='10002007', error_msg='网络接收错误')
        return Resp(FIELDS, [r for r in self.bars.get(code, []) if start_date <= r[0] <= end_date])


class RetroDailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name)
        self.store = RetroDailyStore(self.output, now_fn=lambda: datetime(2026, 9, 16, 12, tzinfo=timezone.utc),
                                     today_fn=lambda: date(2026, 9, 16))
    def tearDown(self):
        self.tmp.cleanup()
    def plan(self, sdk=None):
        return self.store.create_plan('2026-09-07', '2026-09-13', sdk=sdk or FakeSDK())

    def test_plan_freezes_references_and_filters_symbols(self):
        plan = self.plan()
        self.assertTrue(plan['created']); self.assertEqual(plan['symbol_count'], 3); self.assertEqual(plan['trading_days'], 5)
        full = self.store.plan(plan['capture_id'], with_symbols=True)
        self.assertEqual(full['symbols'], ['sh.600001', 'sz.000002', 'sz.300004'])
        again = self.plan()
        self.assertFalse(again['created']); self.assertEqual(again['capture_id'], plan['capture_id'])
        self.assertEqual(self.store.trading_days(plan['capture_id']), [d for d, f in CALENDAR if f == '1'])
        self.assertEqual(len(self.store.reference(plan['capture_id'])['stock_basic']), len(BASIC))
        reference = self.output / '_market_data/retro_daily' / plan['capture_id'] / 'reference/stock_basic.json.gz'
        reference.write_bytes(b'tampered')
        with self.assertRaises(RetroDailyError) as ctx:
            self.store.reference(plan['capture_id'])
        self.assertEqual(ctx.exception.code, 'CORRUPT_ARCHIVE')

    def test_plan_fails_closed_on_provider_and_reference_problems(self):
        cases = [(FakeSDK(login_error=True), 'PROVIDER_ERROR'),
                 (FakeSDK(calendar=CALENDAR[:-1]), 'DATA_SCHEMA'),
                 (FakeSDK(basic=BASIC + [BASIC[0]]), 'DATA_SCHEMA'),
                 (FakeSDK(basic=[BASIC[4]]), 'NO_DATA')]
        for sdk, code in cases:
            with self.assertRaises(RetroDailyError) as ctx:
                self.store.create_plan('2026-09-07', '2026-09-13', sdk=sdk)
            self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(RetroDailyError):
            self.store.create_plan('2026-09-07', '2026-09-17', sdk=FakeSDK())
        self.assertEqual(self.store.list(), [])

    def test_fetch_is_resumable_and_status_reports_coverage(self):
        capture = self.plan()['capture_id']; sdk = FakeSDK()
        first = self.store.fetch(capture, max_symbols=1, sdk=sdk)
        self.assertEqual((first['attempted'], first['completed'], first['remaining_in_shard'], first['stopped_by']),
                         (1, 1, 2, 'max_symbols'))
        self.assertEqual(self.store.status(capture)['complete'], False)
        second = self.store.fetch(capture, sdk=sdk)
        self.assertEqual((second['completed'], second['empty'], second['remaining_in_shard']), (2, 1, 0))
        third = self.store.fetch(capture, sdk=sdk)
        self.assertEqual(third['attempted'], 0); self.assertEqual(sdk.calls, ['sh.600001', 'sz.000002', 'sz.300004'])
        status = self.store.status(capture, deep=True)
        self.assertTrue(status['complete']); self.assertEqual(status['rows'], 7); self.assertEqual(status['st_rows'], 1)
        self.assertEqual(status['tradable_rows'], 6); self.assertEqual((status['first_date'], status['last_date']), ('2026-09-07', '2026-09-11'))
        self.assertEqual(self.store.symbol_manifest(capture, 'sz.300004')['status'], 'EMPTY')

    def test_shards_partition_symbols(self):
        capture = self.plan()['capture_id']; symbols = self.store.plan(capture, with_symbols=True)['symbols']
        groups = [{s for s in symbols if shard_of(s, 3) == k} for k in range(3)]
        self.assertEqual(set().union(*groups), set(symbols)); self.assertEqual(sum(len(g) for g in groups), len(symbols))
        for k in range(3):
            self.store.fetch(capture, shard=k, shards=3, sdk=FakeSDK())
        self.assertTrue(self.store.status(capture)['complete'])
        with self.assertRaises(RetroDailyError):
            self.store.fetch(capture, shard=3, shards=3, sdk=FakeSDK())

    def test_fetch_cleans_interrupted_temporaries_of_its_own_shard_only(self):
        capture = self.plan()['capture_id']; base = self.output / '_market_data/retro_daily' / capture
        own = next(s for s in ('sh.600001', 'sz.000002', 'sz.300004') if shard_of(s, 2) == 0)
        other = next(s for s in ('sh.600001', 'sz.000002', 'sz.300004') if shard_of(s, 2) == 1)
        uid = '12345678-1234-1234-1234-123456789abc'
        own_tmp = base / 'symbols' / ('.tmp-' + own.replace('.', '_') + '-' + uid); own_tmp.mkdir(); (own_tmp / 'rows.json.gz').write_bytes(b'x')
        other_tmp = base / 'symbols' / ('.tmp-' + other.replace('.', '_') + '-' + uid); other_tmp.mkdir()
        own_failure_tmp = base / 'failures' / ('.' + own.replace('.', '_') + '.json-' + uid + '.tmp'); own_failure_tmp.write_text('{}')
        result = self.store.fetch(capture, shard=0, shards=2, sdk=FakeSDK())
        self.assertEqual(result['cleaned_temporaries'], 2)
        self.assertFalse(own_tmp.exists()); self.assertFalse(own_failure_tmp.exists()); self.assertTrue(other_tmp.exists())

    def test_invalid_rows_and_provider_errors_become_failure_records(self):
        capture = self.plan()['capture_id']
        bars = default_bars(); bars['sz.000002'] = [bar('2026-09-12', 'sz.000002', 20.0, 10.0)]
        result = self.store.fetch(capture, sdk=FakeSDK(bars=bars, errors={'sz.300004'}))
        self.assertEqual((result['completed'], result['failed']), (1, 2))
        status = self.store.status(capture)
        self.assertEqual(status['failure_count'], 2); self.assertEqual(status['pending_symbols'], 2)
        self.assertEqual({f['code'] for f in status['failures']}, {'DATA_SCHEMA', 'PROVIDER_ERROR'})
        self.assertFalse((self.output / '_market_data/retro_daily' / capture / 'symbols/sz_000002').exists())
        retry = self.store.fetch(capture, sdk=FakeSDK())
        self.assertEqual(retry['completed'], 2)
        status = self.store.status(capture)
        self.assertTrue(status['complete']); self.assertEqual(status['failure_count'], 0)

    def test_consecutive_failures_and_deadline_stop_fetch(self):
        capture = self.plan()['capture_id']
        failing = self.store.fetch(capture, sdk=FakeSDK(errors={'sh.600001', 'sz.000002', 'sz.300004'}))
        self.assertEqual(failing['failed'], 3)
        ticks = iter([0.0, 0.0, 5.0, 11.0, 20.0])
        timed = self.store.fetch(capture, max_seconds=10, sdk=FakeSDK(), clock=lambda: next(ticks))
        self.assertEqual((timed['attempted'], timed['stopped_by']), (2, 'deadline'))

    def test_read_panel_verifies_hashes_and_quarantine_allows_refetch(self):
        capture = self.plan()['capture_id']
        self.store.fetch(capture, max_symbols=1, sdk=FakeSDK())
        with self.assertRaises(RetroDailyError) as ctx:
            self.store.read_panel(capture)
        self.assertEqual(ctx.exception.code, 'INCOMPLETE_CAPTURE')
        self.store.fetch(capture, sdk=FakeSDK())
        panel, meta = self.store.read_panel(capture, start='2026-09-08')
        self.assertEqual(panel.height, 6); self.assertEqual(panel['date'].min(), date(2026, 9, 8))
        self.assertEqual(panel.schema['tradestatus'], pl.UInt8); self.assertEqual(meta['symbols_loaded'], 3)
        suspended = panel.filter((pl.col('code') == 'sh.600001') & (pl.col('date') == date(2026, 9, 9))).row(0, named=True)
        self.assertEqual((suspended['tradestatus'], suspended['close'], suspended['preclose']), (0, None, 11.0))
        parquet = self.output / '_market_data/retro_daily' / capture / 'symbols/sh_600001/daily.parquet'
        parquet.write_bytes(parquet.read_bytes() + b'x')
        with self.assertRaises(RetroDailyError):
            self.store.read_panel(capture)
        self.assertEqual(self.store.status(capture, deep=True)['corrupt_symbols'], ['sh.600001'])
        with self.assertRaises(RetroDailyError):
            self.store.quarantine_corrupt(capture)
        self.assertEqual(self.store.quarantine_corrupt(capture, confirmed=True)['quarantined'], ['sh.600001'])
        self.assertEqual(self.store.fetch(capture, sdk=FakeSDK())['completed'], 1)
        self.assertTrue(self.store.status(capture, deep=True)['complete'])

    def test_normalize_rejects_contract_violations(self):
        days = {d for d, f in CALENDAR if f == '1'}; start, end = date(2026, 9, 7), date(2026, 9, 13)
        good = bar('2026-09-07', 'sh.600001', 10.0, 9.9)
        self.assertEqual(len(normalize_symbol_rows([good], 'sh.600001', start, end, days)), 1)
        bad_rows = [
            [bar('2026-09-07', 'sh.600002', 10.0, 9.9)],
            [good[:9] + ('2',) + good[10:]],
            [bar('2026-09-08', 'sh.600001', 10.0, 9.9), good],
            [good[:3] + ('9.0',) + good[4:]],
            [good[:11] + ('2',) + good[12:]],
            [good[:-1]],
            [bar('2026-09-06', 'sh.600001', 10.0, 9.9)],
        ]
        for rows in bad_rows:
            with self.assertRaises(RetroDailyError):
                normalize_symbol_rows(rows, 'sh.600001', start, end, days)

    def test_cli_reports_json_results(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(cli_main(['--output', str(self.output), '--call', 'list']), 0)
        self.assertEqual(json.loads(stream.getvalue()), {'ok': True, 'data': {'captures': []}})
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = cli_main(['--output', str(self.output), '--call', 'fetch', '--capture-id',
                             '00000000-0000-0000-0000-000000000000', '--shard', 'x'])
        self.assertEqual(code, 2); self.assertFalse(json.loads(stream.getvalue())['ok'])


if __name__ == '__main__':
    unittest.main()
