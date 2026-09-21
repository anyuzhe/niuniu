import hashlib
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

import test_core
from test_strategy_package import package

from quantlab.storage.codec import encode
from quantlab.trading import strategy_run_catalog as catalog
from quantlab.trading.strategy_package import compile_strategy
from quantlab.workbench.jobs import execute, prepare


class StrategyRevisionSourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.CoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.output = self.fixture.root / "revision-runs"
        self.output.mkdir()

    def archive(self, pkg=None):
        compiled = compile_strategy(package() if pkg is None else pkg)
        run = execute(prepare(compiled["spec"]), self.fixture.root, self.output)
        return run, compiled

    @staticmethod
    def fingerprint(root):
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()
        }

    def test_old_execution_get_make_and_verify_revision_source_without_writes(self):
        run, compiled = self.archive()
        before = self.fingerprint(self.output)
        with patch("quantlab.data.mqc.MQCParquetProvider.load", side_effect=AssertionError("no data root reads")):
            detail = catalog.get_strategy_run(self.output, run.run_id)
            source = catalog.make_strategy_revision_source(detail)
            verified = catalog.verify_strategy_revision_source(self.output, source)
        self.assertEqual(detail["content_hash"], catalog.strategy_content_hash(compiled["spec"]["strategy_package"]))
        self.assertEqual(source["parent_run_id"], run.run_id)
        self.assertEqual(source["parent_package_hash"], compiled["package_hash"])
        self.assertEqual(verified, {
            "status": "verified",
            "source": source,
            "scope": "historical_reference_only",
            "execution_authorized": False,
        })
        self.assertNotIn("revision_source", detail)
        self.assertEqual(before, self.fingerprint(self.output))

    def test_prepare_revision_returns_direct_source_and_content_hash_match(self):
        run, compiled = self.archive()
        value = catalog.prepare_strategy_revision(self.output, run.run_id, expected_package_hash=compiled["package_hash"])
        self.assertTrue(value["current_matches_history"])
        self.assertEqual(value["revision_source"]["parent_run_id"], run.run_id)
        self.assertEqual(value["revision_source"]["parent_content_hash"], value["source"]["content_hash"])
        self.assertEqual(value["historical_package"], compiled["package"])
        self.assertNotIn("revision_source", value["compiled"]["package"])
        self.assertFalse(value["execution_authorized"])

    def test_verify_rejects_changed_fingerprint_and_damaged_or_missing_parent(self):
        run, _ = self.archive()
        source = catalog.make_strategy_revision_source(catalog.get_strategy_run(self.output, run.run_id))
        changed = dict(source, parent_evidence_hash="0" * 64)
        with self.assertRaises(ValueError):
            catalog.verify_strategy_revision_source(self.output, changed)
        (run.artifact_path / "bars.parquet").write_bytes(b"broken")
        with self.assertRaises(ValueError):
            catalog.verify_strategy_revision_source(self.output, source)
        with self.assertRaises(ValueError):
            catalog.verify_strategy_revision_source(self.fixture.root / "missing", source)

    def test_get_marks_archived_optional_source_not_checked_without_expanding_parent(self):
        parent, _ = self.archive()
        parent_detail = catalog.get_strategy_run(self.output, parent.run_id)
        source = catalog.make_strategy_revision_source(parent_detail)
        child_package = package(strategy_version="2.0.0")
        child_package["revision_source"] = source
        child, _ = self.archive(child_package)
        with patch.object(catalog, "get_strategy_run", wraps=catalog.get_strategy_run) as wrapped:
            detail = wrapped(self.output, child.run_id)
        self.assertEqual(wrapped.call_count, 1)
        self.assertEqual(detail["revision_source"], source)
        self.assertEqual(detail["revision_source_verification"], "not_checked")

    def test_prepare_revision_uses_current_direct_parent_not_ancestor(self):
        grandparent, _ = self.archive()
        source = catalog.make_strategy_revision_source(catalog.get_strategy_run(self.output, grandparent.run_id))
        parent_package = package(strategy_version="2.0.0")
        parent_package["revision_source"] = source
        parent, parent_compiled = self.archive(parent_package)
        prepared = catalog.prepare_strategy_revision(self.output, parent.run_id,
                                                    expected_package_hash=parent_compiled["package_hash"])
        self.assertEqual(prepared["revision_source"]["parent_run_id"], parent.run_id)
        self.assertNotEqual(prepared["revision_source"]["parent_run_id"], source["parent_run_id"])

    def test_parent_manifest_damage_is_rejected_not_rewritten_or_cached(self):
        run, _ = self.archive()
        source = catalog.make_strategy_revision_source(catalog.get_strategy_run(self.output, run.run_id))
        path = run.artifact_path / "experiment.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["manifest"]["strategy_package"]["package"]["name"] = "damaged"
        path.write_text(encode(record), encoding="utf-8")
        with self.assertRaises(ValueError):
            catalog.verify_strategy_revision_source(self.output, source)


if __name__ == "__main__":
    unittest.main()
