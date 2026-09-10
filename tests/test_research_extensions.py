import math
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.causal import assert_prefix_invariant
from quantlab.data.base import ExplicitUniverse
from quantlab.experiments.research import FactorResearchEngine, information_ratio
from quantlab.factors.builtin import ATR, DirectionalEfficiency, ReturnVolatility
from quantlab.factors.engine import compute_factor


def bars_for(symbol, closes, highs=None, lows=None):
    times = [datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=n) for n in range(len(closes))]
    return pl.DataFrame({
        "symbol": [symbol] * len(closes), "datetime": times, "available_at": times,
        "timeframe": ["1d"] * len(closes), "close": [float(c) for c in closes],
        "high": highs or [float(c + 1) for c in closes],
        "low": lows or [float(c - 1) for c in closes],
    })


def evaluate(bars, values=None, horizons=(1, 2), quantiles=2):
    if values is None:
        values = bars.select("symbol", "datetime", "available_at", pl.lit(1.0).alias("value"))
    return FactorResearchEngine().evaluate(bars, values, ExplicitUniverse(tuple(bars["symbol"].unique())).mask(bars), horizons, quantiles)


class ResearchExtensionTests(unittest.TestCase):
    def test_factor_formulas_warmup_and_symbol_isolation(self):
        bars = pl.concat([bars_for("A", [100, 110, 99, 99, 108]), bars_for("B", [200] * 5)])
        expected = {ATR: 11.5, ReturnVolatility: math.sqrt(0.02), DirectionalEfficiency: -1 / 21}
        for kind, first_value in expected.items():
            with self.subTest(factor=kind.__name__):
                result = compute_factor(kind(), bars, {"lookback": 2})
                self.assertEqual(result["value"].null_count(), 4)
                self.assertAlmostEqual(result.filter(pl.col("symbol") == "A")["value"][2], first_value)
                flat = result.filter(pl.col("symbol") == "B")["value"].drop_nulls()
                self.assertEqual(flat.to_list(), [2.0 if kind is ATR else 0.0] * 3)
                assert_prefix_invariant(kind(), bars, {"lookback": 2}, [bars["datetime"][2], bars["datetime"][3]])
        with self.assertRaisesRegex(ValueError, ">= 2"):
            ReturnVolatility().parameters({"lookback": 1})

    def test_excursions_exclude_current_bar_and_require_full_future(self):
        bars = pl.concat([
            bars_for("A", [100, 110, 99, 105], [1000.0, 112.0, 105.0, 108.0], [1.0, 108.0, 90.0, 97.0]),
            bars_for("B", [200] * 4),
        ])
        metrics, frame = evaluate(bars)
        a = frame.filter(pl.col("symbol") == "A")
        self.assertAlmostEqual(a["mfe_2"][0], 0.12)
        self.assertAlmostEqual(a["mae_2"][0], -0.10)
        self.assertEqual(a["mae_1"][0], 0.0)
        self.assertEqual(a["mfe_1"][1], 0.0)
        self.assertEqual(a["mfe_2"].tail(2).to_list(), [None, None])
        self.assertEqual(a["mae_2"].tail(2).to_list(), [None, None])
        self.assertEqual(metrics["2"]["observations"], 4)
        expected_mfe = (0.12 + 0.0 + 0.005 + 0.005) / 4
        self.assertAlmostEqual(metrics["2"]["mean_mfe"], expected_mfe)

    def test_information_ratio_has_explicit_sample_std_and_null_rules(self):
        self.assertAlmostEqual(information_ratio(pl.Series([0.1, 0.2, 0.3, float("nan")])), 2.0)
        for values in [[], [0.1], [0.2, 0.2], [float("nan")]]:
            self.assertIsNone(information_ratio(pl.Series(values, dtype=pl.Float64)))

    def test_long_short_uses_only_matched_dates_with_ties(self):
        bars = pl.concat([bars_for(str(i), [100, 100 * (1 + i / 100), 100 * (1 + i / 100)**2]) for i in range(10)])
        values = bars.select("symbol", "datetime", "available_at",
            pl.when((pl.col("datetime").dt.day() == 1) & (pl.col("symbol").cast(pl.Int64) < 8))
            .then(0).otherwise(pl.col("symbol").cast(pl.Int64)).cast(pl.Float64).alias("value"))
        metrics, _ = evaluate(bars, values, (1,), 3)
        self.assertEqual(metrics["1"]["long_short_dates"], 1)
        self.assertAlmostEqual(metrics["1"]["long_short_spread"], 0.08 - 0.015)

    def test_no_valid_factor_or_future_returns_yields_null_metrics(self):
        bars = bars_for("A", [100, 101])
        values = bars.select("symbol", "datetime", "available_at", pl.lit(None, dtype=pl.Float64).alias("value"))
        metrics, _ = evaluate(bars, values, (3,))
        self.assertEqual(metrics["3"]["observations"], 0)
        for key in ("mean_mfe", "mean_mae", "icir", "rank_icir", "long_short_spread"):
            self.assertIsNone(metrics["3"][key])


if __name__ == "__main__":
    unittest.main()
