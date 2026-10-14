import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.causal import audit_prefix_invariance, audit_registry
from quantlab.factors.base import FactorDefinition
from quantlab.factors.builtin import Momentum, base_quant_pack
from quantlab.factors.registry import FactorRegistry


def bars(days=60, symbols=("A", "B")):
    times = [datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=i) for i in range(days)]
    rows = []
    for index, symbol in enumerate(symbols):
        for step, moment in enumerate(times):
            price = 10.0 + index + (step % 7) * 0.3 + step * 0.05
            rows.append({"symbol": symbol, "datetime": moment, "available_at": moment, "timeframe": "1d",
                         "open": price, "high": price + 1, "low": price - 1, "close": price,
                         "volume": 1000.0 + step, "turnover": 10000.0 + step})
    return pl.DataFrame(rows)


class LeakNextClose(Momentum):
    definition = replace(Momentum.definition, factor_id="TEST.LEAK_NEXT")

    def expression(self, parameters):
        return pl.col("close").shift(-1).over("symbol") / pl.col("close") - 1


class WholeSampleZScore(Momentum):
    definition = replace(Momentum.definition, factor_id="TEST.WHOLE_SAMPLE")

    def expression(self, parameters):
        close = pl.col("close")
        return (close - close.mean().over("symbol")) / close.std().over("symbol")


class NeedsParameters(Momentum):
    definition = replace(Momentum.definition, factor_id="TEST.NEEDS_PARAMETERS")

    def parameters(self, supplied):
        raise ValueError("inputs required")


class AlwaysNull(Momentum):
    definition = replace(Momentum.definition, factor_id="TEST.ALWAYS_NULL")

    def expression(self, parameters):
        return pl.lit(None, dtype=pl.Float64)


class Crashes(Momentum):
    definition = replace(Momentum.definition, factor_id="TEST.CRASHES")

    def expression(self, parameters):
        raise RuntimeError("boom")


class CausalAuditTests(unittest.TestCase):
    def test_causal_factor_passes_every_check(self):
        report = audit_prefix_invariance(Momentum(), bars())
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["checks"]), 6)
        self.assertTrue(all(c["mismatches"] == 0 and c["compared_values"] > 0 for c in report["checks"]))

    def test_one_bar_lookahead_is_caught_by_both_modes(self):
        report = audit_prefix_invariance(LeakNextClose(), bars())
        self.assertEqual(report["status"], "FAIL")
        failed = {c["mode"] for c in report["checks"] if c["mismatches"]}
        self.assertEqual(failed, {"truncate", "tamper_future"})
        first = next(c["first_mismatch"] for c in report["checks"] if c["mismatches"])
        self.assertIn(first["symbol"], {"A", "B"})

    def test_whole_sample_normalisation_is_caught(self):
        self.assertEqual(audit_prefix_invariance(WholeSampleZScore(), bars())["status"], "FAIL")

    def test_all_null_output_is_not_reported_as_a_pass(self):
        report = audit_prefix_invariance(AlwaysNull(), bars())
        self.assertEqual(report["status"], "SKIP")
        self.assertIn("all_null_output", report["reason"])

    def test_unusable_factors_are_reported_not_raised(self):
        self.assertEqual(audit_prefix_invariance(NeedsParameters(), bars())["status"], "SKIP")
        self.assertEqual(audit_prefix_invariance(Crashes(), bars())["status"], "ERROR")
        self.assertEqual(audit_prefix_invariance(Momentum(), bars(days=5))["status"], "SKIP")

    def test_registry_sweep_and_selection(self):
        registry = FactorRegistry()
        registry.register_pack(base_quant_pack())
        statuses = {r["factor_id"]: r["status"] for r in audit_registry(registry, bars(), factor_ids={"BASE.MOMENTUM", "BASE.ATR"})}
        self.assertEqual(statuses, {"BASE.MOMENTUM": "PASS", "BASE.ATR": "PASS"})


if __name__ == "__main__":
    unittest.main()
