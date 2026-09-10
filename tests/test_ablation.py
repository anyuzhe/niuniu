import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.app import default_registry
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot, ExplicitUniverse
from quantlab.experiments.ablation import AblationRunner, remove_condition, variants
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.runner import ExperimentRunner
from quantlab.storage.experiments import LocalExperimentStore, load_record
from quantlab.domain import Timeframe


INPUTS = {"m": {"factor_id": "BASE.MOMENTUM", "parameters": {"lookback": 1}},
    "e": {"factor_id": "BASE.DIRECTIONAL_EFFICIENCY", "parameters": {"lookback": 2}}}


class Provider:
    def __init__(self):
        self.calls = 0

    def load(self, request):
        self.calls += 1
        times = [datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=i) for i in range(6)]
        prices = [100.0, 110.0, 90.0, 120.0, 110.0, 150.0]
        bars = pl.DataFrame({"symbol": ["A"]*6, "datetime": times, "available_at": times, "timeframe": ["1d"]*6,
            "close": prices, "high": [p+1 for p in prices], "low": [p-1 for p in prices]})
        return DataBatch(bars, DataSnapshot("ablation-test-v1", "test", "raw", ()))


class AblationTests(unittest.TestCase):
    def test_structural_pruning_and_unchanged_weights(self):
        a = {"input": "m", "op": "gt", "value": 0}
        b = {"input": "e", "op": "gt", "value": 0}
        tree = {"all": [{"not": a}, {"any": [a, b]}]}
        original = deepcopy(tree)
        self.assertEqual(remove_condition(tree, "m"), b)
        self.assertEqual(tree, original)
        factor = default_registry().get("COMB.SCORE", "1.0.0")
        output = variants(factor, {"inputs": INPUTS, "weights": {"m": 2, "e": -0.5}})
        self.assertEqual(output["m"]["weights"], {"e": -0.5})
        self.assertEqual(output["e"]["weights"], {"m": 2})
        with self.assertRaisesRegex(ValueError, "at least two"):
            variants(factor, {"inputs": {"m": INPUTS["m"]}, "weights": {"m": 1}})

    def test_common_warmup_one_read_repeat_and_child_artifacts(self):
        provider = Provider()
        config = ExperimentConfig("消融测试", DataRequest(("A",), Timeframe.DAILY, date(2025,1,1), date(2025,1,6)),
            "COMB.SCORE", parameters={"inputs": INPUTS, "weights": {"m": 2, "e": 0.5}}, horizons=(1,))
        with tempfile.TemporaryDirectory() as tmp:
            runner = AblationRunner(ExperimentRunner(provider, default_registry(), ExplicitUniverse(("A",)), LocalExperimentStore(Path(tmp))))
            first = runner.run(config)
            self.assertEqual(provider.calls, 1)
            second = runner.run(config)
            self.assertEqual(provider.calls, 2)
            self.assertEqual(first.experiment_id, second.experiment_id)
            self.assertEqual(first.comparisons, second.comparisons)
            record = load_record(first.artifact_path / "experiment.json")
            self.assertEqual(record["manifest"]["common_eligible_before_regime"], 4)
            self.assertEqual(len(record["children"]), 3)
            for comparison in first.comparisons:
                obs = comparison["metrics"]["1"]["observations"]
                self.assertEqual(obs, {"full": 3, "without": 3, "delta_full_minus_without": 0})
                self.assertIsNone(comparison["metrics"]["1"]["ic"]["delta_full_minus_without"])
            for child in record["children"]:
                path = Path(child["artifact_path"])
                self.assertTrue((path / "observations.parquet").exists())
                self.assertTrue((path / "report.md").exists())
            self.assertIn("删减后参数", (first.artifact_path / "report.md").read_text())
            changed = runner.run(replace(config, parameters={"inputs": INPUTS, "weights": {"m": 3, "e": 0.5}}))
            self.assertNotEqual(first.experiment_id, changed.experiment_id)

    def test_condition_comparison_records_trigger_sample_change(self):
        rule = {"all": [{"input": "m", "op": "gt", "value": 0}, {"input": "e", "op": "gt", "value": 0}]}
        cfg = ExperimentConfig("布尔消融", DataRequest(("A",), Timeframe.DAILY, date(2025,1,1), date(2025,1,6)),
            "COMB.CONDITION", parameters={"inputs": INPUTS, "rule": rule}, horizons=(1,))
        with tempfile.TemporaryDirectory() as tmp:
            runner = AblationRunner(ExperimentRunner(Provider(), default_registry(), ExplicitUniverse(("A",)), LocalExperimentStore(Path(tmp))))
            result = runner.run(cfg)
            without_m = next(c for c in result.comparisons if c["removed"] == "m")
            counts = without_m["metrics"]["1"]["triggered_event_count"]
            self.assertEqual(counts["full"], 2)
            self.assertEqual(counts["without"], 3)
            self.assertEqual(counts["delta_full_minus_without"], -1)

    def test_invalid_study_saves_failure_before_data_read(self):
        provider = Provider()
        cfg = ExperimentConfig("错误消融", DataRequest(("A",), Timeframe.DAILY, date(2025,1,1), date(2025,1,6)), "BASE.MOMENTUM")
        with tempfile.TemporaryDirectory() as tmp:
            runner = AblationRunner(ExperimentRunner(provider, default_registry(), ExplicitUniverse(("A",)), LocalExperimentStore(Path(tmp))))
            with self.assertRaisesRegex(ValueError, "requires COMB"):
                runner.run(cfg)
            self.assertEqual(provider.calls, 0)
            records = list(Path(tmp).glob("*/experiment.json"))
            self.assertEqual(len(records), 1)
            self.assertEqual(load_record(records[0])["status"], "failed")


if __name__ == "__main__":
    unittest.main()
