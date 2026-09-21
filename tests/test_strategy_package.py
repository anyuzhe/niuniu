import json
import math
import tempfile
import time
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import test_core

from quantlab.agent.planning import ResearchBudget
from quantlab.agent.proposals import ProposalService
from quantlab.experiments.execution import ExecutionStudy
from quantlab.storage.codec import digest, encode
from quantlab.theory.templates import templates
from quantlab.trading.strategy_package import FORMAT, LIFECYCLE, compile_strategy
from quantlab.workbench.jobs import JobQueue, execute, prepare


def package(*, theory=None, strategy_version="1.0.0", max_position=1.0):
    spec = {
        "question": "F3b 合成策略包测试",
        "symbols": ["sh.600000", "sh.600001", "sh.600002", "sh.600003", "sh.600004"],
        "timeframe": "1d",
        "start": "2025-01-01",
        "end": "2025-01-10",
        "adjustment": "qfq",
        "qualification": "research_only",
        "replay": True,
        "mode": "execution",
        "execution": {
            "initial_cash": 100000,
            "top_n": 1,
            "threshold": 0,
            "exposure": 0.8,
            "lot_size": 100,
            "t_plus_one": True,
            "price_mode": "research",
            "commission_bps": 3,
            "minimum_commission": 5,
            "sell_tax_bps": 0,
            "transfer_bps": 0,
            "slippage_bps": 2,
            "statutory_fees": False,
        },
        "portfolio": {
            "weighting": "equal",
            "max_position": max_position,
            "max_exposure": 1.0,
            "max_turnover": 2.0,
        },
    }
    if theory is None:
        spec.update(factor="BASE.MOMENTUM", version="1.0.0", parameters={"lookback": 2})
    else:
        spec.update(theory=theory["template_id"], theory_version=theory["version"])
    return {
        "format": FORMAT,
        "strategy_key": "tests.f3b",
        "name": "F3b 合成测试策略",
        "version": strategy_version,
        "lifecycle": dict(LIFECYCLE),
        "spec": spec,
    }


