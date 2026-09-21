import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import polars as pl

import test_core
from test_strategy_package import package

from quantlab.storage.codec import digest, encode
from quantlab.trading import strategy_run_catalog as catalog
from quantlab.trading.strategy_package import compile_strategy
from quantlab.workbench.jobs import execute, prepare


class StrategyRunCatalogTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.CoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.output = self.fixture.root / "catalog-runs"
        self.output.mkdir()

    def archive(self):
        compiled = compile_strategy(package())
        return execute(prepare(compiled["spec"]), self.fixture.root, self.output)

    @staticmethod
    def fingerprint(root):
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()
        }

    @staticmethod
    def write_record(root, run_id, *, kind="factor", status="completed", manifest=None):
        manifest = {} if manifest is None else manifest
        folder = root / run_id
        folder.mkdir()
        (folder / "experiment.json").write_text(encode({
            "run_id": run_id,
            "experiment_id": digest(manifest),
            "created_at": "2026-09-21T00:00:00+00:00",
            "status": status,
            "kind": kind,
            "manifest": manifest,
        }), encoding="utf-8")

    def test_real_synthetic_archive_lists_then_gets_without_source_reads_or_writes(self):
        run = self.archive()
        before = self.fingerprint(self.output)
        with patch.object(pl, "read_parquet", side_effect=AssertionError("list must not read Parquet")):
            listed = catalog.list_strategy_runs(self.output)
        self.assertEqual([row["run_id"] for row in listed["runs"]], [run.run_id])
        self.assertEqual(listed["total_candidates"], 2)
        self.assertEqual(listed["non_strategy"], 1)
        self.assertEqual(listed["runs"][0]["verification"], "metadata_only")
        self.assertNotIn("execution_metrics", listed["runs"][0])
        with patch("quantlab.data.mqc.MQCParquetProvider.load", side_effect=AssertionError("data root read")):
            detail = catalog.get_strategy_run(self.output, run.run_id)
        self.assertEqual(detail["run_id"], run.run_id)
        self.assertEqual(detail["package"], compile_strategy(package())["package"])
        self.assertEqual(detail["package_identity"]["package_hash"], listed["runs"][0]["package_hash"])
        self.assertEqual(detail["verification"], "archive_internal_consistency")
        self.assertEqual(detail["scope"], "DESCRIPTIVE_ONLY")
        self.assertEqual(before, self.fingerprint(self.output))

    def test_query_pagination_is_literal_and_offsets_point_to_next_candidate(self):
        first = self.archive()
        second = self.archive()
        offset = 0
        found = []
        pages = 0
        while offset is not None:
            page = catalog.list_strategy_runs(self.output, query="TESTS.F3B", offset=offset, limit=1)
            found.extend(row["run_id"] for row in page["runs"])
            pages += 1
            self.assertEqual(page["has_more"], page["next_offset"] is not None)
            offset = page["next_offset"]
        self.assertEqual(set(found), {first.run_id, second.run_id})
        self.assertGreaterEqual(pages, 2)
        self.assertEqual(catalog.list_strategy_runs(self.output, query="[", limit=20)["runs"], [])
        for kwargs in ({"query": "x" * 201}, {"offset": True}, {"offset": 100001}, {"limit": False}, {"limit": 21}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                catalog.list_strategy_runs(self.output, **kwargs)

    def test_scan_stops_at_one_hundred_candidates_and_reports_true_next_offset(self):
        root = self.fixture.root / "scan-limit"
        root.mkdir()
        for value in range(1, 102):
            self.write_record(root, str(UUID(int=value)))
        first = catalog.list_strategy_runs(root)
        self.assertEqual(first["total_candidates"], 101)
        self.assertEqual(first["scanned"], 100)
        self.assertEqual(first["non_strategy"], 100)
        self.assertEqual(first["next_offset"], 100)
        self.assertTrue(first["has_more"])
        last = catalog.list_strategy_runs(root, offset=first["next_offset"])
        self.assertEqual(last["scanned"], 1)
        self.assertIsNone(last["next_offset"])

    def test_bad_record_failed_run_and_old_or_factor_records_are_visible(self):
        failed = self.archive()
        failed_path = failed.artifact_path / "experiment.json"
        failed_record = json.loads(failed_path.read_text(encoding="utf-8"))
        failed_record["status"] = "failed"
        failed_path.write_text(encode(failed_record), encoding="utf-8")
        bad_id = str(uuid4())
        bad = self.output / bad_id
        bad.mkdir()
        (bad / "experiment.json").write_text("not-json", encoding="utf-8")
        old_id = str(uuid4())
        self.write_record(self.output, old_id, kind="execution", manifest={"config": {}})

        result = catalog.list_strategy_runs(self.output)
        self.assertIn(failed.run_id, [row["run_id"] for row in result["runs"] if row["status"] == "failed"])
        self.assertGreaterEqual(result["non_strategy"], 2)  # factor child plus old package-less execution
        self.assertEqual(result["errors"], [{"run_id": bad_id, "reason": "unreadable_experiment_json"}])
        self.assertTrue(result["incomplete"])
        with self.assertRaisesRegex(ValueError, "not completed"):
            catalog.get_strategy_run(self.output, failed.run_id)

    def test_symlink_uuid_size_and_root_input_guards(self):
        large_id = str(uuid4())
        large = self.output / large_id
        large.mkdir()
        with (large / "experiment.json").open("wb") as stream:
            stream.seek(8 * 1024 * 1024)
            stream.write(b"x")
        link_id = str(uuid4())
        target = self.fixture.root / "outside-candidate"
        target.mkdir()
        try:
            os.symlink(target, self.output / link_id)
        except (OSError, NotImplementedError):
            link_id = None
        result = catalog.list_strategy_runs(self.output)
        reasons = {row["run_id"]: row["reason"] for row in result["errors"]}
        self.assertEqual(reasons[large_id], "experiment_json_too_large")
        if link_id is not None:
            self.assertEqual(reasons[link_id], "symlink_candidate")
        with self.assertRaisesRegex(ValueError, "canonical UUID"):
            catalog.get_strategy_run(self.output, "../escape")
        root_link = self.fixture.root / "catalog-link"
        try:
            os.symlink(self.output, root_link)
        except (OSError, NotImplementedError):
            return
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            catalog.list_strategy_runs(root_link)

    def test_change_after_deep_comparison_is_rejected(self):
        run = self.archive()
        real_compare = catalog.compare_strategy_runs

        def compare_then_change(*args):
            result = real_compare(*args)
            path = run.artifact_path / "experiment.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["manifest"]["strategy_package"]["package"]["name"] = "changed-after-comparison"
            path.write_text(encode(record), encoding="utf-8")
            return result

        with patch.object(catalog, "compare_strategy_runs", side_effect=compare_then_change):
            with self.assertRaisesRegex(ValueError, "changed after archive verification"):
                catalog.get_strategy_run(self.output, run.run_id)


if __name__ == "__main__":
    unittest.main()
