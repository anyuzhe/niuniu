from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import unittest

import polars as pl

from limit_research_fixtures import CAL, FakeSDK, T
from quantlab.agent.limit_events_cli import main as cli_main
from quantlab.data.retro_daily import RetroDailyStore
from quantlab.trading.limit_events import LABEL_COLUMNS, LimitEventError, LimitEventLibrary
from quantlab.trading.price_limit_regime import limit_prices


class LimitEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name)
        clock = lambda: datetime(2026, 12, 1, tzinfo=timezone.utc)
        self.store = RetroDailyStore(self.output, now_fn=clock, today_fn=lambda: date(2026, 12, 31))
        self.library = LimitEventLibrary(self.output, now_fn=clock)
    def tearDown(self):
        self.tmp.cleanup()
    def capture(self, start=None, end=None, sdk=None):
        plan = self.store.create_plan(start or CAL[0], end or CAL[-1], sdk=sdk or FakeSDK())
        self.store.fetch(plan['capture_id'], sdk=sdk or FakeSDK())
        return plan['capture_id']
    def event(self, frame, code, i):
        rows = frame.filter((pl.col('code') == code) & (pl.col('date') == T(i))).to_dicts()
        self.assertEqual(len(rows), 1, (code, i)); return rows[0]

    def test_events_features_and_labels(self):
        build = self.library.build([self.capture()])
        self.assertTrue(build['created'])
        events, manifest = self.library.read_events(build['build_id'])
        keys = sorted((r['code'], r['date']) for r in events.select('code', 'date').to_dicts())
        expected = sorted([('sh.600001', T(i)) for i in (26, 27, 28, 29)] + [('sz.300001', T(10)), ('sz.300001', T(12))] +
                          [('sh.688001', T(10)), ('sh.688001', T(11))] + [('sh.600003', T(15))])
        self.assertEqual(keys, expected)
        first = self.event(events, 'sh.600001', 26)
        self.assertTrue(first['is_first_board'] and first['is_limit_up_close']); self.assertEqual(first['limit_up_streak'], 1)
        self.assertAlmostEqual(first['t1_open_ret'], 0.10, places=9); self.assertTrue(first['t1_open_at_limit_up'])
        self.assertTrue(first['t1_is_limit_up_close']); self.assertEqual(first['t1_limit_up_streak'], 2)
        self.assertAlmostEqual(first['ret_t1open_to_t2open'], 12.2 / 12.1 - 1, places=9)
        self.assertAlmostEqual(first['ret_close_to_t2close'], 12.5 / 11.0 - 1, places=9)
        word = self.event(events, 'sh.600001', 27)
        self.assertTrue(word['is_one_word_limit_up'] and word['prev_is_limit_up_close']); self.assertAlmostEqual(word['ret_5d'], 0.21, places=9)
        broken = self.event(events, 'sh.600001', 28)
        self.assertTrue(broken['is_broken_board']); self.assertFalse(broken['is_limit_up_close']); self.assertEqual(broken['limit_up_streak'], 0)
        after_broken = self.event(events, 'sh.600001', 29)
        self.assertTrue(after_broken['prev_is_broken_board']); self.assertFalse(after_broken['touched_limit_up'])
        chinext = self.event(events, 'sz.300001', 10)
        self.assertEqual(chinext['limit_rate'], 0.20); self.assertFalse(chinext['t1_tradable'])
        self.assertIsNone(chinext['t1_open_ret']); self.assertIsNone(chinext['ret_close_to_t2close'])
        star = self.event(events, 'sh.688001', 10)
        self.assertEqual(star['sessions_since_listing'], 6); self.assertEqual(star['limit_up_price'], limit_prices(28.0, 0.20)[0])
        down = self.event(events, 'sh.600003', 15)
        self.assertTrue(down['is_limit_down_close'] and down['touched_limit_down'])
        stats = manifest['stats']
        self.assertEqual(stats['violation_rows'], 1); self.assertEqual(stats['limit_up_close'], 4)
        self.assertEqual(stats['rule_counts']['NO_LIMIT:IPO_NO_LIMIT_WINDOW'], 5)
        self.assertGreater(stats['rule_counts']['UNMODELED:NEAR_DELISTING_UNMODELED'], 0)
        self.assertEqual(manifest['label_columns'], list(LABEL_COLUMNS))
        self.assertTrue(set(LABEL_COLUMNS).isdisjoint(manifest['feature_columns']))

    def test_idempotent_build_verify_and_tamper_detection(self):
        capture = self.capture()
        build = self.library.build([capture]); again = self.library.build([capture])
        self.assertFalse(again['created']); self.assertEqual(again['build_id'], build['build_id'])
        self.assertEqual(self.library.verify(build['build_id'])['verified'], True)
        self.assertEqual(self.library.list()[0]['events'], build['stats']['events'])
        summary = self.library.summary(build['build_id'])
        self.assertEqual(summary['by_year'][0]['year'], 2026)
        folder = self.output / '_limit_research/limit_events' / build['build_id']
        (folder / 'events.parquet').write_bytes((folder / 'events.parquet').read_bytes() + b'x')
        with self.assertRaises(LimitEventError):
            self.library.read_events(build['build_id'])
        manifest = json.loads((folder / 'manifest.json').read_text()); manifest['stats']['events'] = 0
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(LimitEventError):
            self.library.get(build['build_id'])

    def test_contiguous_captures_match_single_capture(self):
        single = self.library.build([self.capture()])
        middle = date(2026, 8, 31)
        left = self.capture(end=middle); right = self.capture(start=middle + timedelta(days=1))
        split = self.library.build([right, left])
        a, _ = self.library.read_events(single['build_id']); b, _ = self.library.read_events(split['build_id'])
        self.assertNotEqual(single['build_id'], split['build_id'])
        self.assertTrue(a.equals(b)); self.assertEqual(single['stats'], split['stats'])

    def test_batched_build_equals_in_memory_build(self):
        capture = self.capture()
        batched = LimitEventLibrary(self.output, now_fn=lambda: datetime(2026, 12, 2, tzinfo=timezone.utc), batch_symbols=2).build([capture])
        from quantlab.trading.limit_events import build_event_frame, load_inputs
        panel, calendar, reference, _inputs = load_inputs(self.store, [capture])
        events, stats = build_event_frame(panel, calendar, reference)
        stored, manifest = LimitEventLibrary(self.output).read_events(batched['build_id'])
        self.assertTrue(stored.equals(events)); self.assertEqual(manifest['stats'], stats)

    def test_inputs_must_be_complete_and_contiguous(self):
        left = self.capture(end=date(2026, 8, 20)); right = self.capture(start=date(2026, 8, 24))
        with self.assertRaises(LimitEventError) as ctx:
            self.library.build([left, right])
        self.assertEqual(ctx.exception.code, 'NON_CONTIGUOUS_INPUTS')
        plan = self.store.create_plan(date(2026, 8, 3), date(2026, 9, 1), sdk=FakeSDK())
        self.store.fetch(plan['capture_id'], max_symbols=2, sdk=FakeSDK())
        with self.assertRaises(LimitEventError) as ctx:
            self.library.build([plan['capture_id']])
        self.assertEqual(ctx.exception.code, 'INCOMPLETE_CAPTURE')
        with self.assertRaises(LimitEventError):
            self.library.build([])

    def test_cli_build_and_summary(self):
        capture = self.capture()
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(cli_main(['--output', str(self.output), '--call', 'build', '--capture-ids', capture]), 0)
        build_id = json.loads(stream.getvalue())['data']['build_id']
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(cli_main(['--output', str(self.output), '--call', 'summary', '--build-id', build_id]), 0)
        self.assertIn('limit_up_close_by_streak', json.loads(stream.getvalue())['data'])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main(['--output', str(self.output), '--call', 'get']), 2)


if __name__ == '__main__':
    unittest.main()
