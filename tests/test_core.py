import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import polars as pl
from polars.testing import assert_frame_equal

from quantlab.app import build_runner, default_registry
from quantlab.causal import align_available, assert_prefix_invariant
from quantlab.data.base import DataRequest, ExplicitUniverse
from quantlab.data.mqc import MQCParquetProvider
from quantlab.domain import Event, Timeframe, Zone
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.research import FactorResearchEngine
from quantlab.factors.builtin import CloseLocation, Momentum, base_quant_pack
from quantlab.factors.engine import compute_factor

TZ = ZoneInfo("Asia/Shanghai")


class LeakingMomentum(Momentum):
    def expression(self, parameters):
        return pl.col("close").shift(-1).over("symbol")


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.symbols = tuple(f"sh.{600000 + i}" for i in range(5))
        self.start = date(2025, 1, 1)
        self.end = date(2025, 1, 10)
        daily = self.root / "lake/bronze/provider=baostock/stock_kline_daily"
        minute = self.root / "lake/bronze/provider=baostock/stock_kline_min5"
        adjusted = self.root / "lake/silver/qfq_kline_daily"
        adjusted.mkdir(parents=True)
        daily.mkdir(parents=True)
        minute.mkdir(parents=True)
        for i, symbol in enumerate(self.symbols):
            rows = []
            for n in range(10):
                close = 10.0 * (1 + (i + 1) / 100) ** n
                rows.append({"date": self.start + timedelta(days=n), "code": symbol, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000, "amount": 1000 * close, "adjustflag": "3"})
            frame = pl.DataFrame(rows)
            frame.with_columns(*[(pl.col(c)*0.5).alias(c) for c in ('open','high','low','close')],
                pl.lit(0.5).alias('factor')).write_parquet(adjusted / f"{symbol.replace('.', '_')}.parquet")
            frame.write_parquet(daily / f"{symbol.replace('.', '_')}.parquet")
            frame.with_columns((pl.col("date").dt.strftime("%Y%m%d") + pl.lit("093500000")).alias("time")).write_parquet(minute / f"{symbol.replace('.', '_')}.parquet")
        self.request = DataRequest(self.symbols, Timeframe.DAILY, self.start, self.end)
        self.provider = MQCParquetProvider(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_parquet_normalization_snapshot_and_minute_clock(self):
        batch = self.provider.load(self.request)
        self.assertEqual(batch.bars.height, 50)
        self.assertEqual(batch.bars["datetime"][0].hour, 15)
        self.assertEqual(str(batch.bars.schema["datetime"].time_zone), "Asia/Shanghai")
        self.assertEqual(batch.snapshot, self.provider.load(self.request).snapshot)
        minute = self.provider.load(replace(self.request, timeframe=Timeframe.MIN5))
        self.assertEqual(minute.bars["datetime"][0].minute, 35)
        self.assertEqual(minute.bars["datetime"][0].hour, 9)
        self.assertNotEqual(batch.snapshot.snapshot_id, minute.snapshot.snapshot_id)

    def test_invalid_data_and_missing_symbols_fail(self):
        with self.assertRaises(FileNotFoundError):
            self.provider.load(replace(self.request, symbols=("sh.699999",)))
        path = self.root / "lake/bronze/provider=baostock/stock_kline_daily/sh_600000.parquet"
        original = pl.read_parquet(path)
        before = self.provider.load(self.request).snapshot.snapshot_id
        original.with_columns((pl.col("amount") + 1).alias("amount")).write_parquet(path)
        self.assertNotEqual(before, self.provider.load(self.request).snapshot.snapshot_id)
        pl.concat([original, original.head(1)]).write_parquet(path)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.provider.load(self.request)
        original.with_columns(pl.lit(-1).alias("close")).write_parquet(path)
        with self.assertRaisesRegex(ValueError, "Invalid OHLCV"):
            self.provider.load(self.request)

    def test_registry_parameters_and_pack_atomicity(self):
        registry = default_registry()
        before = registry.describe()
        with self.assertRaises(ValueError):
            registry.register_pack(base_quant_pack())
        self.assertEqual(registry.describe(), before)
        with self.assertRaises(ValueError):
            registry.get("BASE.MOMENTUM", "missing")
        for parameters in [{"lookback": 0}, {"lookback": True}, {"lookback": 1.2}, {"unknown": 2}]:
            with self.assertRaises(ValueError):
                Momentum().parameters(parameters)

    def test_factor_paths_do_not_cross_symbols(self):
        bars = self.provider.load(self.request).bars
        values = compute_factor(Momentum(), bars, {"lookback": 2})
        self.assertEqual(values["value"].null_count(), 10)
        self.assertAlmostEqual(values.filter(pl.col("symbol") == self.symbols[0])["value"][2], 1.01**2 - 1)
        locations = compute_factor(CloseLocation(), bars, {})
        self.assertTrue((locations["value"] == 0.5).all())

    def test_causal_prefix_check_detects_future_shift(self):
        bars = self.provider.load(self.request).bars
        cutoffs = [datetime(2025, 1, n, 15, tzinfo=TZ) for n in (4, 7)]
        assert_prefix_invariant(Momentum(), bars, {"lookback": 2}, cutoffs)
        assert_prefix_invariant(CloseLocation(), bars, {}, cutoffs)
        with self.assertRaises(AssertionError):
            assert_prefix_invariant(LeakingMomentum(), bars, {}, cutoffs)

    def test_multitimeframe_never_uses_unfinished_daily(self):
        low = pl.DataFrame({"symbol": ["A", "A", "B"], "available_at": [datetime(2025, 1, 2, 10, 30, tzinfo=TZ), datetime(2025, 1, 2, 15, tzinfo=TZ), datetime(2025, 1, 2, 15, tzinfo=TZ)]})
        high = pl.DataFrame({"symbol": ["A", "A"], "available_at": [datetime(2025, 1, 1, 15, tzinfo=TZ), datetime(2025, 1, 2, 15, tzinfo=TZ)], "state": [1, 2]})
        self.assertEqual(align_available(low, high)["state"].to_list(), [1, 2, None])

    def test_research_known_returns_and_undefined_correlation(self):
        bars = self.provider.load(self.request).bars
        values = compute_factor(Momentum(), bars, {"lookback": 2})
        mask = ExplicitUniverse(self.symbols).mask(bars)
        metrics, observations = FactorResearchEngine().evaluate(bars, values, mask, (1,), 5)
        self.assertEqual(metrics["1"]["observations"], 35)
        self.assertAlmostEqual(metrics["1"]["mean_forward_return"], 0.03)
        self.assertAlmostEqual(metrics["1"]["ic"], 0.999982, places=4)
        self.assertAlmostEqual(metrics["1"]["rank_ic"], 1.0)
        self.assertEqual(observations.filter(pl.col("datetime").dt.date() == self.end)["forward_1"].null_count(), 5)
        metrics, _ = FactorResearchEngine().evaluate(bars, values.with_columns(pl.lit(1.0).alias("value")), mask, (1,), 5)
        self.assertIsNone(metrics["1"]["ic"])
        self.assertEqual(metrics["1"]["quantile_returns"], [])

    def test_delayed_factor_cannot_be_backdated(self):
        bars = self.provider.load(self.request).bars
        values = compute_factor(Momentum(), bars, {"lookback": 2}).with_columns((pl.col("available_at") + pl.duration(hours=1)).alias("available_at"))
        with self.assertRaisesRegex(ValueError, "available at their bar close"):
            FactorResearchEngine().evaluate(bars, values, ExplicitUniverse(self.symbols).mask(bars), (1,), 5)

    def test_full_workflow_is_reproducible_and_indexed(self):
        runner = build_runner(self.root, self.root / "output", self.symbols)
        config = ExperimentConfig("known synthetic returns", self.request, "BASE.MOMENTUM", parameters={"lookback": 2}, horizons=(1, 3))
        first, second = runner.run(config), runner.run(config)
        self.assertEqual(first.experiment_id, second.experiment_id)
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(first.metrics, second.metrics)
        assert_frame_equal(pl.read_parquet(first.artifact_path / "observations.parquet"), pl.read_parquet(second.artifact_path / "observations.parquet"), check_exact=True)
        with duckdb.connect(str(self.root / "output/experiments.duckdb"), read_only=True) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM experiments WHERE status='completed'").fetchone()[0], 2)
        self.assertIn("未扣成本", (first.artifact_path / "report.md").read_text())

    def test_research_aggregation_is_independent_of_input_order(self):
        bars = self.provider.load(self.request).bars
        values = compute_factor(Momentum(), bars, {"lookback": 2})
        mask = ExplicitUniverse(self.symbols).mask(bars)
        engine = FactorResearchEngine()
        first, details = engine.evaluate(bars, values, mask, (1, 3), 5)
        second, shuffled = engine.evaluate(bars.reverse(), values.reverse(), mask.reverse(), (1, 3), 5)
        self.assertEqual(first, second)
        assert_frame_equal(details, shuffled, check_exact=True)

    def test_failure_is_saved(self):
        runner = build_runner(self.root, self.root / "output", self.symbols)
        config = ExperimentConfig("invalid factor", self.request, "MISSING")
        with self.assertRaisesRegex(ValueError, "Unknown factor"):
            runner.run(config)
        records = list((self.root / "output").glob("*/experiment.json"))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text())
        self.assertEqual(record["status"], "failed")
        self.assertIn("Unknown factor", record["error"])

    def test_domain_time_invariants(self):
        aware = datetime(2025, 1, 1, tzinfo=TZ)
        with self.assertRaisesRegex(ValueError, "timezone aware"):
            Event("e", "f", "A", Timeframe.DAILY, datetime(2025, 1, 1), aware)
        with self.assertRaisesRegex(ValueError, "precede"):
            Event("e", "f", "A", Timeframe.DAILY, aware, aware - timedelta(days=1))
        with self.assertRaisesRegex(ValueError, "bounds"):
            Zone("z", "range", "A", Timeframe.DAILY, aware, aware, 20, 10)


if __name__ == "__main__":
    unittest.main()