class StrategyPackageTests(unittest.TestCase):
    def test_factor_compile_is_complete_stable_and_idempotent(self):
        first = compile_strategy(package())
        second = compile_strategy(package())
        repeated = compile_strategy(first["package"])
        self.assertEqual(first, second)
        self.assertEqual(first, repeated)
        self.assertFalse(first["execution_authorized"])
        self.assertEqual(set(first["package"]), {"format", "strategy_key", "name", "version", "lifecycle", "spec"})
        self.assertNotIn("strategy_package", first["package"]["spec"])
        self.assertEqual(first["package_hash"], digest(first["package"]))
        normalized = first["package"]["spec"]
        submission = prepare(normalized)
        self.assertEqual(normalized["execution"], json.loads(encode(asdict(submission.execution))))
        self.assertEqual(normalized["portfolio"], json.loads(encode(asdict(submission.portfolio))))
        self.assertEqual(normalized["universe"], json.loads(encode(asdict(submission.universe))))
        envelope = first["spec"]["strategy_package"]
        self.assertEqual(envelope["package"], first["package"])
        self.assertEqual(envelope["package_hash"], first["package_hash"])
        self.assertEqual(envelope["signal"]["factor_id"], "BASE.MOMENTUM")
        self.assertEqual(len(envelope["signal"]["code_hash"]), 64)
        self.assertIsNone(envelope["signal"]["template_source"])

    def test_representative_and_all_sixteen_templates_compile(self):
        catalog = templates()
        self.assertEqual(len(catalog), 16)
        representative = compile_strategy(package(theory=catalog[0]))
        signal = representative["spec"]["strategy_package"]["signal"]
        self.assertEqual(signal["factor_id"], "COMB.CONDITION")
        self.assertEqual(signal["template_source"]["template_id"], catalog[0]["template_id"])
        self.assertEqual(signal["template_source"]["version"], catalog[0]["version"])
        self.assertEqual(len(signal["template_source"]["code_hash"]), 64)
        hashes = []
        for item in catalog:
            with self.subTest(template=item["template_id"]):
                compiled = compile_strategy(package(theory=item))
                source = compiled["spec"]["strategy_package"]["signal"]["template_source"]
                self.assertEqual((source["template_id"], source["version"]), (item["template_id"], item["version"]))
                hashes.append(compiled["package_hash"])
        self.assertEqual(len(set(hashes)), 16)

    def test_strategy_version_and_position_change_hash(self):
        base = compile_strategy(package())["package_hash"]
        self.assertNotEqual(base, compile_strategy(package(strategy_version="1.0.1"))["package_hash"])
        self.assertNotEqual(base, compile_strategy(package(max_position=0.5))["package_hash"])

    def test_strict_package_contract_rejects_bad_fields_values_and_lifecycle(self):
        cases = []
        unknown = package(); unknown["metadata"] = {}
        cases.append(unknown)
        lifecycle = package(); lifecycle["lifecycle"]["holding"] = "fixed_period"
        cases.append(lifecycle)
        stop = package(); stop["lifecycle"]["stop_loss"] = 0.1
        cases.append(stop)
        conflict = package(); conflict["spec"].update(theory="RESEARCH.TREND_BREAKOUT", theory_version="1.0.0")
        cases.append(conflict)
        missing_fee = package(); del missing_fee["spec"]["execution"]["minimum_commission"]
        cases.append(missing_fee)
        nested_budget = package(); nested_budget["spec"]["execution"]["budget"] = {"cash": 1}
        cases.append(nested_budget)
        boolean_number = package(); boolean_number["spec"]["execution"]["initial_cash"] = True
        cases.append(boolean_number)
        nonfinite = package(); nonfinite["spec"]["portfolio"]["max_position"] = math.inf
        cases.append(nonfinite)
        latest = package(); latest["version"] = "latest"
        cases.append(latest)
        template_parameters = package(theory=templates()[0]); template_parameters["spec"]["parameters"] = {}
        cases.append(template_parameters)
        for value in cases:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                compile_strategy(value)

    def test_prepare_rejects_spec_hash_unknown_and_signal_tampering(self):
        compiled = compile_strategy(package())
        changed_spec = deepcopy(compiled["spec"])
        changed_spec["execution"]["top_n"] = 2
        with self.assertRaisesRegex(ValueError, "不一致"):
            prepare(changed_spec)
        changed_hash = deepcopy(compiled["spec"])
        changed_hash["strategy_package"]["package_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "package_hash"):
            prepare(changed_hash)
        unknown = deepcopy(compiled["spec"])
        unknown["strategy_package"]["package"]["unknown"] = True
        with self.assertRaisesRegex(ValueError, "外层字段"):
            prepare(unknown)
        changed_signal = deepcopy(compiled["spec"])
        changed_signal["strategy_package"]["signal"]["code_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "code_hash"):
            prepare(changed_signal)
        unnormalized = deepcopy(compiled["spec"])
        del unnormalized["execution"]["allow_st"]
        del unnormalized["strategy_package"]["package"]["spec"]["execution"]["allow_st"]
        unnormalized["strategy_package"]["package_hash"] = digest(unnormalized["strategy_package"]["package"])
        with self.assertRaisesRegex(ValueError, "完整规范化"):
            prepare(unnormalized)

    def test_legacy_prepare_preview_has_no_new_none_field(self):
        plain = package()["spec"]
        preview = prepare(plain).preview()
        self.assertNotIn("strategy_package", preview)
        self.assertEqual(preview, prepare(deepcopy(plain)).preview())

    def test_execution_study_rechecks_actual_config_execution_and_portfolio(self):
        compiled = compile_strategy(package())
        submission = prepare(compiled["spec"])
        envelope = submission.strategy_package
        study = ExecutionStudy(SimpleNamespace())
        with self.assertRaisesRegex(ValueError, "运行时 config"):
            study.run(replace(submission.config, research_question="tampered"), submission.execution,
                      submission.portfolio, strategy_package=envelope)
        with self.assertRaisesRegex(ValueError, "运行时 execution"):
            study.run(submission.config, replace(submission.execution, top_n=2),
                      submission.portfolio, strategy_package=envelope)
        with self.assertRaisesRegex(ValueError, "运行时 portfolio"):
            study.run(submission.config, submission.execution,
                      replace(submission.portfolio, max_position=0.5), strategy_package=envelope)

    def test_real_proposal_freeze_queue_archive_and_reopen_bind_package(self):
        fixture = test_core.CoreTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        output = fixture.root / "strategy-package-runs"; output.mkdir()
        compiled = compile_strategy(package())
        service = ProposalService(output, fixture.root, budget=replace(ResearchBudget(), max_active_jobs=1))
        proposal = service.propose(str(uuid4()), compiled["spec"])
        queue = JobQueue(output, fixture.root)
        try:
            result = service.approve_and_submit(proposal["proposal_id"], proposal["proposal_digest"], lambda: queue)
            deadline = time.time() + 30
            while time.time() < deadline:
                job = next(row for row in queue.list() if row["job_id"] == result["job"]["job_id"])
                if job["status"] not in ("queued", "running"):
                    break
                time.sleep(0.02)
            self.assertEqual(job["status"], "completed", job)
            record = json.loads((output / job["run_id"] / "experiment.json").read_text())
            self.assertEqual(record["manifest"]["strategy_package"], compiled["spec"]["strategy_package"])
            self.assertTrue(record["targets"])
            self.assertTrue(record["fills"])
            again = service.approve_and_submit(proposal["proposal_id"], proposal["proposal_digest"], lambda: queue)
            self.assertEqual(again["job"]["job_id"], job["job_id"])
            self.assertEqual(len(queue.list()), 1)
            plain_result = execute(prepare(compiled["package"]["spec"]), fixture.root, fixture.root / "plain-runs")
            plain_record = json.loads((plain_result.artifact_path / "experiment.json").read_text())
            self.assertEqual(record["targets"], plain_record["targets"])
            self.assertEqual(record["fills"], plain_record["fills"])
            self.assertEqual(record["execution"], plain_record["execution"])
            self.assertNotEqual(record["experiment_id"], plain_record["experiment_id"])
        finally:
            queue.close()
        reopened = JobQueue(output, fixture.root)
        try:
            saved = reopened.list()
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["status"], "completed")
            self.assertEqual(saved[0]["spec"]["strategy_package"]["package_hash"], compiled["package_hash"])
            self.assertEqual(service.get(proposal["proposal_id"])["status"], "submitted")
        finally:
            reopened.close()

    def test_single_mode_cannot_use_package_or_research_session_grant(self):
        compiled = compile_strategy(package())
        attack = deepcopy(compiled["spec"])
        attack["mode"] = "single"
        with self.assertRaisesRegex(ValueError, "仅允许用于 execution"):
            prepare(attack)

        fixture = test_core.CoreTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        output = fixture.root / "grant-package"; output.mkdir()
        from quantlab.agent.research_session_grant import preview_grant, authorize_grant, ResearchSessionGrantService
        scope = {
            "symbols": list(fixture.symbols), "timeframe": "1d", "start": "2025-01-01", "end": "2025-01-10",
            "adjustment": "qfq", "qualification": "research_only", "allowed_modes": ["single"],
            "allowed_factors": ["BASE.MOMENTUM@1.0.0"],
        }
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        plan = preview_grant(output, fixture.root, scope, expires_at=expiry, max_jobs=1, max_active_jobs=1,
                             max_leaf_studies=4, max_total_leaf_studies=4,
                             max_total_bar_evaluations=100000, max_total_resample_date_draws=100000,
                             cooperative_seconds=30)
        state = authorize_grant(output, fixture.root, plan, digest(plan), confirmed=True)
        disguised = deepcopy(compiled["spec"])
        disguised["mode"] = "single"
        disguised.pop("execution")
        disguised.pop("portfolio")
        disguised.pop("execution_backend")
        queue_called = []
        service = ResearchSessionGrantService(output, fixture.root, lambda: queue_called.append(True))
        with self.assertRaises(Exception):
            service.submit(state["grant_id"], str(uuid4()), disguised)
        self.assertFalse(queue_called)


if __name__ == "__main__":
    unittest.main()
