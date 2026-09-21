"""Repeatable cross-module lifecycle tests using only synthetic temporary data.

The providers below are deterministic model doubles: they exercise ChatRuntime's
real tool dispatch but do not claim autonomous research or contact a model API.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import multiprocessing
from pathlib import Path
import socket
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch
from uuid import uuid4

from quantlab.agent.chat_cli import headless_chat_runtime
from quantlab.agent.model_config import ModelConfig
from quantlab.agent.research_session_grant import authorize_grant, grant_status, preview_grant
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.dynamic_paper import DynamicPaperAccount
from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
from quantlab.storage.codec import digest
from quantlab.trading.decision_store import DecisionStore
from quantlab.trading.paper_fill_intent import PaperFillIntentBridge
from quantlab.trading.paper_lifecycle import PaperLifecycleAnalytics
from quantlab.trading.paper_review import PaperReviewService
from quantlab.trading.playbook_decision_bridge import PlaybookDecisionBridge
from quantlab.trading.playbook_paper_plan import PlaybookPaperPlanError, PlaybookPaperPlanService
from quantlab.trading.playbook_store import PlaybookStore
from quantlab.trading.strategy_intent import StrategyIntentService

import test_core
from test_paper_review import day_bar, rules


def dt(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone(timedelta(hours=8)))


def _is_loopback_address(address):
    if isinstance(address, str):
        return True  # AF_UNIX path.
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextmanager
def external_network_blocked():
    """Fail the test on non-loopback socket use while leaving local IPC intact."""
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def guarded_connect(sock, address):
        if not _is_loopback_address(address):
            raise AssertionError("external network is forbidden in functional lifecycle tests")
        return original_connect(sock, address)

    def guarded_create_connection(address, *args, **kwargs):
        if not _is_loopback_address(address):
            raise AssertionError("external network is forbidden in functional lifecycle tests")
        return original_create_connection(address, *args, **kwargs)

    with patch.object(socket.socket, "connect", guarded_connect), patch.object(
        socket, "create_connection", guarded_create_connection
    ):
        yield


class DiscoveryAndHypothesisProvider:
    def __init__(self, hypothesis):
        self.hypothesis = hypothesis
        self.results = {}
        self.tool_names = set()

    def run(self, system, messages, tools, dispatch, emit, stop):
        self.tool_names = {tool["name"] for tool in tools}
        self.results["search"] = dispatch(
            "search_factors", {"query": "BASE.MOMENTUM", "offset": 0, "limit": 20}, "discover-factor"
        )
        self.results["describe"] = dispatch(
            "describe_factor", {"factor_id": "BASE.MOMENTUM", "version": "1.0.0"}, "describe-factor"
        )
        self.results["hypothesis"] = dispatch(
            "record_hypothesis",
            {"request_id": str(uuid4()), "hypothesis_json": json.dumps(self.hypothesis, ensure_ascii=False)},
            "record-hypothesis",
        )
        return {"text": "夹具模型已通过正式工具发现因子并记录待验证假设；尚未执行研究。", "model": "fixture", "provider": "fixture"}


class GrantedResearchProvider:
    def __init__(self, grant_id, spec, hypothesis_id):
        self.grant_id = grant_id
        self.spec = spec
        self.hypothesis_id = hypothesis_id
        self.results = {}

    def run(self, system, messages, tools, dispatch, emit, stop):
        def checked(key, name, arguments, call_id):
            result = dispatch(name, arguments, call_id)
            self.results[key] = result
            if not result.get("ok"):
                raise ValueError(key + " failed: " + json.dumps(result, ensure_ascii=False))
            return result

        checked("grant", "get_research_session_grant", {}, "get-grant")
        arguments = {
            "grant_id": self.grant_id,
            "request_id": "model-supplied-id-is-replaced",
            "spec_json": json.dumps(self.spec, ensure_ascii=False),
        }
        checked("submit_first", "submit_granted_experiment", arguments, "submit-1")
        checked("submit_again", "submit_granted_experiment", arguments, "submit-2")
        job_id = self.results["submit_first"]["data"]["job"]["job_id"]
        # Keep polling within the configured tool budget, allowing slower cold imports.
        for index in range(12):
            job = checked("job", "get_job", {"job_id": job_id}, "job-" + str(index))
            if job["data"]["status"] not in ("queued", "running"):
                break
            time.sleep(1.0)
        if self.results["job"]["data"]["status"] != "completed":
            raise AssertionError("synthetic granted research did not complete")
        run_id = self.results["job"]["data"]["run_id"]
        checked("experiment", "get_experiment", {"run_id": run_id}, "get-experiment")
        checked(
            "inspected",
            "inspect_research_evidence",
            {"run_id": run_id, "pointer": "/metrics/1/rank_ic"},
            "inspect-evidence",
        )
        finding = {
            "hypothesis_id": self.hypothesis_id,
            "title": "合成样本生命周期证据",
            "statement": "仅记录合成夹具的研究证据，不推广为真实市场 Alpha。",
            "assessment": "inconclusive",
            "limitations": "TemporaryDirectory 合成数据与夹具模型，只验证正式生命周期接线。",
            "next_action": "由真实助手在另行授权的数据范围内自行提出后续研究。",
            "evidence": [{"run_id": run_id, "pointer": "/metrics/1/rank_ic", "relation": "context"}],
            "supersedes": None,
        }
        checked(
            "finding",
            "record_finding",
            {"request_id": str(uuid4()), "finding_json": json.dumps(finding, ensure_ascii=False)},
            "record-finding",
        )
        return {"text": "夹具模型已读取归档证据并保存有限结论；不声称 Alpha。", "model": "fixture", "provider": "fixture"}


def _research_reopen_worker(connection, payload):
    try:
        with external_network_blocked(), headless_chat_runtime(
            payload["output"], payload["data_root"], local_data_only=True
        ) as runtime:
            job = runtime.api.call("get_job", {"job_id": payload["job_id"]})
            experiment = runtime.api.call("get_experiment", {"run_id": payload["run_id"]})
            memory = runtime.api.call("get_research_memory", {"memory_id": payload["finding_id"]})
            inspected = runtime.api.call(
                "inspect_research_evidence", {"run_id": payload["run_id"], "pointer": "/metrics/1/rank_ic"}
            )
            grant = runtime.api.call("get_research_session_grant", {})
            connection.send(
                {
                    "ok": all(item["ok"] for item in (job, experiment, memory, inspected, grant)),
                    "job_run_id": job["data"]["run_id"],
                    "experiment_run_id": experiment["data"]["run_id"],
                    "memory_run_id": memory["data"]["record"]["evidence"][0]["run_id"],
                    "source_sha256": memory["data"]["record"]["evidence"][0]["source_sha256"],
                    "inspected_source_sha256": inspected["data"]["source_sha256"],
                    "source_integrity": memory["data"]["source_integrity"],
                    "used": grant["data"]["used"],
                    "remaining": grant["data"]["remaining"],
                }
            )
    except BaseException:
        connection.send({"ok": False, "traceback": traceback.format_exc()})
    finally:
        connection.close()


def _spawn_result(target, payload):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(sender, payload))
    process.start()
    sender.close()
    try:
        if not receiver.poll(30):
            raise AssertionError("spawned lifecycle verifier timed out")
        result = receiver.recv()
        process.join(10)
        if process.exitcode != 0:
            raise AssertionError("spawned lifecycle verifier exited with " + str(process.exitcode))
        return result
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(5)
        if not process.is_alive():
            process.close()


def _create_general_prediction(root, selected_symbols):
    clock = dt("2026-09-14T09:36:00")
    store = PlaybookStore(root, now_fn=lambda: clock)
    source = store.create_strategy_source(
        str(uuid4()),
        {
            "source_key": "general-lifecycle-source",
            "source_kind": "SYSTEM_REVIEW",
            "title": "通用生命周期合成来源",
            "locator": "local:synthetic-functional-lifecycle",
            "published_at": None,
            "available_at": "2026-09-14T09:00:00+08:00",
            "content_hash": "a" * 64,
            "archive_ref": "synthetic:test-only",
            "completeness": "VERIFIED",
            "notes": "非 Qimo 专属；只用于 TemporaryDirectory 集成测试。",
            "evidence_ids": ["synthetic-fixture"],
        },
    )
    compatibility_source = store.create_source(
        str(uuid4()),
        {
            "expert_key": "general-lifecycle-compat",
            "title": "通用生命周期兼容来源",
            "source_type": "OTHER",
            "locator": "local:synthetic-functional-lifecycle-compat",
            "available_at": "2026-09-14T09:00:00+08:00",
            "content_hash": "b" * 64,
            "archive_ref": "synthetic:test-only",
            "completeness": "VERIFIED",
            "notes": "现有 PlaybookDefinition/Case 的兼容 source_ids 合同。",
        },
    )
    definition = store.create_definition(
        str(uuid4()),
        {
            "playbook_key": "general-lifecycle",
            "name": "通用生命周期 Playbook",
            "version": "v1",
            "state": "DRAFT",
            "source_ids": [compatibility_source["source_id"]],
            "market_context": {"fixture": True},
            "eligibility": {"rule": "synthetic eligible"},
            "selection": {"rule": "synthetic selected"},
            "veto": {},
            "entry": {"rule": "host confirmed paper only"},
            "confirm": {},
            "invalidation": {},
            "hold": {},
            "add": {},
            "reduce": {},
            "exit": {},
            "notes": "通用、非 Qimo 专属。",
        },
    )
    link = store.create_source_link(
        str(uuid4()),
        {
            "definition_id": definition["definition_id"],
            "strategy_source_id": source["strategy_source_id"],
            "relation": "ORIGIN",
            "notes": "合成来源绑定",
            "evidence_ids": ["synthetic-fixture"],
        },
    )
    case = store.create_case(
        str(uuid4()),
        {
            "definition_id": definition["definition_id"],
            "trading_day": "2026-09-14",
            "frame": "R1",
            "as_of": "2026-09-14T09:35:30+08:00",
            "source_ids": [compatibility_source["source_id"]],
            "summary": "通用合成 case",
            "notes": "",
        },
    )
    candidate_set = store.create_candidate_set(
        str(uuid4()),
        {
            "case_id": case["case_id"],
            "definition_id": definition["definition_id"],
            "trading_day": "2026-09-14",
            "frame": "R1",
            "as_of": "2026-09-14T09:35:30+08:00",
            "completeness": "FULL",
            "pit_status": "STRICT_PIT",
            "universe_source": "synthetic fixture",
            "generation_method": "deterministic fixture",
            "candidates": [
                {
                    "symbol": "sh.600000",
                    "eligibility_reasons": ["synthetic eligible"],
                    "features": {"execution_profile": "STANDARD_ACCESS"},
                    "evidence_ids": ["synthetic-bar"],
                }
            ],
            "evidence_ids": ["synthetic-bar"],
        },
    )
    selected = list(selected_symbols)
    selection = store.create_selection(
        str(uuid4()),
        {
            "candidate_set_id": candidate_set["candidate_set_id"],
            "kind": "SYSTEM_PREDICTION",
            "selected_symbols": selected,
            "ranked_symbols": selected,
            "reasons": {"sh.600000": ["synthetic rule matched"]} if selected else {},
            "evidence_ids": ["synthetic-prediction"],
            "as_of": "2026-09-14T09:35:30+08:00",
            "notes": "NO_TRADE" if not selected else "synthetic selected",
        },
    )
    return {
        "source": source,
        "compatibility_source": compatibility_source,
        "definition": definition,
        "link": link,
        "selection": selection,
    }


def _paper_reopen_worker(connection, payload):
    try:
        with external_network_blocked():
            root = Path(payload["root"])
            bridge = PlaybookDecisionBridge(root, now_fn=lambda: dt("2026-09-14T09:36:00")).apply(
                payload["selection_id"]
            )
            plans = PlaybookPaperPlanService(root, now_fn=lambda: dt("2026-09-14T15:10:00"))
            plan = plans.create(
                payload["selection_id"],
                [payload["plan_decision_id"]],
                "general_lifecycle",
                {"sh.600000": 0.5},
                confirmed=True,
            )
            executed = plans.execute_dynamic(
                plan["plan_id"],
                day_bar("2026-09-15", 10.2),
                rules("2026-09-15"),
                ExecutionConfig(initial_cash=100000, top_n=1, exposure=1, price_mode="account"),
                confirmed=True,
                as_of=dt("2026-09-15T15:05:00"),
            )
            fill = PaperFillIntentBridge(root, now_fn=lambda: dt("2026-09-15T15:10:00")).apply(
                plan["plan_id"], confirmed=True
            )
            review = PaperReviewService(root, now_fn=lambda: dt("2026-09-15T16:00:00")).build(
                plan["plan_id"], "2026-09-15"
            )
            account = DynamicPaperAccount(root / "paper_dynamic/general_lifecycle.json").read()
            connection.send(
                {
                    "ok": True,
                    "bridge_decision_id": bridge["decisions"][0]["decision_id"],
                    "plan_id": plan["plan_id"],
                    "account_revision": executed["execution"]["account_revision"],
                    "fill_decision_id": fill["results"][0]["decision_id"],
                    "review_hash": review["review_hash"],
                    "order_count": len(account["orders"]),
                    "fill_count": len(account["fills"]),
                }
            )
    except BaseException:
        connection.send({"ok": False, "traceback": traceback.format_exc()})
    finally:
        connection.close()


class FunctionalLifecycleTests(unittest.TestCase):
    def test_chat_runtime_grant_freeze_archive_finding_and_process_reopen(self):
        fixture = test_core.CoreTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        output = fixture.root / "functional-output"
        output.mkdir()
        hypothesis = {
            "title": "合成动量生命周期假设",
            "statement": "在固定合成样本中，二期动量可能与下一期收益排序相关。",
            "factor_id": "BASE.MOMENTUM",
            "factor_version": "1.0.0",
            "parameters": {"lookback": 2},
            "mechanism": "仅以确定性合成价格延续检查跨模块接线。",
            "falsification": "若归档 rank_ic 为空或来源校验失败，则不形成支持性解释。",
            "supersedes": None,
        }
        scope = {
            "symbols": list(fixture.symbols),
            "timeframe": "1d",
            "start": "2025-01-01",
            "end": "2025-01-10",
            "adjustment": "qfq",
            "qualification": "research_only",
            "allowed_modes": ["single"],
            "allowed_factors": ["BASE.MOMENTUM@1.0.0"],
        }
        spec = {
            "question": "合成动量生命周期研究",
            "symbols": list(fixture.symbols),
            "start": "2025-01-01",
            "end": "2025-01-10",
            "timeframe": "1d",
            "adjustment": "qfq",
            "qualification": "research_only",
            "factor": "BASE.MOMENTUM",
            "version": "1.0.0",
            "parameters": {"lookback": 2},
            "mode": "single",
            "horizons": [1],
            "quantiles": 5,
            "replay": True,
        }
        with external_network_blocked(), headless_chat_runtime(
            output, fixture.root, allow_granted_research=True, local_data_only=True
        ) as runtime:
            conversation = runtime.store.create("functional lifecycle")
            discovery = DiscoveryAndHypothesisProvider(hypothesis)
            first = runtime.send(
                conversation,
                "先发现正式研究工具和因子，再记录可证伪假设；不要执行。",
                ModelConfig(max_tool_calls=12, max_context_chars=200000),
                allow_send=True,
                provider=discovery,
            )
            self.assertTrue({"search_factors", "record_hypothesis", "submit_granted_experiment"} <= discovery.tool_names)
            self.assertEqual(first["tool_calls"], 3)
            self.assertTrue(all(result["ok"] for result in discovery.results.values()), discovery.results)
            hypothesis_id = discovery.results["hypothesis"]["data"]["record"]["memory_id"]
            self.assertFalse((output / "_jobs").exists())

            plan = preview_grant(
                output,
                fixture.root,
                scope,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                max_jobs=1,
                max_active_jobs=1,
                max_leaf_studies=1,
                max_total_leaf_studies=1,
                max_total_bar_evaluations=1000,
                max_total_resample_date_draws=1,
                cooperative_seconds=60,
            )
            grant = authorize_grant(output, fixture.root, plan, digest(plan), confirmed=True)
            execution = GrantedResearchProvider(grant["grant_id"], spec, hypothesis_id)
            second = runtime.send(
                conversation,
                "在宿主刚授权的精确范围内提交一次，读取完成归档并保存有限 finding。",
                ModelConfig(max_tool_calls=24, max_context_chars=200000),
                allow_send=True,
                provider=execution,
            )
            self.assertIn("不声称 Alpha", second["text"])
            self.assertTrue(all(result["ok"] for result in execution.results.values()), execution.results)

        first_job = execution.results["submit_first"]["data"]["job"]
        repeated_job = execution.results["submit_again"]["data"]["job"]
        self.assertEqual(first_job["job_id"], repeated_job["job_id"])
        self.assertEqual(first_job["created_at"], repeated_job["created_at"])
        job_id = first_job["job_id"]
        run_id = execution.results["job"]["data"]["run_id"]
        self.assertEqual(execution.results["experiment"]["data"]["run_id"], run_id)
        self.assertEqual(execution.results["inspected"]["data"]["run_id"], run_id)
        finding = execution.results["finding"]["data"]
        finding_id = finding["record"]["memory_id"]
        self.assertEqual(finding["record"]["evidence"][0]["run_id"], run_id)
        self.assertEqual(finding["source_integrity"], "verified")

        job_record = json.loads((output / "_jobs" / (job_id + ".json")).read_text())
        frozen = ApprovalInputFreezeStore(output, fixture.root).verify(
            job_record["execution_guard"]["approval_freeze"], spec
        )
        self.assertEqual(frozen["manifest"]["freeze_id"], job_id)
        self.assertEqual(frozen["manifest"]["data_entries"][0]["rows"], 50)
        self.assertEqual(grant_status(output, fixture.root)["used"]["jobs"], 1)
        self.assertEqual(grant_status(output, fixture.root)["remaining"]["jobs"], 0)
        self.assertEqual(len(list((output / "_jobs").glob("*.json"))), 1)

        reopened = _spawn_result(
            _research_reopen_worker,
            {
                "output": str(output),
                "data_root": str(fixture.root),
                "job_id": job_id,
                "run_id": run_id,
                "finding_id": finding_id,
            },
        )
        self.assertTrue(reopened["ok"], reopened.get("traceback"))
        self.assertEqual({reopened["job_run_id"], reopened["experiment_run_id"], reopened["memory_run_id"]}, {run_id})
        self.assertEqual(reopened["source_sha256"], reopened["inspected_source_sha256"])
        self.assertEqual(reopened["source_integrity"], "verified")
        self.assertEqual(reopened["used"]["jobs"], 1)
        self.assertEqual(reopened["remaining"]["jobs"], 0)

    def test_general_playbook_to_paper_fill_review_is_restart_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary, external_network_blocked():
            root = Path(temporary)
            records = _create_general_prediction(root, ["sh.600000"])
            self.assertEqual(records["source"]["source_kind"], "SYSTEM_REVIEW")
            self.assertEqual(records["link"]["definition_id"], records["definition"]["definition_id"])
            selection = records["selection"]

            bridged = PlaybookDecisionBridge(root, now_fn=lambda: dt("2026-09-14T09:36:00")).apply(
                selection["selection_id"]
            )
            self.assertEqual(bridged["decisions"][0]["action"], "WATCH")
            intent = StrategyIntentService(root, now_fn=lambda: dt("2026-09-14T15:00:00"))
            intent.transition(
                str(uuid4()),
                {
                    "symbol": "sh.600000",
                    "trading_day": "2026-09-14",
                    "frame": "R2",
                    "action": "READY",
                    "role_id": "human",
                    "ai_thesis": "宿主确认仅进入模拟准备",
                    "transition_reason": "host fixture readiness",
                    "source": "functional_lifecycle_host",
                },
            )
            plan_decision = intent.transition(
                str(uuid4()),
                {
                    "symbol": "sh.600000",
                    "trading_day": "2026-09-14",
                    "frame": "R3",
                    "action": "PLAN_OPEN",
                    "role_id": "human",
                    "ai_thesis": "宿主确认模拟计划",
                    "confirm_trigger": "next completed synthetic bar",
                    "transition_reason": "host fixture paper plan",
                    "source": "functional_lifecycle_host",
                },
            )
            plans = PlaybookPaperPlanService(root, now_fn=lambda: dt("2026-09-14T15:10:00"))
            plan = plans.create(
                selection["selection_id"],
                [plan_decision["decision_id"]],
                "general_lifecycle",
                {"sh.600000": 0.5},
                confirmed=True,
            )
            executed = plans.execute_dynamic(
                plan["plan_id"],
                day_bar("2026-09-15", 10.2),
                rules("2026-09-15"),
                ExecutionConfig(initial_cash=100000, top_n=1, exposure=1, price_mode="account"),
                confirmed=True,
                as_of=dt("2026-09-15T15:05:00"),
            )
            self.assertEqual(executed["status"], "EXECUTED_WITH_FILL")
            fill = PaperFillIntentBridge(root, now_fn=lambda: dt("2026-09-15T15:10:00")).apply(
                plan["plan_id"], confirmed=True
            )
            self.assertEqual(fill["results"][0]["status"], "OPEN_RECORDED")
            open_id = fill["results"][0]["decision_id"]
            review = PaperReviewService(root, now_fn=lambda: dt("2026-09-15T16:00:00")).build(
                plan["plan_id"], "2026-09-15"
            )
            self.assertEqual(review["review_frame"], "D1")
            self.assertFalse(review["future_data_used"])
            self.assertEqual(StrategyIntentService(root).state("sh.600000")["current_decision"]["decision_id"], open_id)
            lifecycle = PaperLifecycleAnalytics(root).build()
            self.assertEqual(lifecycle["system_predictions"], 1)
            self.assertEqual(lifecycle["paper_executions_with_fill"], 1)
            self.assertEqual(lifecycle["paper_reviews_by_frame"], {"D1": 1})
            self.assertFalse(lifecycle["automatic_real_trade"])

            reopened = _spawn_result(
                _paper_reopen_worker,
                {
                    "root": str(root),
                    "selection_id": selection["selection_id"],
                    "plan_decision_id": plan_decision["decision_id"],
                },
            )
            self.assertTrue(reopened["ok"], reopened.get("traceback"))
            self.assertEqual(reopened["bridge_decision_id"], bridged["decisions"][0]["decision_id"])
            self.assertEqual(reopened["plan_id"], plan["plan_id"])
            self.assertEqual(reopened["account_revision"], 1)
            self.assertEqual(reopened["fill_decision_id"], open_id)
            self.assertEqual(reopened["review_hash"], review["review_hash"])
            account = DynamicPaperAccount(root / "paper_dynamic/general_lifecycle.json").read()
            self.assertEqual(reopened["order_count"], len(account["orders"]))
            self.assertEqual(reopened["fill_count"], len(account["fills"]))
            self.assertGreater(reopened["fill_count"], 0)
            bridge_decisions = DecisionStore(root).list(
                symbol="sh.600000", trading_day="2026-09-14", frame="R1", include_superseded=True, limit=20
            )["records"]
            self.assertEqual(len([row for row in bridge_decisions if row["source"] == "playbook_system_prediction"]), 1)

    def test_unconfirmed_and_no_trade_paths_create_no_orders(self):
        with tempfile.TemporaryDirectory() as selected_tmp, tempfile.TemporaryDirectory() as no_trade_tmp, external_network_blocked():
            selected_root = Path(selected_tmp)
            selected = _create_general_prediction(selected_root, ["sh.600000"])["selection"]
            PlaybookDecisionBridge(selected_root, now_fn=lambda: dt("2026-09-14T09:36:00")).apply(
                selected["selection_id"]
            )
            intent = StrategyIntentService(selected_root, now_fn=lambda: dt("2026-09-14T15:00:00"))
            intent.transition(
                str(uuid4()),
                {
                    "symbol": "sh.600000",
                    "trading_day": "2026-09-14",
                    "frame": "R2",
                    "action": "READY",
                    "role_id": "human",
                    "ai_thesis": "fixture ready",
                    "transition_reason": "host fixture",
                    "source": "functional_lifecycle_host",
                },
            )
            plan_decision = intent.transition(
                str(uuid4()),
                {
                    "symbol": "sh.600000",
                    "trading_day": "2026-09-14",
                    "frame": "R3",
                    "action": "PLAN_OPEN",
                    "role_id": "human",
                    "ai_thesis": "fixture plan",
                    "confirm_trigger": "synthetic",
                    "transition_reason": "host fixture",
                    "source": "functional_lifecycle_host",
                },
            )
            with self.assertRaises(PlaybookPaperPlanError) as unconfirmed:
                PlaybookPaperPlanService(selected_root).create(
                    selected["selection_id"],
                    [plan_decision["decision_id"]],
                    "unconfirmed",
                    {"sh.600000": 0.5},
                )
            self.assertEqual(unconfirmed.exception.code, "CONFIRMATION_REQUIRED")
            self.assertFalse((selected_root / "paper").exists())
            self.assertFalse((selected_root / "paper_dynamic").exists())

            no_trade_root = Path(no_trade_tmp)
            no_trade = _create_general_prediction(no_trade_root, [])["selection"]
            receipt = PlaybookDecisionBridge(no_trade_root, now_fn=lambda: dt("2026-09-14T09:36:00")).apply(
                no_trade["selection_id"]
            )
            self.assertTrue(receipt["no_trade"])
            self.assertEqual(receipt["decisions"], [])
            with self.assertRaises(PlaybookPaperPlanError) as blocked:
                PlaybookPaperPlanService(no_trade_root).create(
                    no_trade["selection_id"], [str(uuid4())], "no_trade", {}, confirmed=True
                )
            self.assertEqual(blocked.exception.code, "NO_TRADE")
            self.assertFalse((no_trade_root / "_trading/decision_ledger.sqlite3").exists())
            self.assertFalse((no_trade_root / "paper").exists())
            self.assertFalse((no_trade_root / "paper_dynamic").exists())
            lifecycle = PaperLifecycleAnalytics(no_trade_root).build()
            self.assertEqual(lifecycle["paper_plans"], 0)
            self.assertEqual(lifecycle["paper_executions"], 0)
            self.assertEqual(lifecycle["paper_fill_count"], 0)


if __name__ == "__main__":
    unittest.main()
