"""F14 cross-layer strategy lifecycle acceptance on isolated synthetic archives.

These tests intentionally stitch the existing production services together instead of
using a test-only lifecycle facade: F9 raw archive export/check, strategy compile,
ProposalService approval, real JobQueue execution, progress/catalog/revision,
comparison, bundle transfer/restore, and numerical reproduction.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import test_archived_dataset_lifecycle as archived_fixture
from test_strategy_package_cli import package_fixture

from quantlab.agent.planning import ResearchBudget
from quantlab.agent.proposal_progress import read_proposal_progress
from quantlab.agent.proposals import ProposalService
from quantlab.data.archived_daily_dataset import ArchivedDailyDatasetProvider
from quantlab.data.archived_research_check import check_archived_daily_research
from quantlab.storage.bundle import export_bundle, restore_bundle, reproduce_artifact
from quantlab.trading.strategy_comparison import compare_strategy_runs
from quantlab.trading.strategy_package import compile_strategy
from quantlab.trading.strategy_run_catalog import (
    get_strategy_run,
    list_strategy_runs,
    prepare_strategy_revision,
    verify_strategy_revision_source,
)
from quantlab.workbench.jobs import JobQueue


def _settled(testcase, queue, job_id, *, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = next(j for j in queue.list() if j["job_id"] == job_id)
        if job["status"] not in ("queued", "running"):
            testcase.assertEqual(job["status"], "completed", job)
            return job
        time.sleep(0.03)
    testcase.fail("real JobQueue did not settle: " + job_id)


class F14StrategyLifecycleAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.fx = archived_fixture.ArchivedDatasetLifecycleTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.addCleanup(lambda: self.fx.queue.close() if self.fx.queue else None)
        self.root = Path(self.fx.root).resolve()
        self.output = Path(self.fx.output).resolve()
        self.dataset = Path(self.fx.destination).resolve()

    def _exported_raw_archive_and_package(self):
        exported = self.fx.export()
        precheck = check_archived_daily_research(self.dataset, self.fx.spec)
        self.assertTrue(precheck["compatible"], precheck)
        package = package_fixture()
        package["spec"].update(
            symbols=list(self.fx.symbols),
            start=self.fx.start,
            end=self.fx.end,
            adjustment="raw",
            qualification="research_only",
        )
        compiled = compile_strategy(package)
        checked = check_archived_daily_research(self.dataset, compiled["spec"])
        self.assertTrue(checked["compatible"], checked)
        self.assertEqual(checked["dataset_id"], exported["dataset_id"])
        return exported, package, compiled

    def _approve_and_complete(self, service, proposal, queue):
        submitted = service.approve_and_submit(
            proposal["proposal_id"], proposal["proposal_digest"], lambda: queue
        )
        job = _settled(self, queue, submitted["job"]["job_id"])
        return submitted, job

    def test_full_raw_archive_strategy_revision_bundle_restore_and_reproduction(self):
        _, package, compiled = self._exported_raw_archive_and_package()
        service = ProposalService(self.output, self.dataset)
        request_id = str(uuid4())
        proposal = service.propose(request_id, compiled["spec"])
        self.assertEqual(service.propose(request_id, compiled["spec"]), proposal)
        self.assertEqual(proposal["status"], "pending")

        self.fx.queue = JobQueue(self.output, self.dataset)
        first_submission, first_job = self._approve_and_complete(service, proposal, self.fx.queue)
        duplicate_submission = service.approve_and_submit(
            proposal["proposal_id"], proposal["proposal_digest"], lambda: self.fx.queue
        )
        self.assertEqual(duplicate_submission["job"]["job_id"], first_job["job_id"])
        self.assertEqual(len([j for j in self.fx.queue.list() if j["job_id"] == first_job["job_id"]]), 1)

        progress = read_proposal_progress(self.output, proposal["proposal_id"])
        self.assertEqual(progress["phase"], "completed", progress)
        self.assertEqual(progress["result"]["run_id"], first_job["run_id"])
        self.assertTrue(progress["can_open_result"])

        listed = list_strategy_runs(self.output, query=package["strategy_key"])
        self.assertIn(first_job["run_id"], [row["run_id"] for row in listed["runs"]])
        first_detail = get_strategy_run(self.output, first_job["run_id"])
        prepared = prepare_strategy_revision(
            self.output,
            first_job["run_id"],
            expected_package_hash=first_detail["package_identity"]["package_hash"],
        )
        self.assertFalse(prepared["execution_authorized"])
        self.assertEqual(prepared["revision_source"]["parent_run_id"], first_job["run_id"])

        revised = deepcopy(prepared["compiled"]["package"])
        revised["version"] = "1.0.1-f14-explicit"
        revised["revision_source"] = deepcopy(prepared["revision_source"])
        revised["spec"]["portfolio"]["max_position"] = 0.2
        revised_compiled = compile_strategy(revised)
        self.assertTrue(check_archived_daily_research(self.dataset, revised_compiled["spec"])["compatible"])
        second_request = str(uuid4())
        second_proposal = service.propose(second_request, revised_compiled["spec"])
        self.assertEqual(second_proposal["status"], "pending")
        self.assertIsNone(second_proposal["approved_at"])
        self.assertEqual(
            second_proposal["plan"]["strategy_revision_sources"][0]["execution_authorized"],
            False,
        )
        second_submission, second_job = self._approve_and_complete(service, second_proposal, self.fx.queue)
        self.assertNotEqual(second_job["run_id"], first_job["run_id"])

        second_detail = get_strategy_run(self.output, second_job["run_id"])
        self.assertEqual(second_detail["package"]["revision_source"], prepared["revision_source"])
        self.assertEqual(second_detail["revision_source_verification"], "not_checked")
        verified_parent = verify_strategy_revision_source(self.output, prepared["revision_source"])
        self.assertEqual(verified_parent["status"], "verified")
        comparison = compare_strategy_runs(self.output, first_job["run_id"], second_job["run_id"])
        self.assertEqual(comparison["scope"], "DESCRIPTIVE_ONLY")
        self.assertTrue(comparison["comparable"], comparison)
        self.assertIn("spec.portfolio.max_position", [row["path"] for row in comparison["config_changes"]])

        bundle = self.root / "f14-child-only-bundle.zip"
        export_report = export_bundle(self.output / second_job["run_id"], bundle)
        restored = restore_bundle(bundle, self.root / "restored-bundle")
        restored_runs = Path(restored["artifact_root"])
        self.assertFalse((restored_runs / first_job["run_id"]).exists(), "direct parent strategy must not be auto-bundled")
        self.assertTrue((restored_runs / second_job["run_id"]).is_dir())
        self.assertGreaterEqual(export_report["runs"], 2)  # child execution plus its signal artifact

        script = """
