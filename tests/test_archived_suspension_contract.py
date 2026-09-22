"""Synthetic-only acceptance for F9 archived daily suspension contract v2."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo
import contextlib
import io
import json
import time

import polars as pl

from test_retro_daily import FakeSDK, bar
from quantlab.agent.archived_daily_dataset_cli import main as cli_main
from quantlab.agent.proposals import ProposalService
from quantlab.app import default_registry
from quantlab.data.archived_daily_dataset import (
    CONTRACT_V1, CONTRACT_V2, FORMAT_V2, MARKER,
    ArchivedDailyDatasetProvider, export_archived_daily_dataset,
    inspect_archived_daily_dataset, preview_archived_daily_dataset,
)
from quantlab.data.base import DataRequest, ExplicitUniverse
from quantlab.data.provider import local_data_provider
from quantlab.domain import Timeframe
from quantlab.execution.backtest import ExecutionConfig, OpenExecutionBacktester
from quantlab.experiments.runner import ExperimentRunner
from quantlab.storage.approval_inputs import ApprovalInputFreezeStore, ApprovalFrozenDataProvider
from quantlab.storage.bundle import reproduce_artifact
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore
from quantlab.workbench.jobs import JobQueue, prepare


class ArchivedSuspensionContractTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.source = self.root / "source"; self.source.mkdir()
        self.output = self.root / "runs"; self.output.mkdir()
        self.destination = self.root / "dataset-v2"
        self.symbols = ("sh.600001", "sz.000002")
        days = [date(2026, 7, 1) + timedelta(days=i) for i in range(10)]
        self.sessions = [d for d in days if d.weekday() < 5][:5]
        calendar = [(d.isoformat(), "1" if d in self.sessions else "0") for d in days]
        basic = [(s, "synthetic", "2000-01-01", "", "1", "1") for s in self.symbols]
        values = {
            "sh.600001": [
                bar(self.sessions[0].isoformat(), "sh.600001", 10.0, 9.8),
                bar(self.sessions[1].isoformat(), "sh.600001", 10.5, 10.0),
                bar(self.sessions[2].isoformat(), "sh.600001", 0, 10.5, tradestatus="0"),
                bar(self.sessions[3].isoformat(), "sh.600001", 11.0, 10.5),
                bar(self.sessions[4].isoformat(), "sh.600001", 11.5, 11.0),
            ],
            "sz.000002": [
                bar(self.sessions[i].isoformat(), "sz.000002", 20.0 + i, 19.5 + i)
                for i in range(5)
            ],
        }
        store = __import__("quantlab.data.retro_daily", fromlist=["RetroDailyStore"]).RetroDailyStore(
            self.source, today_fn=lambda: date(2026, 9, 22),
            now_fn=lambda: datetime(2026, 9, 22, tzinfo=timezone.utc))
        self.capture = store.create_plan(self.sessions[0].isoformat(), days[-1].isoformat(), sdk=FakeSDK(basic=basic, calendar=calendar, bars=values))["capture_id"]
        self.assertEqual(store.fetch(self.capture, sdk=FakeSDK(basic=basic, calendar=calendar, bars=values))["completed"], 2)
        self.start = self.sessions[0].isoformat(); self.end = self.sessions[-1].isoformat()
        self.spec = {
            "question": "synthetic suspension contract",
            "symbols": list(self.symbols), "start": self.start, "end": self.end,
            "timeframe": "1d", "adjustment": "raw",
            "factor": "BASE.MOMENTUM", "version": "1.0.0",
            "parameters": {"lookback": 1}, "horizons": [1], "quantiles": 2,
            "replay": True, "mode": "single", "qualification": "research_only",
        }
        self.queue = None
        self.addCleanup(lambda: self.queue.close() if self.queue else None)

    def export_v2(self):
        preview = preview_archived_daily_dataset(
            self.source, self.capture, " ".join(self.symbols), self.start, self.end, contract=CONTRACT_V2)
        result = export_archived_daily_dataset(
            self.source, self.capture, " ".join(self.symbols), self.start, self.end, self.destination,
            expected_preview_hash=preview["preview_hash"], confirmed=True, contract=CONTRACT_V2)
        return preview, result

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_main(list(args))
        return code, json.loads(out.getvalue())

    def settled(self, job_id):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            job = next(j for j in self.queue.list() if j["job_id"] == job_id)
            if job["status"] not in ("queued", "running"):
                return job
            time.sleep(.02)
        self.fail("job did not settle")

    def test_v1_still_rejects_while_v2_preserves_source_state_without_fill_prices(self):
        with self.assertRaisesRegex(ValueError, "v1 rejects requested tradestatus!=1"):
            preview_archived_daily_dataset(self.source, self.capture, " ".join(self.symbols), self.start, self.end)
        preview, exported = self.export_v2()
        self.assertEqual(preview["input_contract"], CONTRACT_V2)
        self.assertEqual((preview["rows"], preview["suspended_rows"], preview["tradable_rows"]), (10, 1, 9))
        self.assertEqual(exported["input_contract"], CONTRACT_V2)
        self.assertEqual(json.loads((self.destination / MARKER).read_text())["format"], FORMAT_V2)
        inspected = inspect_archived_daily_dataset(self.destination)
        self.assertEqual(inspected["input_contract"], CONTRACT_V2)
        provider = ArchivedDailyDatasetProvider(self.destination)
        batch = provider.load(DataRequest(self.symbols, Timeframe.DAILY, self.sessions[0], self.sessions[-1]))
        row = batch.bars.filter((pl.col("symbol") == "sh.600001") &
                                (pl.col("datetime").dt.date() == self.sessions[2])).row(0, named=True)
        self.assertEqual(row["bs_trade_status"], 0)
        self.assertTrue(all(row[k] is None for k in ("open", "high", "low", "close")))
        self.assertEqual(row["volume"], 0.0)
        self.assertIsNone(row["turnover"])
        self.assertEqual(row["vendor_previous_close"], 10.5)
        self.assertTrue(all(item.get("input_contract") == CONTRACT_V2 for item in batch.snapshot.files))

    def test_cli_requires_explicit_v2_and_inspect_reports_contract(self):
        common = ("--source-workspace", str(self.source), "--capture-id", self.capture,
                  "--symbols", *self.symbols, "--start", self.start, "--end", self.end)
        code, failed = self.cli("preview", *common)
        self.assertEqual(code, 2); self.assertFalse(failed["ok"])
        code, preview = self.cli("preview", *common, "--contract", CONTRACT_V2)
        self.assertEqual(code, 0); self.assertEqual(preview["data"]["suspended_rows"], 1)
        code, exported = self.cli("export", *common, "--contract", CONTRACT_V2,
            "--destination", str(self.destination), "--expected-preview-hash", preview["data"]["preview_hash"],
            "--confirm-create")
        self.assertEqual(code, 0, exported)
        code, inspected = self.cli("inspect", "--data-root", str(self.destination))
        self.assertEqual(code, 0); self.assertEqual(inspected["data"]["input_contract"], CONTRACT_V2)

    def test_research_keeps_session_grid_but_excludes_suspended_signal_and_label_endpoint(self):
        self.export_v2()
        provider = local_data_provider(self.destination, "raw")
        config = prepare(self.spec).config
        runner = ExperimentRunner(provider, default_registry(), ExplicitUniverse(self.symbols),
                                  LocalExperimentStore(self.root / "research"))
        result = runner.run(config)
        record = json.loads((result.artifact_path / "experiment.json").read_text())
        self.assertEqual(record["manifest"]["trade_state_policy"]["suspended_rows"], 1)
        observations = pl.read_parquet(result.artifact_path / "observations.parquet")
        suspended_dt = datetime.combine(self.sessions[2], datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai")).replace(hour=15)
        self.assertEqual(observations.filter((pl.col("symbol") == "sh.600001") &
                                             (pl.col("datetime") == suspended_dt)).height, 0)
        prior_dt = datetime.combine(self.sessions[1], datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai")).replace(hour=15)
        prior = observations.filter((pl.col("symbol") == "sh.600001") &
                                    (pl.col("datetime") == prior_dt)).row(0, named=True)
        self.assertIsNone(prior["forward_1"], "label endpoint is suspended and must not jump to the next tradable close")

    def test_execution_never_fills_suspension_and_carries_last_tradable_mark(self):
        self.export_v2()
        bars = ArchivedDailyDatasetProvider(self.destination).load(
            DataRequest(("sh.600001",), Timeframe.DAILY, self.sessions[0], self.sessions[3])).bars
        tz = ZoneInfo("Asia/Shanghai")
        before = datetime.combine(self.sessions[0] - timedelta(days=1), datetime.min.time(), tzinfo=tz).replace(hour=15)
        reduce_close = datetime.combine(self.sessions[1], datetime.min.time(), tzinfo=tz).replace(hour=15)
        targets = pl.DataFrame({
            "symbol": ["sh.600001", "sh.600001"],
            "datetime": [before, reduce_close], "available_at": [before, reduce_close],
            "weight": [1.0, 0.0],
        })
        cfg = ExecutionConfig(initial_cash=100000, lot_size=100, commission_bps=0,
                              minimum_commission=0, sell_tax_bps=0, slippage_bps=0)
        curve, fills, rejections, summary = OpenExecutionBacktester(cfg).run(targets, bars)
        self.assertEqual([f["side"] for f in fills], ["buy", "sell"])
        self.assertTrue(any(r["reason"] == "vendor_suspended" and r["filled"] == 0 for r in rejections))
        suspended_nav = curve.filter(pl.col("datetime").dt.date() == self.sessions[2]).row(0, named=True)
        buy = fills[0]
        # Suspension valuation carries the last real close (day 2 = 10.5), never the buy open or vendor preclose as a fill.
        self.assertAlmostEqual(suspended_nav["position_value"], buy["quantity"] * 10.5)
        self.assertEqual(summary["ending_positions"], {})

    def test_vnpy_open_rejects_preserved_suspension_rows(self):
        self.export_v2()
        bars = ArchivedDailyDatasetProvider(self.destination).load(
            DataRequest(("sh.600001",), Timeframe.DAILY, self.sessions[0], self.sessions[3])).bars
        from quantlab.adapters.vnpy import VnpyOpenBacktester
        cfg = ExecutionConfig(minimum_commission=0, slippage_bps=0, limit_pct=.1)
        with self.assertRaisesRegex(ValueError, "does not accept preserved suspension rows"):
            VnpyOpenBacktester(cfg).run(pl.DataFrame(), bars)

    def test_suspended_ex_date_dividend_fails_without_explicit_post_action_mark(self):
        self.export_v2()
        bars = ArchivedDailyDatasetProvider(self.destination).load(
            DataRequest(("sh.600001",), Timeframe.DAILY, self.sessions[0], self.sessions[3])).bars
        tz = ZoneInfo("Asia/Shanghai")
        before = datetime.combine(self.sessions[0] - timedelta(days=1), datetime.min.time(), tzinfo=tz).replace(hour=15)
        targets = pl.DataFrame({"symbol":["sh.600001"],"datetime":[before],"available_at":[before],"weight":[1.0]})
        closes=bars["datetime"].to_list()
        for ex_at in (closes[2].replace(hour=9,minute=30), closes[2]):
            action={"action_id":"suspended-cash","symbol":"sh.600001","record_at":closes[1],
                "ex_at":ex_at,"pay_at":closes[3].replace(hour=9,minute=30),
                "available_at":closes[0],"cash_per_share":.5,"tax_rate":0.,"source":"synthetic suspension review"}
            cfg = ExecutionConfig(initial_cash=100000, lot_size=100, commission_bps=0,
                                  minimum_commission=0, sell_tax_bps=0, slippage_bps=0,
                                  corporate_actions=[action])
            with self.subTest(ex_at=ex_at), self.assertRaisesRegex(ValueError, "explicit post-action valuation mark"):
                OpenExecutionBacktester(cfg).run(targets, bars)

    def test_state_aware_validation_fails_on_unknown_status_or_missing_valuation_reference(self):
        self.export_v2()
        batch = ArchivedDailyDatasetProvider(self.destination).load(
            DataRequest(("sh.600001",), Timeframe.DAILY, self.sessions[0], self.sessions[-1]))
        from quantlab.data.validation import ordered_bars
        bad = batch.bars.with_columns(
            pl.when(pl.col("datetime").dt.date() == self.sessions[2]).then(None)
              .otherwise(pl.col("bs_trade_status")).alias("bs_trade_status"))
        with self.assertRaisesRegex(ValueError, "explicit bs_trade_status"):
            ordered_bars(bad)
        bad = batch.bars.with_columns(
            pl.when(pl.col("datetime").dt.date() == self.sessions[2]).then(None)
              .otherwise(pl.col("vendor_previous_close")).alias("vendor_previous_close"))
        with self.assertRaisesRegex(ValueError, "vendor_previous_close"):
            ordered_bars(bad)
        # bs_trade_status exists on other providers too; without the explicit v2 contract it must retain legacy validation.
        legacy = batch.bars.drop("input_contract").with_columns(
            *[pl.when(pl.col("bs_trade_status") == 0).then(pl.col("vendor_previous_close")).otherwise(pl.col(c)).alias(c)
              for c in ("open","high","low","close")],
            pl.col("turnover").fill_null(0.0),
        )
        self.assertEqual(ordered_bars(legacy).height, legacy.height)

    def test_approval_freeze_runs_after_source_offline_and_reproduction_is_portable(self):
        self.export_v2()
        service = ProposalService(self.output, self.destination)
        proposal = service.propose(str(uuid4()), self.spec)
        full = SimpleNamespace(root=self.output, data_root=self.destination,
                               list=lambda: [{"job_id": str(uuid4()), "status": "running"}])
        with self.assertRaises(Exception):
            service.approve_and_submit(proposal["proposal_id"], proposal["proposal_digest"], lambda: full)
        self.assertEqual(service.store.get(proposal["proposal_id"])["status"], "approved")
        freeze = ApprovalInputFreezeStore(self.output, self.destination).path(proposal["proposal_id"])
        manifest = json.loads((freeze / "manifest.json").read_text())["manifest"]
        row = manifest["data_entries"][0]
        frozen_request = DataRequest(self.symbols, Timeframe.DAILY, self.sessions[0], self.sessions[-1])
        frozen_batch = ApprovalFrozenDataProvider(freeze, "raw").load(frozen_request)
        self.assertEqual(frozen_batch.snapshot.files[0]["input_contract"], CONTRACT_V2)
        old_identity = digest({"approval_entry":row["entry_key"],"request":frozen_request})
        self.assertNotEqual(frozen_batch.snapshot.snapshot_id, old_identity)
        expected_identity = digest({"approval_entry":row["entry_key"],"request":frozen_request,
            "frozen_sha256":row["sha256"],"source_snapshot_id":row["source_snapshot"]["snapshot_id"],
            "input_contract":CONTRACT_V2})
        self.assertEqual(frozen_batch.snapshot.snapshot_id, expected_identity)
        self.source.rename(self.root / "source-offline")
        self.destination.rename(self.root / "dataset-offline")
        self.destination.mkdir()
        self.queue = JobQueue(self.output, self.destination)
        with patch.object(ArchivedDailyDatasetProvider, "load", side_effect=AssertionError("must use approval freeze")):
            submitted = service.approve_and_submit(proposal["proposal_id"], proposal["proposal_digest"], lambda: self.queue)
            job = self.settled(submitted["job"]["job_id"])
        self.assertEqual(job["status"], "completed", job)
        original = self.output / job["run_id"]
        record = json.loads((original / "experiment.json").read_text())
        self.assertEqual(record["manifest"]["data_snapshot"]["source"], "archived_retro_daily_dataset")
        self.assertTrue(record["manifest"]["data_snapshot"]["files"][0]["approval_time_frozen"])
        with patch.object(ArchivedDailyDatasetProvider, "load", side_effect=AssertionError("external data read")):
            reproduced = reproduce_artifact(original, self.root / "reproduced")
        self.assertEqual(reproduced["status"], "numerically_matched", reproduced)


if __name__ == "__main__":
    import unittest
    unittest.main()
