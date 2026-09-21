import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import polars as pl

import test_core
from test_strategy_package import package

from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.storage.codec import digest, encode
from quantlab.trading.strategy_comparison import compare_strategy_packages, compare_strategy_runs
from quantlab.trading.strategy_package import compile_strategy
from quantlab.workbench.jobs import execute, prepare


class StrategyComparisonTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.CoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.output = self.fixture.root / "comparison-runs"
        self.output.mkdir()

    def run_package(self, value=None):
        compiled = compile_strategy(value or package())
        return execute(prepare(compiled["spec"]), self.fixture.root, self.output)

    @staticmethod
    def metrics_by_name(result):
        return {row["metric"]: row for row in result["metrics"]}

    def test_package_comparison_normalizes_and_reports_no_difference(self):
        left = package()
        right = deepcopy(left)
        right["spec"]["execution"]["allow_st"] = False
        result = compare_strategy_packages(left, right)
        self.assertTrue(result["same_strategy_key"])
        self.assertTrue(result["same_version"])
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["left"]["package_hash"], result["right"]["package_hash"])
        self.assertIn("规范化配置内容相同", " ".join(result["warnings"]))

    def test_package_same_version_changed_content_warns_without_ranking(self):
        result = compare_strategy_packages(package(), package(max_position=0.5))
        self.assertTrue(result["same_strategy_key"])
        self.assertTrue(result["same_version"])
        self.assertIn("spec.portfolio.max_position", [row["path"] for row in result["changes"]])
        self.assertIn("版本未更新", " ".join(result["warnings"]))
        self.assertNotIn("winner", result)

    def test_same_config_runs_are_comparable_with_zero_deltas(self):
        left = self.run_package()
        right = self.run_package()
        result = compare_strategy_runs(self.output, left.run_id, right.run_id)
        self.assertEqual(result["format"], "niuniu-strategy-run-comparison-v1")
        self.assertEqual(result["scope"], "DESCRIPTIVE_ONLY")
        self.assertTrue(result["comparable"])
        self.assertEqual(result["blockers"], [])
        for row in result["metrics"]:
            if row["left"] is not None:
                self.assertEqual(row["delta"], 0, row)
        self.assertIn("signal_market_bytes", result["left"]["evidence_fingerprint"])

    def test_position_rule_change_remains_comparable_and_is_explicit(self):
        left = self.run_package(package(max_position=1.0))
        right = self.run_package(package(max_position=0.5))
        result = compare_strategy_runs(self.output, left.run_id, right.run_id)
        self.assertTrue(result["comparable"], result["blockers"])
        self.assertIn("spec.portfolio.max_position", [row["path"] for row in result["config_changes"]])
        self.assertIn("研究变量", " ".join(result["warnings"]))

    def test_securities_and_date_changes_are_incomparable(self):
        left = self.run_package()
        stock = package()
        stock["spec"]["symbols"] = stock["spec"]["symbols"][:-1]
        stock_run = self.run_package(stock)
        dated = package()
        dated["spec"]["end"] = "2025-01-09"
        date_run = self.run_package(dated)
        stock_result = compare_strategy_runs(self.output, left.run_id, stock_run.run_id)
        date_result = compare_strategy_runs(self.output, left.run_id, date_run.run_id)
        self.assertIn("securities_differ", stock_result["blockers"])
        self.assertIn("date_range_differ", date_result["blockers"])
        self.assertTrue(all(row["delta"] is None for row in stock_result["metrics"]))
        self.assertTrue(all(row["delta"] is None for row in date_result["metrics"]))

    def test_cost_change_is_incomparable(self):
        left = self.run_package()
        changed = package()
        changed["spec"]["execution"]["commission_bps"] = 8
        right = self.run_package(changed)
        result = compare_strategy_runs(self.output, left.run_id, right.run_id)
        self.assertFalse(result["comparable"])
        self.assertIn("execution_assumptions_or_costs_differ", result["blockers"])
        self.assertTrue(all(row["delta"] is None for row in result["metrics"]))

    def test_actual_market_byte_change_is_incomparable_despite_same_package(self):
        left = self.run_package()
        source = (self.fixture.root / "lake/silver/qfq_kline_daily"
                  / f"{self.fixture.symbols[0].replace('.', '_')}.parquet")
        pl.read_parquet(source).with_columns((pl.col("close") + 0.01).alias("close")).write_parquet(source)
        right = self.run_package()
        result = compare_strategy_runs(self.output, left.run_id, right.run_id)
        self.assertFalse(result["comparable"])
        self.assertIn("signal_market_bytes_differ", result["blockers"])
        self.assertIn("execution_market_bytes_differ", result["blockers"])

    def test_failed_and_package_less_archives_are_rejected(self):
        failed = self.run_package()
        failed_path = failed.artifact_path / "experiment.json"
        failed_record = json.loads(failed_path.read_text(encoding="utf-8"))
        failed_record["status"] = "failed"
        failed_path.write_text(encode(failed_record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not completed"):
            compare_strategy_runs(self.output, failed.run_id, failed.run_id)

        no_package = self.run_package()
        no_package_path = no_package.artifact_path / "experiment.json"
        no_package_record = json.loads(no_package_path.read_text(encoding="utf-8"))
        del no_package_record["manifest"]["strategy_package"]
        no_package_record["experiment_id"] = digest(no_package_record["manifest"])
        no_package_path.write_text(encode(no_package_record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no strategy package"):
            compare_strategy_runs(self.output, no_package.run_id, no_package.run_id)

    def test_corrupted_bytes_and_symlinks_are_rejected(self):
        damaged = self.run_package()
        (damaged.artifact_path / "bars.parquet").write_bytes(b"not parquet")
        with self.assertRaisesRegex(ValueError, "Unreadable archived execution bars"):
            compare_strategy_runs(self.output, damaged.run_id, damaged.run_id)

        linked = self.run_package()
        parent_bars = linked.artifact_path / "bars.parquet"
        record = json.loads((linked.artifact_path / "experiment.json").read_text(encoding="utf-8"))
        child_bars = self.output / record["children"][0]["run_id"] / "bars.parquet"
        parent_bars.unlink()
        try:
            os.symlink(child_bars, parent_bars)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            compare_strategy_runs(self.output, linked.run_id, linked.run_id)

    def test_path_escape_rejected_and_comparison_has_no_write_side_effect(self):
        left = self.run_package()
        right = self.run_package()
        before_left = snapshot_tree(self.output, left.run_id)
        before_right = snapshot_tree(self.output, right.run_id)
        names_before = sorted(str(path.relative_to(self.output)) for path in self.output.rglob("*"))
        compare_strategy_runs(self.output, left.run_id, right.run_id)
        self.assertEqual(before_left, snapshot_tree(self.output, left.run_id))
        self.assertEqual(before_right, snapshot_tree(self.output, right.run_id))
        self.assertEqual(names_before, sorted(str(path.relative_to(self.output)) for path in self.output.rglob("*")))
        with self.assertRaisesRegex(ValueError, "canonical UUID"):
            compare_strategy_runs(self.output, "../escape", right.run_id)
        with tempfile.TemporaryDirectory() as temporary:
            link = Path(temporary) / "output-link"
            try:
                os.symlink(self.output, link)
            except (OSError, NotImplementedError):
                return
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                compare_strategy_runs(link, left.run_id, right.run_id)


if __name__ == "__main__":
    unittest.main()
