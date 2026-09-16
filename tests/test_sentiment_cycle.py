from contextlib import redirect_stdout
from datetime import date, timedelta
import io
import json
import math
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import polars as pl

from quantlab.agent.sentiment_cycle_cli import main as cli_main
from quantlab.trading.sentiment_cycle import MIN_HISTORY, NEGATIVE, POSITIVE, classify, compute_cycle, similar_days


def synthetic(days=420, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(days)
    wave = np.sin(2 * math.pi * t / 60)
    dates = [date(2024, 1, 1) + timedelta(days=int(i)) for i in t]
    return pl.DataFrame({
        'date': dates,
        'limit_up_count_non_st': (60 + 40 * wave + rng.normal(0, 3, days)).round(0),
        'max_streak': (4 + 3 * wave + rng.normal(0, 0.3, days)).round(0),
        'advance_rate_1to2': 0.25 + 0.15 * wave + rng.normal(0, 0.01, days),
        'prev_limit_up_avg_return': 0.01 + 0.02 * wave + rng.normal(0, 0.002, days),
        'up_ratio': 0.5 + 0.2 * wave + rng.normal(0, 0.02, days),
        'limit_down_count_non_st': (20 - 15 * wave + rng.normal(0, 2, days)).round(0),
        'broken_rate': 0.3 - 0.15 * wave + rng.normal(0, 0.01, days),
        'big_loss_count': (10 - 8 * wave + rng.normal(0, 1, days)).round(0),
        'limit_up_count': (65 + 40 * wave).round(0),
    })


class ClassifyTests(unittest.TestCase):
    def test_rule_order(self):
        self.assertEqual(classify(None, None), 'UNKNOWN')
        self.assertEqual(classify(float('nan'), 5.0), 'UNKNOWN')
        self.assertEqual(classify(15, 30), 'ICE')
        self.assertEqual(classify(85, -30), 'CLIMAX')
        self.assertEqual(classify(40, 12), 'REPAIR'); self.assertEqual(classify(60, 12), 'FERMENT')
        self.assertEqual(classify(60, -12), 'DIVERGENCE'); self.assertEqual(classify(40, -12), 'EBB')
        self.assertEqual(classify(55, 2), 'RANGE_WARM'); self.assertEqual(classify(45, None), 'RANGE_COOL')


class CycleTests(unittest.TestCase):
    def test_history_requirement_bounds_and_phase_coverage(self):
        cycle = compute_cycle(synthetic())
        self.assertTrue(all(p == 'UNKNOWN' for p in cycle['phase'][:MIN_HISTORY]))
        known = cycle.filter(pl.col('temperature').is_not_null())
        self.assertGreater(known.height, 300)
        self.assertTrue(known['temperature'].min() >= 0 and known['temperature'].max() <= 100)
        self.assertTrue({'ICE', 'CLIMAX', 'REPAIR', 'DIVERGENCE'} <= set(known['phase'].to_list()))
        for name in POSITIVE + NEGATIVE:
            values = known['pct_' + name].drop_nulls()
            self.assertTrue(values.min() >= 0 and values.max() <= 1)

    def test_no_lookahead_truncation_invariance(self):
        daily = synthetic(); full = compute_cycle(daily)
        for cut in (120, 250, 333, 419):
            truncated = compute_cycle(daily.head(cut + 1))
            self.assertEqual(full.row(cut, named=True), truncated.row(cut, named=True))

    def test_percentile_excludes_today_and_uses_window(self):
        values = list(range(100)) + [50]
        daily = pl.DataFrame({'date': [date(2024, 1, 1) + timedelta(days=i) for i in range(101)],
                              **{n: values for n in POSITIVE + NEGATIVE}})
        cycle = compute_cycle(daily)
        self.assertAlmostEqual(cycle['pct_max_streak'][100], 50.5 / 100)
        self.assertAlmostEqual(cycle['pct_max_streak'][99], 1.0)
        self.assertIsNone(cycle['pct_max_streak'][MIN_HISTORY - 1])

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            compute_cycle(pl.DataFrame({'date': [date(2024, 1, 1)]}))
        daily = synthetic(70)
        with self.assertRaises(ValueError):
            compute_cycle(pl.concat([daily, daily.tail(1)]))


class SimilarDayTests(unittest.TestCase):
    def test_neighbors_are_strictly_historical_and_outcomes_known(self):
        daily = synthetic(); target = daily['date'][400]
        result = similar_days(daily, target, k=5, exclude_recent=20)
        self.assertEqual(len(result['neighbors']), 5)
        for row in result['neighbors']:
            self.assertLess(date.fromisoformat(row['next_date']), target - timedelta(days=19))
        distances = [row['distance'] for row in result['neighbors']]
        self.assertEqual(distances, sorted(distances))
        # Profiles are levels, so analogues share the wave level (rising or falling side alike).
        level = lambda i: math.sin(2 * math.pi * i / 60)
        gaps = [abs(level((date.fromisoformat(r['date']) - daily['date'][0]).days) - level(400)) for r in result['neighbors']]
        self.assertTrue(all(g <= 0.5 for g in gaps), gaps)
        with self.assertRaises(ValueError):
            similar_days(daily, daily['date'][10])
        with self.assertRaises(ValueError):
            similar_days(daily, target, k=0)


class CliTests(unittest.TestCase):
    def test_rules_and_missing_build(self):
        with TemporaryDirectory() as tmp:
            stream = io.StringIO()
            with redirect_stdout(stream):
                self.assertEqual(cli_main(['--output', tmp, '--call', 'rules']), 0)
            data = json.loads(stream.getvalue())['data']
            self.assertEqual(data['origin'], 'host_engineering_policy_not_expert_rule'); self.assertEqual(len(data['rules']), 6)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli_main(['--output', tmp, '--call', 'cycle', '--build-id', '00000000-0000-0000-0000-000000000000']), 2)

if __name__ == '__main__':
    unittest.main()
