import math
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
from quantlab.experiments.runner import ExperimentRunner
from quantlab.regime.config import RegimeConfig, RegimeFilter
from quantlab.regime.engine import RuleBasedRegimeEngine, compute_regime, filter_mask
from quantlab.storage.experiments import LocalExperimentStore, load_record


def inputs(efficiencies, volatilities, symbol="A"):
    times = [datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=i) for i in range(len(efficiencies))]
    return pl.DataFrame({"symbol": [symbol] * len(times), "datetime": times, "available_at": times,
        "timeframe": ["1d"] * len(times), "efficiency": efficiencies, "volatility": volatilities},
        schema_overrides={"efficiency": pl.Float64, "volatility": pl.Float64})


class RegimeTests(unittest.TestCase):
    def test_boundaries_unknown_and_zero_baseline(self):
        frame = inputs([None, 0.3, -0.3, 0.2, 0.6, -0.6], [None, 1.0, 0.75, 1.125, 0.0, 0.0])
        engine = RuleBasedRegimeEngine(RegimeConfig(baseline_window=1))
        result = engine.frame(frame)
        self.assertEqual(result["regime_direction"].to_list(), ["Unknown", "Bull", "Bear", "Neutral", "Bull", "Bear"])
        self.assertEqual(result["regime_structure"].to_list(), ["Unknown", "Transition", "Transition", "Range", "Trend", "Trend"])
        self.assertEqual(result["regime_volatility"].to_list(), ["Unknown", "Unknown", "Low", "High", "Low", "Low"])
        states = engine.classify(frame)
        self.assertTrue(all(s.liquidity == "Unknown" for s in states))
        jump = engine.frame(inputs([0.0, 0.0], [0.0, 0.1]))
        self.assertEqual(jump["regime_volatility"].to_list(), ["Unknown", "High"])

    def test_prior_window_prefix_invariance_and_symbol_isolation(self):
        frame = pl.concat([inputs([0.5] * 5, [1.0, 1.0, 100.0, 1.0, 1.0]), inputs([0.0] * 5, [0.0] * 5, "B")])
        engine = RuleBasedRegimeEngine(RegimeConfig(baseline_window=2))
        full = engine.frame(frame)
        self.assertEqual(full.filter(pl.col("symbol") == "A")["volatility_baseline"][2], 1.0)
        self.assertEqual(full.filter(pl.col("symbol") == "A")["regime_volatility"][2], "High")
        self.assertEqual(full.filter(pl.col("symbol") == "B")["regime_volatility"][2], "Low")
        for n in (2, 3, 4):
            cutoff = frame["available_at"][n-1]
            assert_frame_equal(engine.frame(frame.filter(pl.col("available_at") <= cutoff)), full.filter(pl.col("available_at") <= cutoff), check_exact=True)
        assert_frame_equal(full, engine.frame(frame.reverse()), check_exact=True)

    def test_validation_and_filter_unknown(self):
        for kwargs in ({"lookback": True}, {"baseline_window": 0}, {"range_threshold": 0.8}, {"volatility_high": math.nan}):
            with self.assertRaises(ValueError):
                RegimeConfig(**kwargs)
        with self.assertRaises(ValueError):
            RegimeFilter(direction="Up")
        with self.assertRaises(ValueError):
            RegimeFilter()
        states = RuleBasedRegimeEngine().frame(inputs([None, 0.8, -0.8], [None, 0.1, 0.1]))
        selected = filter_mask(states, RegimeFilter(direction="Bull", structure="Trend"))
        self.assertEqual(selected["regime_eligible"].to_list(), [False, True, False])

    def test_runner_filter_preserves_future_horizon_and_reproducibility(self):
        frame = inputs([0.0] * 10, [0.0] * 10).drop("efficiency", "volatility")
        closes = [100.0, 110.0, 120.0, 100.0, 90.0, 110.0, 120.0, 90.0, 80.0, 100.0]
        frame = frame.with_columns(pl.Series("close", closes)).with_columns(
            (pl.col("close") + 1).alias("high"), (pl.col("close") - 1).alias("low"))

        class Provider:
            def load(self, request):
                return DataBatch(frame, DataSnapshot("synthetic-regime-v1", "test", "raw", ()))

        data = DataRequest(("A",), Timeframe.DAILY, date(2025, 1, 1), date(2025, 1, 10))
        cfg = ExperimentConfig("conditional horizon", data, "BASE.MOMENTUM", parameters={"lookback": 2}, horizons=(1,),
            regime=RegimeConfig(lookback=2, baseline_window=2), regime_filter=RegimeFilter(direction="Bull"))
        registry = default_registry()
        full_states, _ = compute_regime(frame, registry, cfg.regime)
        for n in (4, 6):
            prefix, _ = compute_regime(frame.head(n), registry, cfg.regime)
            assert_frame_equal(prefix, full_states.head(n), check_exact=True)
        with tempfile.TemporaryDirectory() as tmp:
            runner = ExperimentRunner(Provider(), registry, ExplicitUniverse(("A",)), LocalExperimentStore(Path(tmp)))
            a, b = runner.run(cfg), runner.run(cfg)
            self.assertEqual(a.experiment_id, b.experiment_id)
            self.assertEqual(a.metrics, b.metrics)
            record = load_record(a.artifact_path / "experiment.json")
            result = pl.read_parquet(a.artifact_path / "observations.parquet")
            expected = frame.with_columns((pl.col("close").shift(-1) / pl.col("close") - 1).alias("expected"))
            checked = result.join(expected.select("datetime", "expected"), on="datetime")
            self.assertEqual(checked["forward_1"].to_list(), checked["expected"].to_list())
            self.assertTrue((result["regime_direction"] == "Bull").all())
            self.assertEqual(record["regime_summary"]["eligible_before"], 10)
            self.assertLess(record["regime_summary"]["eligible_after"], 10)
            self.assertEqual(record["baseline_metrics"]["1"]["observations"], 7)
            self.assertIn("市场状态", (a.artifact_path / "report.md").read_text())
            annotate = runner.run(replace(cfg, regime_filter=None))
            plain = runner.run(replace(cfg, regime=None, regime_filter=None))
            self.assertEqual(annotate.metrics, plain.metrics)
            empty = runner.run(replace(cfg, regime_filter=RegimeFilter(direction="Bull", structure="Range")))
            self.assertEqual(empty.metrics["1"]["eligible_bars"], 0)
            self.assertIsNone(empty.metrics["1"]["mean_forward_return"])


if __name__ == "__main__":
    unittest.main()
