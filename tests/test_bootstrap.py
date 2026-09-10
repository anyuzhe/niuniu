import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import polars as pl

from test_holdout import Provider
from quantlab.app import default_registry
from quantlab.data.base import DataRequest, ExplicitUniverse
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.runner import ExperimentRunner
from quantlab.statistics.bootstrap import BootstrapConfig, block_mean_interval, bootstrap_statistics
from quantlab.storage.experiments import LocalExperimentStore, load_record


class BootstrapTests(unittest.TestCase):
    def test_circular_blocks_wrap_and_truncate_last_block(self):
        with patch("quantlab.statistics.bootstrap.random.Random.randrange", return_value=4):
            result = block_mean_interval([0., 1., 2., 3., 4.], BootstrapConfig(20, 2), 7)
        self.assertEqual(result["estimate"], 2)
        # Draws [4, 0], [4, 0], [4]; the last block is truncated to five dates.
        self.assertEqual((result["ci_low"], result["ci_high"]), (2.4, 2.4))

    def test_intraday_ic_is_averaged_before_dates(self):
        rows = []
        for day, hour, direction in [(1, 10, 1), (1, 11, -1), (2, 10, 1)]:
            for index, symbol in enumerate(("A", "B", "C")):
                rows.append({"symbol": symbol, "datetime": datetime(2025,1,day,hour),
                    "value": float(index), "forward_1": direction * float(index)})
        results = bootstrap_statistics(pl.DataFrame(rows), (1,), BootstrapConfig(100, 1), 7)
        for name in ("daily_mean_ic", "daily_mean_rank_ic"):
            self.assertAlmostEqual(results["1"][name]["estimate"], .5)
            self.assertEqual(results["1"][name]["valid_days"], 2)

    def test_constant_missing_and_insufficient_blocks(self):
        config = BootstrapConfig(100, 1)
        result = block_mean_interval([2.0, None, 2.0], config, 7)
        self.assertEqual(result["status"], "computed")
        self.assertEqual((result["estimate"], result["ci_low"], result["ci_high"]), (2, 2, 2))
        self.assertEqual((result["observed_days"], result["valid_days"]), (3, 2))
        self.assertEqual(result, block_mean_interval([2.0, None, 2.0], config, 7))
        short = block_mean_interval([1.0, 2.0, 3.0], BootstrapConfig(100, 2), 7)
        self.assertEqual(short["reason"], "insufficient_valid_days_for_two_blocks")
        self.assertIsNone(short["ci_low"])
        self.assertEqual(short["block_days"], 2)

    def test_validation(self):
        for kwargs in ({"resamples": 19}, {"resamples": True}, {"block_days": 0}, {"confidence": 1}, {"confidence": float("nan")}):
            with self.assertRaises(ValueError):
                BootstrapConfig(**kwargs)
        with self.assertRaises(ValueError):
            block_mean_interval([float("inf")], BootstrapConfig(), 0)

    def test_daily_weighting_missing_dates_and_order_independence(self):
        frame = pl.DataFrame({"symbol": ["A", "B", "A", "A"],
            "datetime": [datetime(2025,1,1), datetime(2025,1,1), datetime(2025,1,2), datetime(2025,1,3)],
            "value": [0., 0., 0., 0.], "forward_1": [.1, .1, .3, None], "forward_2": [.2, .2, .4, None]})
        config = BootstrapConfig(100, 1)
        results = bootstrap_statistics(frame, (1, 2), config, 7, boolean_factor=True)
        self.assertEqual(results, bootstrap_statistics(frame.reverse(), (2, 1), config, 7, boolean_factor=True))
        mean = results["1"]["daily_mean_forward_return"]
        self.assertAlmostEqual(mean["estimate"], .2)
        self.assertEqual((mean["observed_days"], mean["valid_days"]), (3, 2))
        self.assertEqual(results["1"]["daily_mean_ic"]["status"], "unavailable")
        self.assertEqual(results["1"]["triggered_daily_mean_forward_return"]["valid_days"], 0)
        empty = bootstrap_statistics(frame.head(0), (1,), config, 7)
        self.assertEqual(empty["1"]["daily_mean_forward_return"]["observed_days"], 0)

    def test_runner_persistence_repeatability_and_holdout_propagation(self):
        base = ExperimentConfig("Bootstrap 验证", DataRequest(("A",), Timeframe.DAILY, date(2025,1,1), date(2025,1,12)),
            "BASE.MOMENTUM", parameters={"lookback": 2}, horizons=(1,3))
        config = replace(base, random_seed=7, bootstrap=BootstrapConfig(100, 1))
        with tempfile.TemporaryDirectory() as tmp:
            runner = ExperimentRunner(Provider(), default_registry(), ExplicitUniverse(("A",)), LocalExperimentStore(Path(tmp)))
            original = runner.run(base)
            a, b = runner.run(config), runner.run(config)
            self.assertEqual(a.experiment_id, b.experiment_id)
            self.assertEqual(a.metrics, b.metrics)
            for horizon, metrics in a.metrics.items():
                self.assertEqual({k:v for k,v in metrics.items() if k != "bootstrap"}, original.metrics[horizon])
                self.assertEqual(metrics["bootstrap"]["daily_mean_forward_return"]["status"], "computed")
            record = load_record(a.artifact_path / "experiment.json")
            self.assertEqual(record["manifest"]["config"]["random_seed"], 7)
            self.assertEqual(record["metrics"], a.metrics)
            self.assertIn("Bootstrap", (a.artifact_path / "report.md").read_text())
            split = HoldoutRunner(runner).run(config, ChronologicalSplit(date(2025,1,4), date(2025,1,8)))
            self.assertEqual([p["metrics"]["1"]["bootstrap"]["daily_mean_forward_return"]["status"] for p in split.periods],
                ["unavailable", "computed", "computed"])


if __name__ == "__main__":
    unittest.main()
