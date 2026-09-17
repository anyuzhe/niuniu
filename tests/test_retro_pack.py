from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import unittest

from limit_research_fixtures import CAL, FakeSDK
from quantlab.agent.retro_daily_cli import main as cli_main
from quantlab.data.retro_daily import RetroDailyError, RetroDailyStore
from quantlab.trading.limit_events import LimitEventLibrary
from quantlab.trading.market_sentiment import MarketSentimentLibrary

CLOCK = lambda: datetime(2026, 12, 1, tzinfo=timezone.utc)


class RetroPackTests(unittest.TestCase):
    def store(self, output):
        return RetroDailyStore(output, now_fn=CLOCK, today_fn=lambda: CAL[-1] + timedelta(days=30))

    def code(self, call, *args, **kwargs):
        with self.assertRaises(RetroDailyError) as caught:
            call(*args, **kwargs)
        return caught.exception.code

    def test_packs_keep_bytes_identity_and_builds_then_remove_originals(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp)
            store = self.store(output)
            capture = store.create_plan(CAL[0], CAL[-1], sdk=FakeSDK())['capture_id']
            self.assertEqual(self.code(store.consolidate, capture, confirmed=True), 'INCOMPLETE_CAPTURE')
            store.fetch(capture, sdk=FakeSDK())
            events = LimitEventLibrary(output, now_fn=CLOCK).build([capture])
            sentiment = MarketSentimentLibrary(output, now_fn=CLOCK).build([capture])
            panel, meta = store.read_panel(capture)
            window, window_meta = store.read_panel(capture, symbols=['sz.300001', 'sh.600001'], start=CAL[5], end=CAL[20])
            evidence = store.panel_evidence(capture)
            self.assertEqual(self.code(store.consolidate, capture), 'CONFIRMATION_REQUIRED')
            ticks = iter(range(1000))
            partial = store.consolidate(capture, confirmed=True, max_seconds=1, clock=lambda: next(ticks) * 0.6)
            self.assertEqual((partial['state'], partial['parts_written'], partial['stopped_by']), ('IN_PROGRESS', 1, 'deadline'))
            self.assertIsNone(store.pack_index(capture))  # readers keep using the per-symbol files until the index is published
            done = store.consolidate(capture, confirmed=True)
            self.assertEqual((done['state'], done['packed'], done['manifest_digest'], done['remaining_symbol_dirs']),
                             ('COMPLETE', True, evidence['manifest_digest'], 6))
            fresh = self.store(output)
            for reader in (fresh, store):
                again, again_meta = reader.read_panel(capture)
                self.assertTrue(again.equals(panel)); self.assertEqual(again_meta, meta)
                part, part_meta = reader.read_panel(capture, symbols=['sz.300001', 'sh.600001'], start=CAL[5], end=CAL[20])
                self.assertTrue(part.equals(window)); self.assertEqual(part_meta, window_meta)
            self.assertEqual(fresh.panel_evidence(capture), evidence)
            self.assertTrue(fresh.status(capture, deep=True)['complete'])
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = cli_main(['--output', str(output), '--call', 'consolidate', '--capture-id', capture, '--confirm', '--remove-originals'])
            removed = json.loads(stream.getvalue())['data']
            self.assertEqual((code, removed['state'], removed['removed_symbol_dirs'], removed['remaining_symbol_dirs']), (0, 'COMPLETE', 6, 0))
            self.assertEqual(list((output / '_market_data' / 'retro_daily' / capture / 'symbols').iterdir()), [])
            after, after_meta = self.store(output).read_panel(capture)
            self.assertTrue(after.equals(panel)); self.assertEqual(after_meta, meta)
            rebuilt_events = LimitEventLibrary(output, now_fn=CLOCK).build([capture])
            rebuilt_sentiment = MarketSentimentLibrary(output, now_fn=CLOCK).build([capture])
            self.assertEqual((rebuilt_events['build_id'], rebuilt_events['created']), (events['build_id'], False))  # identical inputs
            self.assertEqual((rebuilt_sentiment['build_id'], rebuilt_sentiment['created']), (sentiment['build_id'], False))
            self.assertEqual(self.store(output).fetch(capture, sdk=FakeSDK())['stopped_by'], 'packed')
            self.assertEqual(self.code(self.store(output).quarantine_corrupt, capture, confirmed=True), 'CAPTURE_PACKED')
            pack = next(p for p in sorted((output / '_market_data' / 'retro_daily' / capture / 'packs').glob('daily-*.pack')) if p.stat().st_size)
            data = bytearray(pack.read_bytes()); data[len(data) // 2] ^= 0xFF; pack.write_bytes(bytes(data))
            self.assertEqual(self.code(self.store(output).read_panel, capture), 'CORRUPT_ARCHIVE')


if __name__ == '__main__':
    unittest.main()
