import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from polars.testing import assert_frame_equal

from quantlab.app import default_registry
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot, ExplicitUniverse
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.runner import ExperimentRunner
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore, load_record


class Provider:
    def __init__(self, future_multiplier=1):
        self.calls = 0
        self.future_multiplier = future_multiplier

    def load(self, request):
        self.calls += 1
        times = [datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=i) for i in range(12)]
        prices = [(100.0 + i) * (self.future_multiplier if i >= 8 else 1) for i in range(12)]
        bars = pl.DataFrame({"symbol": ["A"]*12, "datetime": times, "available_at": times, "timeframe": ["1d"]*12,
            "close": prices, "high": [p+1 for p in prices], "low": [p-1 for p in prices]})
        return DataBatch(bars, DataSnapshot(digest(bars.write_json()), "test", "raw", ()))


class HoldoutTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ExperimentConfig("时序分段验证", DataRequest(("A",), Timeframe.DAILY, date(2025,1,1), date(2025,1,12)),
            "BASE.MOMENTUM", parameters={"lookback": 2}, horizons=(1,3))
        self.split = ChronologicalSplit(date(2025,1,4), date(2025,1,8))

    def runner(self, provider, path):
        return HoldoutRunner(ExperimentRunner(provider, default_registry(), ExplicitUniverse(("A",)), LocalExperimentStore(path)))

    def test_labels_do_not_cross_boundaries_and_history_warms_validation(self):
        provider = Provider()
        with tempfile.TemporaryDirectory() as tmp:
            result = self.runner(provider, Path(tmp)).run(self.cfg, self.split)
            self.assertEqual(provider.calls, 1)
            self.assertEqual([p["metrics"]["1"]["observations"] for p in result.periods], [1,3,3])
            self.assertEqual([p["metrics"]["3"]["observations"] for p in result.periods], [0,1,1])
            for period in result.periods:
                data = pl.read_parquet(Path(period["artifact_path"]) / "observations.parquet")
                self.assertEqual(data["datetime"].dt.date().min(), period["start"])
                self.assertEqual(data["datetime"].dt.date().max(), period["end"])
                for column in ("forward_1", "mfe_1", "mae_1"):
                    self.assertIsNone(data[column][-1])
                for column in ("forward_3", "mfe_3", "mae_3"):
                    self.assertEqual(data[column].tail(3).to_list(), [None]*3)
                if period["name"] != "train":
                    self.assertIsNotNone(data["value"][0])
            self.assertIn("不跨段", (result.artifact_path / "report.md").read_text())

    def test_reproducibility_and_future_changes_do_not_affect_earlier_periods(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(Provider(), Path(tmp))
            a, b = runner.run(self.cfg, self.split), runner.run(self.cfg, self.split)
            self.assertEqual(a.experiment_id, b.experiment_id)
            self.assertEqual([p["metrics"] for p in a.periods], [p["metrics"] for p in b.periods])
            changed = self.runner(Provider(future_multiplier=10), Path(tmp)).run(self.cfg, self.split)
            for index in (0,1):
                self.assertEqual(a.periods[index]["metrics"], changed.periods[index]["metrics"])
                assert_frame_equal(pl.read_parquet(Path(a.periods[index]["artifact_path"])/"observations.parquet"),
                    pl.read_parquet(Path(changed.periods[index]["artifact_path"])/"observations.parquet"), check_exact=True)
            self.assertNotEqual(a.experiment_id, changed.experiment_id)

    def test_invalid_split_is_recorded_without_reading_data(self):
        with self.assertRaises(ValueError):
            ChronologicalSplit(date(2025,1,8), date(2025,1,4))
        provider = Provider()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.runner(provider, Path(tmp)).run(self.cfg, ChronologicalSplit(date(2024,1,1), date(2024,2,1)))
            self.assertEqual(provider.calls, 0)
            record = load_record(next(Path(tmp).glob("*/experiment.json")))
            self.assertEqual(record["kind"], "holdout")
            self.assertEqual(record["status"], "failed")


if __name__ == "__main__":
    unittest.main()
