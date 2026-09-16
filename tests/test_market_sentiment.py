from contextlib import redirect_stdout
from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import polars as pl

from limit_research_fixtures import CAL, FakeSDK
from quantlab.agent.market_sentiment_cli import main as cli_main
from quantlab.data.retro_daily import SCHEMA, RetroDailyStore
from quantlab.trading.limit_events import prepare_states
from quantlab.trading.market_sentiment import METRICS, MarketSentimentError, MarketSentimentLibrary, daily_metrics

D = [date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1), date(2026, 7, 2)]
REFERENCE = [(c, c, '2000-01-01', '', '1', '1') for c in ('sh.600001', 'sh.600002', 'sz.000003', 'sz.300004', 'sh.600005', 'sh.600007')]


def rows_for(code, path, st=False):
    out, pre = [], None
    for day, spec in zip(D, path):
        if spec == 'S':
            out.append({'date': day, 'code': code, 'open': pre, 'high': pre, 'low': pre, 'close': pre, 'preclose': pre,
                        'volume': 0.0, 'amount': None, 'adjustflag': '3', 'turn': None, 'tradestatus': 0, 'pctChg': 0.0, 'isST': int(st)})
            continue
        base, o, h, l, c = spec
        pre = base if base is not None else pre
        out.append({'date': day, 'code': code, 'open': o, 'high': h, 'low': l, 'close': c, 'preclose': pre, 'volume': 1000.0,
                    'amount': 1000.0 * c, 'adjustflag': '3', 'turn': 1.0, 'tradestatus': 1, 'pctChg': 0.0, 'isST': int(st)})
        pre = c
    return out


def panel():
    rows = []
    rows += rows_for('sh.600001', [(10.0, 10.0, 10.0, 10.0, 10.0), (None, 10.5, 11.0, 10.4, 11.0), (None, 11.5, 12.1, 11.4, 12.1), (None, 12.0, 12.3, 11.9, 12.0)])
    rows += rows_for('sh.600002', [(10.0, 10.0, 10.0, 10.0, 10.0), (None, 10.5, 11.0, 10.4, 11.0), (None, 11.5, 12.1, 11.4, 11.8), (None, 11.0, 11.2, 10.62, 10.62)])
    rows += rows_for('sz.000003', [(10.0, 10.0, 10.0, 10.0, 10.0), (None, 10.0, 10.0, 10.0, 10.0), (None, 10.5, 11.0, 10.4, 11.0), (None, 12.1, 12.1, 12.1, 12.1)])
    rows += rows_for('sz.300004', [(10.0, 10.0, 10.0, 10.0, 10.0), (None, 10.5, 12.0, 10.4, 12.0), 'S', (None, 11.8, 12.0, 11.3, 11.4)])
    rows += rows_for('sh.600005', [(10.0, 10.0, 10.0, 10.0, 10.0), (None, 10.0, 10.0, 10.0, 10.0), (None, 10.2, 10.5, 10.1, 10.5), (None, 10.5, 10.5, 10.5, 10.5)], st=True)
    rows += rows_for('sh.600007', [(10.0, 10.0, 10.0, 10.0, 10.0), (None, 10.0, 10.0, 10.0, 10.0), (None, 10.5, 11.0, 10.4, 11.0), (None, 10.8, 10.9, 10.3, 10.4)])
    return pl.DataFrame(rows, schema=SCHEMA)


