import statistics
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from quantlab.app import default_registry
from quantlab.data.base import ExplicitUniverse
from quantlab.factors.engine import compute_factor
from quantlab.factors.retail_crowding import AmountShock20, RetailCrowdingV1, VolumeShock20
from scripts.research.retail_crowding_v1 import (
    QuantityAwareResearchUniverse, build_family, inference_resolution, load_spec,
)


def bars(days=35):
    start = datetime(2026, 1, 1, 15)
    rows = []
    for symbol, offset in (("sh.600000", 0.0), ("sz.000001", 10.0)):
        for i in range(days):
            close = 100 + offset + i * 0.8 + (i % 4) * 0.2
            rows.append({
                "symbol": symbol, "datetime": start + timedelta(days=i),
                "available_at": start + timedelta(days=i), "timeframe": "1d",
                "open": close - 0.2, "high": close + 0.5, "low": close - 0.5, "close": close,
                "volume": 1000.0 + i * 17 + offset,
                "turnover": 100000.0 + i * 1234 + offset * 100,
                "adj_factor": 1.0,
            })
    return pl.DataFrame(rows).sort("symbol", "datetime")


def prior_z(values, index, window=20):
    prior = values[index-window:index]
    std = statistics.pstdev(prior)
    return None if std <= 1e-12 else (values[index] - statistics.mean(prior)) / std


class RetailCrowdingTests(unittest.TestCase):
    def test_shocks_use_prior_twenty_not_current(self):
        frame = bars()
        one = frame.filter(pl.col("symbol") == "sh.600000")
        index = 24
        for factor, column in ((VolumeShock20(), "volume"), (AmountShock20(), "turnover")):
            values = compute_factor(factor, frame, {}).filter(pl.col("symbol") == "sh.600000")["value"].to_list()
            expected = prior_z(one[column].to_list(), index)
            self.assertAlmostEqual(values[index], expected, places=12)
            self.assertTrue(all(v is None for v in values[:20]))

    def test_crowding_is_equal_weighted_prior_z_and_prefix_invariant(self):
        frame = bars()
        factor = RetailCrowdingV1()
        values = compute_factor(factor, frame, {})
        one = frame.filter(pl.col("symbol") == "sh.600000")
        closes = one["close"].to_list()
        mom = [None] * 5 + [closes[i] / closes[i-5] - 1 for i in range(5, len(closes))]
        index = 30
        expected = statistics.fmean([
            prior_z(mom, index), prior_z(one["volume"].to_list(), index),
            prior_z(one["turnover"].to_list(), index),
        ])
        actual = values.filter(pl.col("symbol") == "sh.600000")["value"][index]
        self.assertAlmostEqual(actual, expected, places=12)
        future = frame.tail(2).with_columns(
            pl.col("datetime") + timedelta(days=100),
            pl.col("available_at") + timedelta(days=100),
            pl.col("close") * 100, pl.col("volume") * 100, pl.col("turnover") * 100,
        )
        expanded = compute_factor(factor, pl.concat([frame, future]).sort("symbol", "datetime"), {})
        original = values.select("symbol", "datetime", "available_at", "value")
        prefix = expanded.filter(pl.col("datetime") <= frame["datetime"].max()).select(original.columns)
        assert_frame_equal(prefix.sort("symbol", "datetime"), original.sort("symbol", "datetime"))

    def test_nullable_quantity_rows_stay_on_timeline_but_are_ineligible(self):
        frame = bars(3).with_row_index("_row").with_columns(
            pl.when(pl.col("_row") == 0).then(None).otherwise(pl.col("volume")).alias("volume"),
            pl.when(pl.col("_row") == 4).then(None).otherwise(pl.col("turnover")).alias("turnover"),
        ).drop("_row")
        universe = QuantityAwareResearchUniverse(ExplicitUniverse(("sh.600000", "sz.000001")))
        mask = universe.mask(frame).sort("symbol", "datetime")
        self.assertEqual(mask.height, frame.height)
        self.assertFalse(mask["eligible"][0])
        self.assertFalse(mask["eligible"][4])
        self.assertEqual(mask["eligible"].sum(), frame.height - 2)

    def test_registry_and_frozen_family_match_reference(self):
        registry = default_registry()
        self.assertEqual(registry.get("RETAIL.CROWDING_V1", "1.0.0").definition.factor_id, "RETAIL.CROWDING_V1")
        spec = load_spec()
        self.assertEqual(spec["version"], "1.0.1")
        self.assertEqual(spec["evaluation"]["permutation"]["resamples"], 9999)
        resolution = inference_resolution(spec)
        self.assertEqual(resolution["planned_tests"], 240)
        self.assertTrue(resolution["sufficient"])
        with self.assertRaisesRegex(ValueError, "version 1.0.1"):
            load_spec(Path(__file__).parents[1] / "docs/reference/retail-crowding-v1.json")
        symbols = tuple(f"sh.60{i:04d}" for i in range(10))
        plan, configs, split = build_family(spec, symbols)
        self.assertEqual(len(plan["trials"]), 8)
        self.assertEqual(tuple(configs["retail_crowding_v1"].horizons), (1, 3, 5, 10, 20))
        self.assertEqual(configs["retail_crowding_v1"].quantiles, 10)
        self.assertEqual(split.train_end.isoformat(), "2018-12-31")
        self.assertEqual(split.valid_end.isoformat(), "2022-12-31")
        self.assertTrue(all(t["study"]["kind"] == "holdout" for t in plan["trials"]))
        self.assertEqual(plan["alpha"], 0.05)


if __name__ == "__main__":
    unittest.main()
