import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from polars.testing import assert_frame_equal

from quantlab.app import default_registry
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot, ExplicitUniverse
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.runner import ExperimentRunner
from quantlab.experiments.walkforward import WalkForwardConfig, WalkForwardRunner
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore, load_record


class Provider:
    def __init__(self, multiplier=1):
        self.calls = 0
        self.multiplier = multiplier

    def load(self, request):
        self.calls += 1
        times = [datetime(2025,1,1,15,tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=i) for i in range(16)]
        prices = [(100.0+i) * (self.multiplier if i >= 9 else 1) for i in range(16)]
        frame = pl.DataFrame({"symbol": ["A"]*16, "datetime": times, "available_at": times, "timeframe": ["1d"]*16,
            "close": prices, "high": [p+1 for p in prices], "low": [p-1 for p in prices]})
        return DataBatch(frame, DataSnapshot(digest(frame.write_json()), "test", "raw", ()))


class WalkForwardTests(unittest.TestCase):
    def setUp(self):
        self.request = DataRequest(("A",), Timeframe.DAILY, date(2025,1,1), date(2025,1,16))
        self.config = ExperimentConfig("滚动评估", self.request, "BASE.MOMENTUM", parameters={"lookback": 2}, horizons=(1,3))
        self.schedule = WalkForwardConfig(4,2,3)

    def runner(self, provider, root):
        return WalkForwardRunner(ExperimentRunner(provider, default_registry(), ExplicitUniverse(("A",)), LocalExperimentStore(root)))

    def test_windows_nonoverlapping_tests_and_short_range_rejection(self):
        windows = self.schedule.windows(self.request)
        self.assertEqual([w["start"].day for w in windows], [1,4,7])
        self.assertEqual([w["valid_end"].day for w in windows], [6,9,12])
        self.assertEqual([w["end"].day for w in windows], [9,12,15])
        for invalid in ((0,2,3), (True,2,3), (1,2,1.5)):
            with self.assertRaises(ValueError):
                WalkForwardConfig(*invalid)
        with self.assertRaises(ValueError):
            WalkForwardConfig(20,2,3).windows(self.request)

    def test_one_read_reproducibility_tail_and_disjoint_test_artifacts(self):
        provider = Provider()
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(provider, Path(tmp))
            a = runner.run(self.config, self.schedule)
            self.assertEqual(provider.calls, 1)
            b = runner.run(self.config, self.schedule)
            self.assertEqual(provider.calls, 2)
            self.assertEqual(a.experiment_id, b.experiment_id)
            seen = set()
            for x, y in zip(a.folds, b.folds):
                self.assertEqual([p["metrics"] for p in x["periods"]], [p["metrics"] for p in y["periods"]])
                test = next(p for p in x["periods"] if p["name"] == "test")
                frame = pl.read_parquet(Path(test["artifact_path"]) / "observations.parquet")
                keys = set(frame["datetime"].to_list())
                self.assertFalse(keys & seen)
                seen |= keys
                self.assertEqual(test["metrics"]["1"]["observations"], 2)
                self.assertEqual(test["metrics"]["3"]["observations"], 0)
            record = load_record(a.artifact_path / "experiment.json")
            self.assertEqual(record["manifest"]["unused_tail"], {"start": "2025-01-16", "end": "2025-01-16"})
            self.assertIn("固定参数滚动评估", (a.artifact_path / "report.md").read_text())

    def test_later_data_cannot_change_earlier_fold(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.runner(Provider(), Path(tmp)).run(self.config, self.schedule)
            b = self.runner(Provider(multiplier=10), Path(tmp)).run(self.config, self.schedule)
            for x,y in zip(a.folds[0]["periods"],b.folds[0]["periods"]):
                self.assertEqual(x["metrics"], y["metrics"])
                assert_frame_equal(pl.read_parquet(Path(x["artifact_path"])/"observations.parquet"),
                    pl.read_parquet(Path(y["artifact_path"])/"observations.parquet"), check_exact=True)

    def test_invalid_study_records_failure_without_read(self):
        provider = Provider()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.runner(provider, Path(tmp)).run(self.config, WalkForwardConfig(20,2,3))
            self.assertEqual(provider.calls, 0)
            record = load_record(next(Path(tmp).glob("*/experiment.json")))
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["kind"], "walkforward")


if __name__ == "__main__":
    unittest.main()
