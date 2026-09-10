import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from polars.testing import assert_frame_equal

from quantlab.app import default_registry
from quantlab.causal import assert_prefix_invariant
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot, ExplicitUniverse
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.research import FactorResearchEngine
from quantlab.experiments.runner import ExperimentRunner
from quantlab.factors.builtin import Momentum
from quantlab.factors.engine import compute_factor
from quantlab.factors.registry import FactorPack
from quantlab.storage.experiments import LocalExperimentStore, load_record
from dataclasses import replace


INPUTS = {
    "m": {"factor_id": "BASE.MOMENTUM", "parameters": {"lookback": 1}},
    "e": {"factor_id": "BASE.DIRECTIONAL_EFFICIENCY", "parameters": {"lookback": 2}},
}
RULE = {"all": [
    {"any": [{"input": "m", "op": "gt", "value": 0}, {"input": "e", "op": "gt", "value": 0}]},
    {"not": {"input": "e", "op": "lt", "value": 0}},
]}


def bars():
    prices = [100.0, 110.0, 90.0, 120.0, 110.0, 150.0]
    times = [datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=i) for i in range(6)]
    return pl.DataFrame({"symbol": ["A"]*6, "datetime": times, "available_at": times, "timeframe": ["1d"]*6,
        "open": prices, "high": [p+1 for p in prices], "low": [p-1 for p in prices], "close": prices,
        "volume": [100.0]*6, "turnover": [10000.0]*6})


class DelayedMomentum(Momentum):
    definition = replace(Momentum.definition, factor_id="TEST.DELAYED")

    def compute(self, bars, parameters):
        return super().compute(bars, parameters).with_columns((pl.col("available_at") + pl.duration(hours=1)).alias("available_at"))


class CombinationTests(unittest.TestCase):
    def test_nested_conditions_and_conservative_missing_values(self):
        factor = default_registry().get("COMB.CONDITION", "1.0.0")
        parameters = factor.parameters({"inputs": INPUTS, "rule": RULE})
        values = compute_factor(factor, bars(), parameters)
        self.assertEqual(values["value"].to_list(), [None, None, 0.0, 1.0, 1.0, 1.0])
        assert_prefix_invariant(factor, bars(), parameters, bars()["datetime"].to_list()[1:-1])
        assert_frame_equal(values, compute_factor(factor, bars().reverse(), parameters), check_exact=True)

    def test_score_weights_and_warmup(self):
        factor = default_registry().get("COMB.SCORE", "1.0.0")
        params = factor.parameters({"inputs": INPUTS, "weights": {"m": 2.0, "e": -0.5}})
        result = compute_factor(factor, bars(), params)
        self.assertEqual(result["value"].head(2).to_list(), [None, None])
        self.assertAlmostEqual(result["value"][2], 2 * (90/110-1) - 0.5 * (-10/30))
        assert_prefix_invariant(factor, bars(), params, bars()["datetime"].to_list()[1:-1])
        renamed = deepcopy(params)
        renamed["weights"]["m"] = 0.0
        self.assertNotEqual(result["value"].to_list(), compute_factor(factor, bars(), renamed)["value"].to_list())

    def test_invalid_reference_recursion_and_nonfinite_weights(self):
        registry = default_registry()
        factor = registry.get("COMB.CONDITION", "1.0.0")
        for rule in ({"all": []}, {"input": "missing", "op": "eq", "value": 1}, {"input": "m", "op": "eval", "value": 1}):
            with self.assertRaises(ValueError):
                factor.parameters({"inputs": INPUTS, "rule": rule})
        with self.assertRaisesRegex(ValueError, "leaf"):
            factor.parameters({"inputs": {"recursive": {"factor_id": "COMB.CONDITION"}}, "rule": {"input": "recursive", "op": "eq", "value": 1}})
        with self.assertRaisesRegex(ValueError, "finite"):
            registry.get("COMB.SCORE", "1.0.0").parameters({"inputs": INPUTS, "weights": {"m": float("inf"), "e": 1}})

    def test_input_availability_cannot_be_backdated(self):
        registry = default_registry()
        registry.register_pack(FactorPack("test", "1", (DelayedMomentum(),)))
        factor = registry.get("COMB.SCORE", "1.0.0")
        params = factor.parameters({"inputs": {"slow": {"factor_id": "TEST.DELAYED", "parameters": {"lookback": 1}}}, "weights": {"slow": 1}})
        result = compute_factor(factor, bars(), params)
        self.assertEqual(result["available_at"][0], bars()["datetime"][0] + timedelta(hours=1))
        with self.assertRaisesRegex(ValueError, "bar close"):
            FactorResearchEngine().evaluate(bars(), result, ExplicitUniverse(("A",)).mask(bars()), (1,), 2)

    def test_experiment_lineage_repeat_and_weight_change_identity(self):
        class Provider:
            def load(self, request):
                return DataBatch(bars(), DataSnapshot("combination-test-v1", "test", "raw", ()))

        cfg = ExperimentConfig("组合集成", DataRequest(("A",), Timeframe.DAILY, date(2025,1,1), date(2025,1,6)),
            "COMB.SCORE", parameters={"inputs": INPUTS, "weights": {"m": 2, "e": 0.5}}, horizons=(1,))
        with tempfile.TemporaryDirectory() as tmp:
            runner = ExperimentRunner(Provider(), default_registry(), ExplicitUniverse(("A",)), LocalExperimentStore(Path(tmp)))
            a, b = runner.run(cfg), runner.run(cfg)
            self.assertEqual(a.experiment_id, b.experiment_id)
            self.assertEqual(a.metrics, b.metrics)
            record = load_record(a.artifact_path / "experiment.json")
            self.assertEqual(len(record["manifest"]["combination_inputs"]), 2)
            self.assertTrue(all(i["code_hash"] and i["definition"]["version"] == "1.0.0" for i in record["manifest"]["combination_inputs"]))
            self.assertIn("因子组合", (a.artifact_path / "report.md").read_text())
            changed = runner.run(replace(cfg, parameters={"inputs": INPUTS, "weights": {"m": 3, "e": 0.5}}))
            self.assertNotEqual(a.experiment_id, changed.experiment_id)


if __name__ == "__main__":
    unittest.main()
