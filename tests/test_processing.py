import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from test_holdout import Provider
from quantlab.app import default_registry
from quantlab.data.base import DataRequest, ExplicitUniverse
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.runner import ExperimentRunner
from quantlab.processing.cross_section import CrossSectionConfig, transform_cross_section
from quantlab.storage.experiments import LocalExperimentStore, load_record


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2025, 1, 1, 15)
        self.frame = pl.DataFrame({"symbol": ["A", "B", "C", "D", "E"], "datetime": [self.now]*5,
            "available_at": [self.now]*5, "value": [1., 1., 4., 100., None]})
        self.mask = self.frame.select("symbol", "datetime").with_columns(pl.Series("eligible", [True, True, True, False, True]))

    def test_ties_missing_and_universe(self):
        ranks = transform_cross_section(self.frame, self.mask, CrossSectionConfig())
        self.assertEqual(ranks["value"].to_list(), [1/3, 1/3, 5/6, None, None])
        score = transform_cross_section(self.frame, self.mask, CrossSectionConfig("cs_zscore"))["value"].drop_nulls()
        self.assertAlmostEqual(score.mean(), 0)
        self.assertAlmostEqual(score.std(ddof=0), 1)
        for method, expected in [("cs_rank", .5), ("cs_zscore", 0.)]:
            constant = transform_cross_section(self.frame.head(2), self.mask.head(2), CrossSectionConfig(method))
            self.assertEqual(constant["value"].to_list(), [expected]*2)
            empty = transform_cross_section(self.frame.head(0), self.mask.head(0), CrossSectionConfig(method))
            self.assertEqual(empty.height, 0)

    def test_prefix_invariance_order_and_information_time(self):
        config = CrossSectionConfig()
        expected = transform_cross_section(self.frame, self.mask, config)
        future = self.frame.with_columns(pl.col("datetime") + timedelta(days=1), pl.col("available_at") + timedelta(days=1), pl.col("value") * -100)
        full = pl.concat([self.frame, future])
        masks = pl.concat([self.mask, self.mask.with_columns(pl.col("datetime") + timedelta(days=1))])
        result = transform_cross_section(full.reverse(), masks.reverse(), config)
        assert_frame_equal(result.filter(pl.col("datetime") == self.now), expected)
        delayed = self.frame.with_columns(pl.when(pl.col("symbol") == "C").then(pl.col("available_at") + timedelta(minutes=1)).otherwise(pl.col("available_at")).alias("available_at"))
        result = transform_cross_section(delayed, self.mask, config)
        self.assertEqual(result.filter(pl.col("value").is_not_null())["available_at"].to_list(), [self.now + timedelta(minutes=1)]*3)
        with self.assertRaises(ValueError):
            transform_cross_section(self.frame, self.mask.head(1), config)

    def test_runner_raw_values_repeatability_and_split(self):
        cfg = ExperimentConfig("截面预处理", DataRequest(("A",), Timeframe.DAILY, date(2025,1,1), date(2025,1,12)),
            "BASE.MOMENTUM", parameters={"lookback": 2}, horizons=(1,), processor=CrossSectionConfig())
        with tempfile.TemporaryDirectory() as tmp:
            runner = ExperimentRunner(Provider(), default_registry(), ExplicitUniverse(("A",)), LocalExperimentStore(Path(tmp)))
            a, b = runner.run(cfg), runner.run(cfg)
            self.assertEqual(a.experiment_id, b.experiment_id)
            self.assertEqual(a.metrics, b.metrics)
            data = pl.read_parquet(a.artifact_path / "observations.parquet")
            raw = runner.run(replace(cfg, processor=None))
            original = pl.read_parquet(raw.artifact_path / "observations.parquet")
            self.assertEqual(data["raw_value"].to_list(), original["value"].to_list())
            self.assertEqual(data["value"].drop_nulls().unique().to_list(), [.5])
            self.assertEqual(data["forward_1"].to_list(), original["forward_1"].to_list())
            self.assertNotIn("raw_value", original.columns)
            record = load_record(a.artifact_path / "experiment.json")
            self.assertIsNone(record["manifest"]["processor"]["fit_period"])
            self.assertIn("截面预处理", (a.artifact_path / "report.md").read_text())
            split = HoldoutRunner(runner).run(cfg, ChronologicalSplit(date(2025,1,4), date(2025,1,8)))
            for period in split.periods:
                self.assertIn("raw_value", pl.read_parquet(Path(period["artifact_path"]) / "observations.parquet").columns)
            with self.assertRaisesRegex(ValueError, "scalar"):
                runner.run(replace(cfg, factor_id="EVT.BREAKOUT_HIGH"))


if __name__ == "__main__":
    unittest.main()