class DailyMetricTests(unittest.TestCase):
    def setUp(self):
        states = prepare_states(panel(), D, REFERENCE)
        self.daily = {r['date']: r for r in daily_metrics(states, D).to_dicts()}

    def test_day_three_counts_and_advance_rates(self):
        d3 = self.daily[D[2]]
        self.assertEqual((d3['tradable_count'], d3['suspended_count']), (5, 1))
        self.assertEqual((d3['limit_up_count'], d3['limit_up_count_non_st']), (4, 3))
        self.assertEqual((d3['touched_limit_up_count'], d3['broken_board_count']), (5, 1))
        self.assertAlmostEqual(d3['broken_rate'], 0.2)
        self.assertEqual((d3['first_board_count'], d3['consecutive_board_count'], d3['max_streak'], d3['streak_2_count']), (3, 1, 2, 1))
        self.assertEqual(d3['prev_first_board_count'], 2); self.assertAlmostEqual(d3['advance_rate_1to2'], 0.5)
        self.assertEqual(d3['prev_limit_up_count'], 2)
        self.assertAlmostEqual(d3['prev_limit_up_avg_return'], (0.1 + (11.8 / 11.0 - 1)) / 2, places=9)
        self.assertEqual(d3['prev_limit_up_win_rate'], 1.0)
        self.assertEqual((d3['up_count'], d3['down_count'], d3['flat_count']), (5, 0, 0))
        self.assertIsNone(d3['high_board_broken']); self.assertEqual(d3['high_board_height_prev'], 1)

    def test_day_four_losses_high_board_and_suspension_exclusion(self):
        d4 = self.daily[D[3]]
        self.assertEqual((d4['limit_up_count'], d4['one_word_limit_up_count'], d4['limit_down_count']), (1, 1, 1))
        self.assertEqual(d4['prev_first_board_count'], 3); self.assertAlmostEqual(d4['advance_rate_1to2'], 1 / 3)
        self.assertEqual(d4['prev_consecutive_count'], 1); self.assertEqual(d4['advance_rate_2plus'], 0.0)
        self.assertEqual(d4['prev_limit_up_count'], 4)
        expected = [12.0 / 12.1 - 1, 0.1, 0.0, 10.4 / 11.0 - 1]
        self.assertAlmostEqual(d4['prev_limit_up_avg_return'], sum(expected) / 4, places=9)
        self.assertAlmostEqual(d4['prev_limit_up_win_rate'], 0.25)
        self.assertEqual(d4['prev_broken_count'], 1); self.assertAlmostEqual(d4['prev_broken_avg_return'], 10.62 / 11.8 - 1, places=9)
        self.assertEqual(d4['big_loss_count'], 1)
        self.assertEqual(d4['high_board_height_prev'], 2); self.assertTrue(d4['high_board_broken'])
        self.assertEqual(d4['tradable_count'], 6)

    def test_first_day_has_no_previous_day_metrics_and_amount_change(self):
        d1, d2 = self.daily[D[0]], self.daily[D[1]]
        self.assertEqual(d1['prev_limit_up_count'], 0); self.assertIsNone(d1['advance_rate_1to2']); self.assertIsNone(d1['amount_change'])
        self.assertAlmostEqual(d2['amount_change'], (1000 * (11.0 + 11.0 + 10.0 + 12.0 + 10.0 + 10.0)) / (1000 * 60.0) - 1, places=9)
        self.assertEqual(set(self.daily[D[0]]) - {'date'}, set(METRICS))


class LibraryTests(unittest.TestCase):
    def test_build_read_verify_and_idempotency(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp); clock = lambda: datetime(2026, 12, 1, tzinfo=timezone.utc)
            store = RetroDailyStore(output, now_fn=clock, today_fn=lambda: date(2026, 12, 31))
            plan = store.create_plan(CAL[0], CAL[-1], sdk=FakeSDK()); store.fetch(plan['capture_id'], sdk=FakeSDK())
            library = MarketSentimentLibrary(output, now_fn=clock)
            build = library.build([plan['capture_id']])
            self.assertTrue(build['created']); self.assertEqual(build['rows'], len(CAL))
            self.assertFalse(library.build([plan['capture_id']])['created'])
            frame, _ = library.read(build['build_id'], start=CAL[20])
            self.assertEqual(frame.height, 20); self.assertEqual(frame['limit_up_count'].sum(), 2)
            self.assertEqual(library.verify(build['build_id'])['verified'], True)
            self.assertEqual(library.list()[0]['rows'], len(CAL))
            stream = io.StringIO()
            with redirect_stdout(stream):
                self.assertEqual(cli_main(['--output', str(output), '--call', 'read', '--build-id', build['build_id'], '--start', CAL[35].isoformat()]), 0)
            self.assertEqual(len(json.loads(stream.getvalue())['data']['rows']), 5)
            path = output / '_limit_research/market_sentiment' / build['build_id'] / 'daily.parquet'
            path.write_bytes(path.read_bytes() + b'x')
            with self.assertRaises(MarketSentimentError):
                library.read(build['build_id'])


if __name__ == '__main__':
    unittest.main()
