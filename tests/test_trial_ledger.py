import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from quantlab.statistics import trial_ledger as tl


def noise(seed, n=500, mean=0.0, vol=0.01):
    return np.random.default_rng(seed).normal(mean, vol, n)


DATES = [f"d{i:04d}" for i in range(500)]


class TrialLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ledger"

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_config_does_not_inflate_n(self):
        first = tl.record_trial(self.root, "fam", {"w": 1}, noise(1), dates=DATES)
        again = tl.record_trial(self.root, "fam", {"w": 1}, noise(1), dates=DATES)
        self.assertEqual((first["status"], again["status"]), ("recorded", "unchanged"))
        self.assertEqual(again["n_in_family"], 1)
        with self.assertRaises(ValueError):
            tl.record_trial(self.root, "fam", {"w": 1}, noise(2), dates=DATES)
        self.assertTrue(tl.verify_ledger(self.root)["ok"])

    def test_config_key_order_is_irrelevant_and_families_are_separate(self):
        tl.record_trial(self.root, "a", {"x": 1, "y": 2}, noise(1), dates=DATES)
        same = tl.record_trial(self.root, "a", {"y": 2, "x": 1}, noise(1), dates=DATES)
        other = tl.record_trial(self.root, "b", {"x": 1, "y": 2}, noise(1), dates=DATES)
        self.assertEqual(same["status"], "unchanged")
        self.assertEqual(other["status"], "recorded")

    def test_tampering_is_detected(self):
        for i in range(3):
            tl.record_trial(self.root, "fam", {"i": i}, noise(i), dates=DATES)
        ledger = self.root / "ledger.jsonl"
        original = ledger.read_text()
        lines = original.split("\n")
        # drop the middle trial: the chain must break
        ledger.write_text(lines[0] + "\n" + lines[2] + "\n")
        self.assertFalse(tl.verify_ledger(self.root)["ok"])
        # edit a config in place
        entry = json.loads(lines[1])
        entry["config"] = {"i": 99}
        ledger.write_text(lines[0] + "\n" + json.dumps(entry) + "\n" + lines[2] + "\n")
        self.assertIn("edited", " ".join(tl.verify_ledger(self.root)["problems"]))
        ledger.write_text(original)
        self.assertTrue(tl.verify_ledger(self.root)["ok"])
        # change a stored return series
        path = self.root / "returns" / f"{json.loads(lines[0])['config_id']}.json"
        data = json.loads(path.read_text())
        data["returns"][0] += 0.5
        path.write_text(json.dumps(data))
        self.assertIn("returns file changed", " ".join(tl.verify_ledger(self.root)["problems"]))

    def test_best_of_many_noise_trials_is_not_significant_after_deflation(self):
        for i in range(60):
            tl.record_trial(self.root, "noise", {"i": i}, noise(100 + i), dates=DATES)
        summary = tl.summarize(self.root, "noise")
        self.assertEqual(summary["n_recorded"], 60)
        dsr = summary["dsr"]["recorded"]
        self.assertGreater(dsr["psr_vs_zero"], dsr["dsr"])
        self.assertLess(dsr["dsr"], 0.95)
        self.assertGreater(summary["pbo"]["pbo"], 0.2)

    def test_real_edge_survives_and_is_found(self):
        for i in range(10):
            tl.record_trial(self.root, "edge", {"i": i}, noise(200 + i), dates=DATES)
        tl.record_trial(self.root, "edge", {"i": "real"}, noise(999, mean=0.004), dates=DATES)
        summary = tl.summarize(self.root, "edge")
        self.assertEqual(summary["best"]["config"], {"i": "real"})
        self.assertGreater(summary["dsr"]["recorded"]["dsr"], 0.95)

    def test_correlated_variants_have_small_effective_n(self):
        base = noise(5)
        for i in range(20):
            tl.record_trial(self.root, "corr", {"i": i}, base + noise(300 + i, vol=0.0005), dates=DATES)
        summary = tl.summarize(self.root, "corr")
        self.assertLess(summary["effective_trials"]["n_effective"], 3)
        self.assertGreater(summary["effective_trials"]["mean_correlation"], 0.9)

    def test_misaligned_series_skip_pbo_and_say_so(self):
        tl.record_trial(self.root, "m", {"i": 0}, noise(1), dates=DATES)
        tl.record_trial(self.root, "m", {"i": 1}, noise(2, n=400), dates=DATES[:400])
        summary = tl.summarize(self.root, "m")
        self.assertNotIn("pbo", summary)
        self.assertIn("alignment", summary)
        self.assertEqual(summary["n_recorded"], 2)

    def test_count_only_trials_and_assumed_n(self):
        tl.record_trial(self.root, "c", {"i": 0})
        tl.record_trial(self.root, "c", {"i": 1})
        summary = tl.summarize(self.root, "c")
        self.assertEqual((summary["n_recorded"], summary["n_with_returns"]), (2, 0))
        tl.record_trial(self.root, "c", {"i": 2}, noise(3), dates=DATES)
        summary = tl.summarize(self.root, "c", assumed_trials=500)
        self.assertEqual(summary["dsr"]["assumed"]["n_trials"], 500)
        self.assertGreater(summary["dsr"]["assumed"]["luck_hurdle"], summary["dsr"]["recorded"]["luck_hurdle"])

    def test_bad_input_is_rejected(self):
        with self.assertRaises(ValueError):
            tl.record_trial(self.root, "bad family!", {})
        with self.assertRaises(ValueError):
            tl.record_trial(self.root, "ok", {}, [0.1, float("nan"), 0.2])
        with self.assertRaises(ValueError):
            tl.record_trial(self.root, "ok", {}, [0.1, 0.2, 0.3], dates=["a"])
        with self.assertRaises(ValueError):
            tl.summarize(self.root, "nothing")


if __name__ == "__main__":
    unittest.main()