import json, sys
from pathlib import Path
from quantlab.storage.bundle import reproduce_artifact
from quantlab.trading.strategy_run_catalog import get_strategy_run, list_strategy_runs
root = Path(sys.argv[1])
run_id = sys.argv[2]
out = Path(sys.argv[3]).resolve()
detail = get_strategy_run(root, run_id)
replay = reproduce_artifact(root / run_id, out)
print(json.dumps({
    'listed': [row['run_id'] for row in list_strategy_runs(root)['runs']],
    'run_id': detail['run_id'],
    'parent_run_id': detail['package']['revision_source']['parent_run_id'],
    'revision_source_verification': detail['revision_source_verification'],
    'reproduction_status': replay['status'],
}, ensure_ascii=False))
"""
        child = subprocess.run(
            [sys.executable, "-B", "-c", script, str(restored_runs), second_job["run_id"], str(self.root / "restored-replay")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        reopened = json.loads(child.stdout)
        self.assertIn(second_job["run_id"], reopened["listed"])
        self.assertEqual(reopened["parent_run_id"], first_job["run_id"])
        self.assertEqual(reopened["revision_source_verification"], "not_checked")
        self.assertEqual(reopened["reproduction_status"], "numerically_matched")
        self.assertTrue(first_submission["approval_freeze"])
        self.assertTrue(second_submission["approval_freeze"])

    def test_approved_task_and_reproduction_use_frozen_bytes_after_archive_is_offline(self):
        _, _, compiled = self._exported_raw_archive_and_package()
        budget = ResearchBudget(max_active_jobs=1)
        service = ProposalService(self.output, self.dataset, budget=budget)
        proposal = service.propose(str(uuid4()), compiled["spec"])
        busy = SimpleNamespace(
            root=self.output,
            data_root=self.dataset,
            list=lambda: [{"job_id": str(uuid4()), "status": "running"}],
        )
        with self.assertRaises(Exception):
            service.approve_and_submit(proposal["proposal_id"], proposal["proposal_digest"], lambda: busy)
        approved = service.get(proposal["proposal_id"])
        self.assertEqual(approved["status"], "approved")
        self.assertIn("approval_freeze", approved)

        self.fx.source.rename(self.root / "f14-source-offline")
        self.dataset.rename(self.root / "f14-dataset-offline")
        self.dataset.mkdir()
        self.fx.queue = JobQueue(self.output, self.dataset)
        with patch.object(ArchivedDailyDatasetProvider, "load", side_effect=AssertionError("live archive read")):
            submitted = service.approve_and_submit(proposal["proposal_id"], proposal["proposal_digest"], lambda: self.fx.queue)
            job = _settled(self, self.fx.queue, submitted["job"]["job_id"])
            replay = reproduce_artifact(self.output / job["run_id"], self.root / "offline-replayed")
        self.assertEqual(replay["status"], "numerically_matched")
        repeated = service.approve_and_submit(proposal["proposal_id"], proposal["proposal_digest"], lambda: self.fx.queue)
        self.assertEqual(repeated["job"]["job_id"], job["job_id"])
        self.assertEqual(len(self.fx.queue.list()), 1)
        progress = read_proposal_progress(self.output, proposal["proposal_id"])
        self.assertEqual(progress["phase"], "completed", progress)
        record = json.loads((self.output / job["run_id"] / "experiment.json").read_text(encoding="utf-8"))
        self.assertTrue(record["manifest"]["signal_data_snapshot"]["files"][0]["approval_time_frozen"])


if __name__ == "__main__":
    unittest.main()
