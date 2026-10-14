import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from quantlab.causal import audit_registry
from quantlab.factors import gtja
from quantlab.factors.registry import FactorRegistry

SOURCE = Path(gtja.__file__).with_name("gtja191")


def bars(days=120, symbols=6, seed=7, adj=1.0):
    rng = np.random.default_rng(seed)
    times = [datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=i) for i in range(days)]
    rows = []
    for s in range(symbols):
        close = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.02, days)))
        open_ = close * (1 + rng.normal(0, 0.005, days))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, days)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, days)))
        volume = rng.integers(100000, 1000000, days).astype(float)
        for i, moment in enumerate(times):
            rows.append({"symbol": f"S{s}", "datetime": moment, "available_at": moment, "timeframe": "1d", "open": open_[i],
                         "high": high[i], "low": low[i], "close": close[i], "volume": volume[i],
                         "turnover": volume[i] * (high[i] + low[i]) / 2, "adj_factor": adj})
    return pl.DataFrame(rows)


def factor(key):
    return next(f for f in gtja.gtja_pack().factors if f.definition.factor_id == f"GTJA191.{key.upper()}")


class Gtja191Tests(unittest.TestCase):
    def test_pack_offers_exactly_the_supported_factors(self):
        pack = gtja.gtja_pack()
        ids = [f.definition.factor_id for f in pack.factors]
        self.assertEqual(len(ids), 183)
        self.assertEqual(len(set(ids)), 183)
        self.assertEqual(len(gtja.UNSUPPORTED), 8)
        for key in gtja.UNSUPPORTED:
            self.assertNotIn(f"GTJA191.{key.upper()}", ids)
        self.assertTrue(all(f.definition.timeframes and len(f.definition.timeframes) == 1 for f in pack.factors))
        registry = FactorRegistry()
        registry.register_pack(pack)

    def test_simple_factors_match_closed_forms(self):
        data = bars()
        out = factor("gtja_014").compute(data, {}).sort("symbol", "datetime")
        expected = data.sort("symbol", "datetime").with_columns((pl.col("close") - pl.col("close").shift(5).over("symbol")).alias("e"))
        np.testing.assert_allclose(out["value"].to_numpy()[5:30], expected["e"].to_numpy()[5:30])
        self.assertTrue(out["value"][:5].is_null().all())
        out = factor("gtja_015").compute(data, {}).sort("symbol", "datetime")
        expected = data.sort("symbol", "datetime").with_columns((pl.col("open") / pl.col("close").shift(1).over("symbol") - 1).alias("e"))
        np.testing.assert_allclose(out["value"].to_numpy()[1:40], expected["e"].to_numpy()[1:40])
        out = factor("gtja_100").compute(data, {}).sort("symbol", "datetime")
        expected = data.sort("symbol", "datetime").with_columns(pl.col("volume").rolling_std(20).over("symbol").alias("e"))
        np.testing.assert_allclose(out["value"].to_numpy()[19:60], expected["e"].to_numpy()[19:60])

    def test_values_are_independent_of_row_order_and_extra_columns(self):
        data = bars(days=90)
        for key in ("gtja_001", "gtja_020", "gtja_081"):
            a = factor(key).compute(data, {}).sort("symbol", "datetime")
            b = factor(key).compute(data.sample(fraction=1.0, shuffle=True, seed=3).with_columns(pl.lit(1).alias("extra")), {}).sort("symbol", "datetime")
            np.testing.assert_allclose(a["value"].fill_null(-9e9).to_numpy(), b["value"].fill_null(-9e9).to_numpy())

    def test_cross_section_factors_depend_on_the_symbols_supplied(self):
        data = bars(days=60)
        full = factor("gtja_001").compute(data, {}).sort("symbol", "datetime")
        part = factor("gtja_001").compute(data.filter(pl.col("symbol").is_in(["S0", "S1", "S2"])), {}).sort("symbol", "datetime")
        both = full.filter(pl.col("symbol") == "S0")["value"].drop_nulls().to_numpy()
        alone = part.filter(pl.col("symbol") == "S0")["value"].drop_nulls().to_numpy()
        self.assertFalse(np.allclose(both, alone))  # documented: ranks use the supplied cross section

    def test_vwap_factors_need_valid_adjustment_and_turnover(self):
        vwap_key = next(f.key for f in gtja.gtja_pack().factors if "vwap" in f.need)
        with self.assertRaises(ValueError):
            factor(vwap_key).compute(bars(days=40, adj=0.0), {})
        broken = bars(days=40).with_columns(pl.when(pl.col("symbol") == "S0").then(None).otherwise(pl.col("turnover")).alias("turnover"))
        with self.assertRaises(ValueError):
            factor(vwap_key).compute(broken, {})

    def test_unavailable_inputs_and_parameters_are_refused(self):
        data = bars(days=30).with_columns((pl.col("datetime") + pl.duration(days=1)).alias("available_at"))
        with self.assertRaises(ValueError):
            factor("gtja_014").compute(data, {})
        with self.assertRaises(ValueError):
            factor("gtja_014").compute(bars(days=30), {"window": 3})

    def test_no_lookahead_on_a_representative_subset(self):
        registry = FactorRegistry()
        registry.register_pack(gtja.gtja_pack())
        keys = ["gtja_001", "gtja_014", "gtja_017", "gtja_020", "gtja_081", "gtja_100", "gtja_191"]
        report = audit_registry(registry, bars(days=200), factor_ids=[f"GTJA191.{k.upper()}" for k in keys])
        statuses = {row["factor_id"]: row["status"] for row in report}
        self.assertEqual(set(statuses.values()), {"PASS"}, statuses)

    def test_provenance_documents_licence_commit_and_every_omission(self):
        text = (SOURCE / "PROVENANCE.md").read_text()
        self.assertIn("5cf7e83637b85e4f855daec16099148b358b89b3", text)
        self.assertIn("MIT", (SOURCE / "LICENSE_AURUMQ").read_text())
        for key in gtja.UNSUPPORTED:
            self.assertIn(key.split("_")[1], text)
        for path in SOURCE.glob("batch_*.py"):
            self.assertNotIn("aurumq_rl", path.read_text())


if __name__ == "__main__":
    unittest.main()
