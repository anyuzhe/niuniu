from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import io
import json
import unittest

from limit_research_fixtures import BASIC, CAL, CAL_ROWS, FakeSDK, Resp, T
from quantlab.agent.limit_events_cli import main as events_cli
from quantlab.agent.retro_daily_cli import main as retro_cli
from quantlab.data.baostock_catalog import DAILY_FIELDS
from quantlab.data.daily_market_archive import DailyMarketArchive
from quantlab.data.forward_daily import ForwardDailyError, ForwardReferenceArchive, resolve_forward
from quantlab.data.retro_daily import FIELDS, RetroDailyStore
from quantlab.trading.limit_events import LimitEventError, LimitEventLibrary, split_inputs
from quantlab.trading.market_sentiment import MarketSentimentLibrary

TZ = ZoneInfo('Asia/Shanghai')
DAILY = DAILY_FIELDS.split(',')


class FakeDailySDK(FakeSDK):
    """Adds the per-date full-market query and an optional extra security or calendar change."""
    def __init__(self, extra_code=None, calendar_rows=None):
        super().__init__(); self.extra_code = extra_code; self.calendar_rows = calendar_rows
    def query_trade_dates(self, start_date, end_date):
        rows = self.calendar_rows if self.calendar_rows is not None else CAL_ROWS
        return Resp(('calendar_date', 'is_trading_day'), [r for r in rows if start_date <= r[0] <= end_date])
    def query_daily_history_k_AStock(self, date):
        out = []
        for code, rows in sorted(self.b.items()):
            for values in rows:
                if values[0] == date:
                    record = dict(zip(FIELDS, values))
                    out.append([record.get(name, '') for name in DAILY])
        if self.extra_code:
            record = dict(zip(FIELDS, (date, self.extra_code, '8', '8.2', '7.9', '8.1', '8', '100', '810', '3', '1', '1', '1.25', '0')))
            out.append([record.get(name, '') for name in DAILY])
        return Resp(DAILY, out)


def local(i, hh=18, mm=10):
    return datetime.combine(T(i), datetime.min.time(), TZ).replace(hour=hh, minute=mm)


class ForwardDailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name)
        self.clock = [datetime(2026, 12, 1, tzinfo=timezone.utc)]
        now = lambda: self.clock[0]
        self.store = RetroDailyStore(self.output, now_fn=now, today_fn=lambda: date(2026, 12, 31))
        self.events = LimitEventLibrary(self.output, now_fn=now); self.sentiment = MarketSentimentLibrary(self.output, now_fn=now)
    def tearDown(self):
        self.tmp.cleanup()
    def retro(self, first, last):
        plan = self.store.create_plan(T(first), T(last), sdk=FakeSDK()); self.store.fetch(plan['capture_id'], sdk=FakeSDK())
        return plan['capture_id']
    def daily(self, days, sdk=None):
        archive = DailyMarketArchive(self.output, now_fn=lambda: self.clock[0])
        for i in days:
            self.clock[0] = local(i, 19, 0); archive.capture(T(i), sdk=sdk or FakeDailySDK())
    def reference(self, i, sdk=None):
        self.clock[0] = local(i, 18, 5)
        return ForwardReferenceArchive(self.output, now_fn=lambda: self.clock[0]).capture(sdk=sdk or FakeDailySDK())

    def test_forward_extension_equals_single_retro_capture(self):
        full = self.retro(1, 40)
        whole_events = self.events.build([full]); whole_sentiment = self.sentiment.build([full])
        base = self.retro(1, 30)
        self.daily(range(31, 41)); reference = self.reference(40)
        self.assertTrue(reference['created']); self.assertEqual(reference['as_of'], T(40).isoformat())
        self.assertFalse(self.reference(40)['created'])
        extended = self.events.build([base], forward_through=T(40).isoformat())
        a, _ = self.events.read_events(whole_events['build_id']); b, manifest = self.events.read_events(extended['build_id'])
        self.assertTrue(a.equals(b)); self.assertEqual(whole_events['stats'], extended['stats'])
        forward = manifest['inputs'][-1]
        self.assertEqual((forward['first_day'], forward['last_day'], len(forward['days']), forward['excluded_codes']),
                         (T(31).isoformat(), T(40).isoformat(), 10, []))
        self.assertEqual(split_inputs(manifest['inputs']), ([base], T(40).isoformat()))
        self.assertEqual(self.events.verify(extended['build_id'])['reason'], 'RECOMPUTED_IDENTICAL')
        daily_whole, _ = self.sentiment.read(whole_sentiment['build_id'])
        extended_sentiment = self.sentiment.build([base], forward_through=T(40).isoformat())
        daily_extended, _ = self.sentiment.read(extended_sentiment['build_id'])
        self.assertTrue(daily_whole.equals(daily_extended))
        self.assertEqual(self.sentiment.verify(extended_sentiment['build_id'])['verified'], True)
        partial = self.events.build([base], forward_through=T(35).isoformat())
        self.assertEqual(partial['calendar']['last'], T(35).isoformat())
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(events_cli(['--output', str(self.output), '--call', 'build', '--capture-ids', base, '--forward-through', T(40).isoformat()]), 0)
        self.assertEqual(json.loads(stream.getvalue())['data']['build_id'], extended['build_id'])

    def test_gaps_references_and_unknown_codes_fail_closed(self):
        base = self.retro(1, 30)
        with self.assertRaises(LimitEventError) as ctx:
            self.events.build([base], forward_through=T(33).isoformat())
        self.assertEqual(ctx.exception.code, 'REFERENCE_NOT_FOUND')
        self.reference(32)
        with self.assertRaises(LimitEventError) as ctx:
            self.events.build([base], forward_through=T(33).isoformat())
        self.assertEqual(ctx.exception.code, 'REFERENCE_NOT_FOUND')  # 参考快照早于前瞻终点，不认识之后的新股
        self.reference(33)
        self.daily([31, 33])
        with self.assertRaises(LimitEventError) as ctx:
            self.events.build([base], forward_through=T(33).isoformat())
        self.assertEqual(ctx.exception.code, 'FORWARD_GAP'); self.assertIn(T(32).isoformat(), str(ctx.exception))
        with self.assertRaises(LimitEventError) as ctx:
            self.events.build([base], forward_through=T(30).isoformat())
        self.assertEqual(ctx.exception.code, 'FORWARD_RANGE')
        self.daily([32], sdk=FakeDailySDK(extra_code='sz.000999'))
        forward = resolve_forward(self.output, CAL[:30], T(33))
        self.assertEqual(forward['evidence']['excluded_codes'], ['sz.000999'])
        self.assertNotIn('sz.000999', forward['symbols'])
        shifted = [(d, '0' if d == T(12).isoformat() else f) for d, f in CAL_ROWS]
        self.reference(34, sdk=FakeDailySDK(calendar_rows=shifted))
        self.daily([34])
        with self.assertRaises(ForwardDailyError) as ctx:
            resolve_forward(self.output, CAL[:30], T(34))
        self.assertEqual(ctx.exception.code, 'CALENDAR_MISMATCH')

    def test_reference_archive_validation_and_cli(self):
        broken = [r for r in CAL_ROWS if r[0] != T(20).isoformat()]
        with self.assertRaises(ForwardDailyError):
            self.reference(30, sdk=FakeDailySDK(calendar_rows=broken))
        snapshot = self.reference(30)
        archive = ForwardReferenceArchive(self.output)
        self.assertEqual(archive.latest_covering(T(30))['snapshot_id'], snapshot['snapshot_id'])
        loaded = archive.load(snapshot['snapshot_id'])
        self.assertEqual(len(loaded['stock_basic']), len(BASIC)); self.assertEqual(loaded['trade_calendar'][-1][0], T(30).isoformat())
        path = self.output / '_market_data' / 'forward_reference' / snapshot['snapshot_id'] / 'stock_basic.json.gz'
        path.write_bytes(path.read_bytes() + b'x')
        with self.assertRaises(ForwardDailyError) as ctx:
            archive.load(snapshot['snapshot_id'])
        self.assertEqual(ctx.exception.code, 'CORRUPT_ARCHIVE')
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(retro_cli(['--output', str(self.output), '--call', 'forward-references']), 0)
        self.assertEqual(json.loads(stream.getvalue())['data']['snapshots'][0]['snapshot_id'], snapshot['snapshot_id'])


if __name__ == '__main__':
    unittest.main()
