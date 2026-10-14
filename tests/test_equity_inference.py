import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from quantlab.execution.performance import performance_metrics
from quantlab.statistics.equity_inference import block_sensitivity, bootstrap_performance, daily_returns


def curve_from(returns, cash=1_000_000.0):
    start = datetime(2024, 1, 2, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    equity, rows = cash, []
    for i, r in enumerate(returns):
        equity *= 1 + r
        rows.append({"datetime": start + timedelta(days=i), "cash": equity, "position_value": 0.0, "equity": equity})
    return pl.DataFrame(rows)


def ar1(n, phi, seed, mean=0.0, sd=0.01):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0, sd)
    return x + mean


class EquityInferenceTests(unittest.TestCase):
    def test_daily_returns_reproduce_engine_sharpe(self):
        r = np.random.default_rng(4).normal(0.0006, 0.01, 300)
        curve = curve_from(r)
        mine = daily_returns(curve, 1_000_000.0)
        np.testing.assert_allclose(mine, r, atol=1e-12)
        engine = performance_metrics(curve, 1_000_000.0)["sharpe"]
        self.assertAlmostEqual(mine.mean() / mine.std(ddof=1) * np.sqrt(252), engine, places=9)

    def test_results_are_deterministic_and_interval_contains_estimate(self):
        r = np.random.default_rng(5).normal(0.0008, 0.01, 1500)
        a, b = bootstrap_performance(r, resamples=500), bootstrap_performance(r, resamples=500)
        self.assertEqual(a, b)
        low, high = a["intervals"]["sharpe"]
        self.assertLess(low, a["observed"]["sharpe"])
        self.assertGreater(high, a["observed"]["sharpe"])
        self.assertLess(a["intervals"]["max_drawdown"][1], 0.0)

    def test_more_data_gives_a_tighter_interval(self):
        wide = bootstrap_performance(np.random.default_rng(6).normal(0.0008, 0.01, 500), resamples=500)["intervals"]["sharpe"]
        tight = bootstrap_performance(np.random.default_rng(6).normal(0.0008, 0.01, 4000), resamples=500)["intervals"]["sharpe"]
        self.assertGreater(wide[1] - wide[0], 1.8 * (tight[1] - tight[0]))

    def test_interval_covers_the_true_sharpe_most_of_the_time(self):
        true_sharpe = 0.0005 / 0.01 * np.sqrt(252)
        hits = 0
        for seed in range(120):
            r = np.random.default_rng(1000 + seed).normal(0.0005, 0.01, 1000)
            low, high = bootstrap_performance(r, resamples=300, block_days=5)["intervals"]["sharpe"]
            hits += low <= true_sharpe <= high
        self.assertGreater(hits / 120, 0.86)

    def test_p_value_is_roughly_calibrated_under_zero_skill(self):
        p = [bootstrap_performance(np.random.default_rng(2000 + s).normal(0, 0.01, 1000), resamples=300, block_days=5)
             ["p_sharpe_not_above_zero"] for s in range(120)]
        self.assertAlmostEqual(float(np.mean(np.asarray(p) < 0.05)), 0.05, delta=0.05)
        self.assertAlmostEqual(float(np.mean(p)), 0.5, delta=0.08)

    def test_serial_correlation_widens_the_block_bootstrap_interval(self):
        rows = block_sensitivity(ar1(2500, 0.5, 9, mean=0.0004), blocks=(1, 20), resamples=600)
        self.assertGreater(rows[1]["width"], 1.25 * rows[0]["width"])

    def test_known_drawdown_and_invalid_inputs(self):
        path = np.array([0.1, -0.2, 0.1] * 20)
        equity, peak, worst = 1.0, 1.0, 0.0
        for r in path:
            equity *= 1 + r
            peak = max(peak, equity)
            worst = min(worst, equity / peak - 1)
        observed = bootstrap_performance(path, block_days=30, resamples=200)["observed"]
        self.assertAlmostEqual(observed["max_drawdown"], worst, places=12)
        self.assertAlmostEqual(observed["annual_return"], (np.prod(1 + path)) ** (252 / path.size) - 1, places=9)
        with self.assertRaises(ValueError):
            bootstrap_performance(np.zeros(10))
        with self.assertRaises(ValueError):
            bootstrap_performance(np.append(np.zeros(60), -1.0))
        with self.assertRaises(ValueError):
            bootstrap_performance(np.random.default_rng(0).normal(0, 0.01, 100), block_days=80)


if __name__ == "__main__":
    unittest.main()
