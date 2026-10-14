import math
import unittest

import numpy as np

from quantlab.statistics.multiple_testing import (
    benjamini_hochberg, deflated_sharpe_ratio, expected_max_sharpe, probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting, sharpe_moments)
from quantlab.statistics.permutation import holm


class SharpeCorrectionTests(unittest.TestCase):
    def test_psr_is_one_half_at_its_own_benchmark_and_monotone_in_length(self):
        self.assertAlmostEqual(probabilistic_sharpe_ratio(0.1, 250, benchmark=0.1), 0.5)
        short, long = (probabilistic_sharpe_ratio(0.1, n) for n in (100, 1000))
        self.assertLess(short, long)

    def test_psr_is_calibrated_for_zero_skill_iid_returns(self):
        rng = np.random.default_rng(7)
        values = []
        for _ in range(3000):
            m = sharpe_moments(rng.normal(0, 0.01, 250))
            values.append(probabilistic_sharpe_ratio(m["sharpe"], m["n_obs"], m["skew"], m["kurtosis"]))
        values = np.asarray(values)
        self.assertAlmostEqual(values.mean(), 0.5, delta=0.03)
        self.assertAlmostEqual((values > 0.95).mean(), 0.05, delta=0.02)

    def test_expected_max_matches_simulated_maximum_of_normals(self):
        draws = np.random.default_rng(11).normal(size=(20000, 100)).max(axis=1).mean()
        self.assertAlmostEqual(expected_max_sharpe(100, 1.0), draws, delta=0.05)
        self.assertEqual(expected_max_sharpe(1, 3.0), 0.0)

    def test_dsr_reduces_to_psr_for_one_trial_and_falls_with_more_trials(self):
        r = np.random.default_rng(3).normal(0.0008, 0.01, 2000)
        one = deflated_sharpe_ratio(r, 1)
        self.assertAlmostEqual(one["dsr"], one["psr_vs_zero"])
        scores = [deflated_sharpe_ratio(r, n)["dsr"] for n in (1, 10, 100, 4000)]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertLess(scores[-1], scores[0])

    def test_best_of_many_noise_strategies_does_not_survive_deflation(self):
        noise = np.random.default_rng(5).normal(0, 0.01, (2000, 500))
        sharpes = noise.mean(axis=0) / noise.std(axis=0, ddof=1)
        best = int(sharpes.argmax())
        result = deflated_sharpe_ratio(noise[:, best], 500, float(sharpes.std(ddof=1)))
        self.assertGreater(result["psr_vs_zero"], 0.95)   # looks significant on its own...
        self.assertLess(result["dsr"], 0.95)              # ...but not after 500 tries

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            sharpe_moments([0.01, 0.01, 0.01, 0.01])
        with self.assertRaises(ValueError):
            expected_max_sharpe(0, 1.0)
        with self.assertRaises(ValueError):
            probabilistic_sharpe_ratio(3.0, 100, skew=10.0, kurtosis=3.0)


class FalseDiscoveryTests(unittest.TestCase):
    def test_known_benjamini_hochberg_example(self):
        result = benjamini_hochberg([0.01, 0.04, 0.03, 0.005], alpha=0.05)
        self.assertEqual([round(q, 12) for q in result["q_values"]], [0.02, 0.04, 0.04, 0.02])
        self.assertEqual(result["reject"], [True, True, True, True])

    def test_missing_tests_keep_their_slot_and_bh_is_never_stricter_than_holm(self):
        p = [0.001, None, 0.02, 0.2, 0.5]
        q = benjamini_hochberg(p)["q_values"]
        self.assertIsNone(q[1])
        for qi, hi in zip(q, holm(p)):
            if qi is not None:
                self.assertLessEqual(qi, hi + 1e-12)
        self.assertEqual(benjamini_hochberg(p)["m"], 5)


class OverfittingTests(unittest.TestCase):
    def test_pure_noise_variants_give_pbo_near_one_half_on_average(self):
        # One dataset is noisy (sd ~0.15 across seeds), so the unbiasedness is checked over many seeds.
        values = [probability_of_backtest_overfitting(np.random.default_rng(seed).normal(0, 0.01, (1600, 40)), n_splits=8)["pbo"]
                  for seed in range(40)]
        self.assertGreater(float(np.mean(values)), 0.38)
        self.assertLess(float(np.mean(values)), 0.62)

    def test_a_real_edge_gives_low_pbo(self):
        x = np.random.default_rng(2).normal(0, 0.01, (1600, 40))
        x[:, 7] += 0.002
        result = probability_of_backtest_overfitting(x)
        self.assertLess(result["pbo"], 0.1)
        self.assertGreater(result["mean_out_of_sample_sharpe_of_that_variant"], 0)

    def test_invalid_shapes_are_rejected(self):
        with self.assertRaises(ValueError):
            probability_of_backtest_overfitting(np.zeros((100, 1)))
        with self.assertRaises(ValueError):
            probability_of_backtest_overfitting(np.random.default_rng(0).normal(size=(100, 5)), n_splits=7)


if __name__ == "__main__":
    unittest.main()
