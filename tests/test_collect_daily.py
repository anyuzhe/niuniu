"""Offline daily-plan and atomic-update regressions; all writes use temporary roots."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import corporate_actions_daily as corporate
from collect import coverage, status_incremental as status
from collect import scan_gaps, bars_incremental, daily_plan
from collect.daily_common import (logical_frame_digest, observed_state, run_lock,
                                  select_stock_basic, sha256_file, symbol_file)


class DailyFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = self.root / "bronze"
        self.dataset.mkdir()
        self.stock = self.root / "stock.parquet"
        pd.DataFrame([{"code": "sh.600001", "ipoDate": "2026-09-21",
                       "type": "1", "status": "1"},
                      {"code": "sh.600002", "ipoDate": "2026-09-21",
                       "type": "1", "status": "0"}]).to_parquet(self.stock)
        self.calendar = self.root / "calendar.parquet"
        pd.DataFrame({"calendar_date": ["2026-09-21", "2026-09-22", "2026-09-23"],
                      "is_trading_day": ["1", "1", "1"]}).to_parquet(self.calendar)
        self.patchers = [patch.object(coverage, "DATA_ROOT", self.root),
                         patch.object(coverage, "LAKE", self.root / "lake"),
                         patch.object(coverage, "STOCK_BASIC", self.stock),
                         patch.object(coverage, "CALENDAR", self.calendar)]
        for item in self.patchers:
            item.start()
            self.addCleanup(item.stop)


class DailyPacketTests(DailyFixture):
    def test_review_packet_proposes_reference_first_without_collecting(self):
        output = self.root / "plans"
        packet = daily_plan.build_packet(date(2026, 9, 23), output)
        self.assertEqual(packet["phase"], "reference_required")
        self.assertEqual(list(packet["plans"]), ["reference"])
        plan = json.loads((output / "reference.json").read_text())
        self.assertEqual(plan["plan_sha256"], packet["plans"]["reference"]["plan_sha256"])
        self.assertFalse((coverage.LAKE / "provider=baostock").exists())

    def test_incomplete_reference_never_generates_downstream_plans(self):
        snapshot = coverage.LAKE / "provider=baostock" / "reference_snapshots" / "snapshot=2026-09-23"
        snapshot.mkdir(parents=True)
        (snapshot / "manifest.json").write_text(json.dumps({"run_status": "running"}))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            daily_plan.build_packet(date(2026, 9, 23), self.root / "plans")
        self.assertFalse((self.root / "plans" / "index.json").exists())


class ReferenceSelectionTests(DailyFixture):
    def test_latest_verified_snapshot_reveals_new_listing_and_binds_manifest(self):
        snapshot = coverage.LAKE / "provider=baostock" / "reference_snapshots" / "snapshot=2026-09-22"
        snapshot.mkdir(parents=True)
        path = snapshot / "stock_basic.parquet"
        pd.DataFrame([{"code": "sh.600001", "ipoDate": "2026-09-21", "type": "1", "status": "1"},
                      {"code": "sh.600003", "ipoDate": "2026-09-22", "type": "1", "status": "1"}]).to_parquet(path)
        manifest = snapshot / "manifest.json"
        manifest.write_text(json.dumps({"run_status": "completed", "results": [
            {"name": "stock_basic", "status": "ok", "file": "stock_basic.parquet",
             "sha256": sha256_file(path)}]}))
        chosen, digest = select_stock_basic(date(2026, 9, 23), lake=coverage.LAKE,
                                            fallback=self.stock)
        self.assertEqual(chosen, path)
        self.assertEqual(digest, sha256_file(manifest))
        plan = corporate.build_plan("ths-dividend", self.dataset,
                                    observed_on=date(2026, 9, 23))
        self.assertEqual(plan["universe_count"], 2)
        manifest.write_text(manifest.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            corporate.validate_plan(plan)
        path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            select_stock_basic(date(2026, 9, 23), lake=coverage.LAKE,
                               fallback=self.stock)

    def test_new_reference_invalidates_previously_approved_bar_plan(self):
        with patch.dict(scan_gaps.DATASETS["baostock-daily"], {"dir": self.dataset}):
            plan = scan_gaps.build_plan("baostock-daily", target_end=date(2026, 9, 23))
            self.assertEqual(plan["universe"]["listed_symbols"], 1)
            bars_incremental.validate_plan_state(plan)
            snapshot = coverage.LAKE / "provider=baostock" / "reference_snapshots" / "snapshot=2026-09-23"
            snapshot.mkdir(parents=True)
            stock = snapshot / "stock_basic.parquet"
            calendar = snapshot / "trade_calendar.parquet"
            pd.read_parquet(self.stock).to_parquet(stock)
            pd.read_parquet(self.calendar).to_parquet(calendar)
            (snapshot / "manifest.json").write_text(json.dumps({
                "run_status": "completed", "results": [
                    {"name": name, "status": "ok", "file": f"{name}.parquet",
                     "sha256": sha256_file(snapshot / f"{name}.parquet")}
                    for name in ("stock_basic", "trade_calendar")]}))
            with self.assertRaisesRegex(ValueError, "newer reference"):
                bars_incremental.validate_plan_state(plan)

    def test_run_lock_refuses_concurrent_writer(self):
        with run_lock(self.dataset, "daily"):
            with self.assertRaises(FileExistsError):
                with run_lock(self.dataset, "daily"):
                    pass


class StatusDailyTests(DailyFixture):
    def row(self, day):
        return {"date": day, "code": "sh.600001", "tradestatus": "1",
                "isST": "0", "fetch_ts": "2026-09-23T00:00:00"}

    def test_tail_only_and_plan_detects_changed_bytes(self):
        pd.DataFrame([self.row("2026-09-21")]).to_parquet(symbol_file(self.dataset, "sh.600001"))
        plan = status.build_plan(self.dataset, end=date(2026, 9, 23),
                                 calendar_path=self.calendar, stock_path=self.stock)
        self.assertEqual([(x["code"], x["start"], x["end"]) for x in plan["actions"]],
                         [("sh.600001", "2026-09-22", "2026-09-23")])
        self.assertEqual(status.validate_plan(plan), plan["actions"])
        pd.DataFrame([self.row("2026-09-21"), self.row("2026-09-22")]).to_parquet(
            symbol_file(self.dataset, "sh.600001"))
        with self.assertRaises(ValueError):
            status.validate_plan(plan)

    def test_apply_appends_status_with_backup_and_does_not_fabricate_bars(self):
        target = symbol_file(self.dataset, "sh.600001")
        pd.DataFrame([self.row("2026-09-21")]).to_parquet(target)
        before = sha256_file(target)
        plan = status.build_plan(self.dataset, end=date(2026, 9, 22),
                                 calendar_path=self.calendar, stock_path=self.stock)
        class Session:
            def __init__(self, starts, end, timeout):
                self.starts = starts
                self.end = end
            def __call__(self, code):
                return pd.DataFrame([{"date": "2026-09-22", "code": code,
                                      "tradestatus": "0", "isST": "1",
                                      "fetch_ts": "2026-09-23T00:00:00"}])
            def close(self):
                pass
        receipt = status.apply(plan, session_factory=Session, throttle=0)
        self.assertEqual(receipt["run_status"], "finished")
        self.assertEqual(receipt["results"][0]["backup"]["sha256"], before)
        self.assertEqual(len(pd.read_parquet(target)), 2)
        self.assertEqual(pd.read_parquet(target)["tradestatus"].tolist(), ["1", "0"])

    def test_failed_status_run_resumes_original_plan(self):
        target = symbol_file(self.dataset, "sh.600001")
        pd.DataFrame([self.row("2026-09-21")]).to_parquet(target)
        plan = status.build_plan(self.dataset, end=date(2026, 9, 22),
                                 calendar_path=self.calendar, stock_path=self.stock)
        class Session:
            calls = 0
            def __init__(self, starts, end, timeout): pass
            def __call__(self, code):
                self.__class__.calls += 1
                if self.calls == 1:
                    return pd.DataFrame([{"date": "2026-09-22", "code": code,
                                          "tradestatus": "bad", "isST": "0",
                                          "fetch_ts": "t"}])
                return pd.DataFrame([{"date": "2026-09-22", "code": code,
                                      "tradestatus": "0", "isST": "0", "fetch_ts": "t"}])
            def close(self): pass
        first = status.apply(plan, session_factory=Session, throttle=0)
        self.assertEqual(first["run_status"], "finished_with_errors")
        second = status.apply(plan, session_factory=Session, resume_run=True, throttle=0)
        self.assertEqual(second["run_status"], "finished")
        self.assertEqual(Session.calls, 2)

    def test_status_bad_approval_does_not_start_provider(self):
        plan = status.build_plan(self.dataset, end=date(2026, 9, 22),
                                 calendar_path=self.calendar, stock_path=self.stock)
        path = self.root / "status-plan.json"
        path.write_text(json.dumps(plan))
        with patch.object(status, "StatusSession") as session:
            with self.assertRaises(PermissionError):
                status.main(["--dest", str(self.dataset), "--apply", "--plan",
                             str(path), "--approve-sha256", "0" * 64])
            session.assert_not_called()

    def test_rejects_missing_supplier_session_or_invalid_state(self):
        cal = coverage.TradingCalendar(self.calendar)
        action = {"code": "sh.600001", "start": "2026-09-22", "end": "2026-09-23"}
        frame = pd.DataFrame([self.row("2026-09-22")])
        with self.assertRaisesRegex(ValueError, "coverage"):
            status.merge_status(self.dataset, action, frame, cal)
        frame = pd.DataFrame([self.row("2026-09-22"), self.row("2026-09-23")])
        frame.loc[1, "tradestatus"] = "bad"
        with self.assertRaisesRegex(ValueError, "invalid status"):
            status.merge_status(self.dataset, action, frame, cal)


class CorporateDailyTests(DailyFixture):
    def setUp(self):
        super().setUp()
        self.preset = patch.object(corporate.universe, "resolve", return_value=["sh.600001"])
        self.preset.start()
        self.addCleanup(self.preset.stop)

    def plan(self, dataset="ths-dividend"):
        return corporate.build_plan(dataset, self.dataset,
                                    observed_on=date(2026, 9, 23))

    def test_plan_approves_exact_baseline_and_stock_bytes(self):
        plan = self.plan()
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(corporate.validate_plan(plan), plan["actions"])
        pd.DataFrame({"code": ["sh.600001"], "value": [1]}).to_parquet(
            symbol_file(self.dataset, "sh.600001"))
        with self.assertRaises(ValueError):
            corporate.validate_plan(plan)
        plan_file = self.root / "plan.json"
        plan_file.write_text(json.dumps(plan))
        with patch.object(corporate, "_fetcher") as fetch:
            with self.assertRaises(PermissionError):
                corporate.main(["--dataset", "ths-dividend", "--dest", str(self.dataset),
                                "--apply", "--plan", str(plan_file),
                                "--approve-sha256", "0" * 64])
            fetch.assert_not_called()

    def test_unchanged_does_not_rewrite_and_revision_preserves_backup(self):
        target = symbol_file(self.dataset, "sh.600001")
        original = pd.DataFrame({"code": ["sh.600001"], "value": [1.0]})
        original.to_parquet(target, index=False)
        plan = self.plan(); before = sha256_file(target)
        fetch = lambda _code: original.copy()
        row = corporate.apply_one(plan, plan["actions"][0], fetch, timeout=2,
                                  backup_root=self.root / "backups")
        self.assertEqual(row["status"], "unchanged")
        self.assertEqual(sha256_file(target), before)
        changed = original.copy(); changed["value"] = [2.0]
        row = corporate.apply_one(plan, plan["actions"][0], lambda _: changed,
                                  timeout=2, backup_root=self.root / "backups")
        self.assertEqual(row["status"], "updated")
        self.assertEqual(row["backup"]["sha256"], before)
        self.assertEqual(pd.read_parquet(target)["value"].tolist(), [2.0])

    def test_empty_regression_never_erases_existing_events(self):
        target = symbol_file(self.dataset, "sh.600001")
        pd.DataFrame({"code": ["sh.600001"], "value": [1.0]}).to_parquet(target)
        plan = self.plan(); before = sha256_file(target)
        with self.assertRaisesRegex(ValueError, "empty history"):
            corporate.apply_one(plan, plan["actions"][0],
                                lambda _: pd.DataFrame(), timeout=2,
                                backup_root=self.root / "backups")
        self.assertEqual(sha256_file(target), before)

    def test_empty_marker_then_new_event_is_backed_up(self):
        marker = self.dataset / "_empty" / "sh_600001.json"
        marker.parent.mkdir()
        marker.write_text('{"code":"sh.600001","status":"empty"}')
        plan = self.plan()
        frame = pd.DataFrame({"code": ["sh.600001"], "value": [1]})
        row = corporate.apply_one(plan, plan["actions"][0], lambda _: frame,
                                  timeout=2, backup_root=self.root / "backups")
        self.assertEqual(row["status"], "new")
        self.assertEqual(row["marker_backup"]["sha256"], plan["actions"][0]["empty_marker_sha256"])
        self.assertFalse(marker.exists())
        self.assertEqual(len(pd.read_parquet(symbol_file(self.dataset, "sh.600001"))), 1)

    def test_baostock_lookback_retains_older_and_rejects_empty_recent(self):
        plan = self.plan("baostock-dividend")
        old = pd.DataFrame({"code": ["sh.600001", "sh.600001"],
                            "report_year_requested": ["2021", "2025"],
                            "value": [1, 2]})
        new = pd.DataFrame({"code": ["sh.600001"],
                            "report_year_requested": ["2025"], "value": [3]})
        merged = corporate._merge_baostock(old, new, 2024)
        self.assertEqual(merged["value"].tolist(), [1, 3])
        with self.assertRaisesRegex(ValueError, "empty recent"):
            corporate._merge_baostock(old, new.iloc[0:0], 2024)
        self.assertEqual(plan["source_window"], {"report_year_start": 2024,
                                                  "report_year_end": 2026})

    def test_failed_run_can_resume_only_missing_symbol(self):
        plan = self.plan()
        calls = []
        def factory(_plan, _timeout):
            def fetch(code):
                calls.append(code)
                if len(calls) == 1:
                    raise RuntimeError("temporary provider error")
                return pd.DataFrame({"code": [code], "value": [7]})
            return fetch, None
        first = corporate.apply(plan, timeout=1, throttle=0, retries=1,
                                fetch_factory=factory)
        self.assertEqual(first["run_status"], "finished_with_errors")
        second = corporate.apply(plan, timeout=1, throttle=0, retries=1,
                                 resume_run=True, fetch_factory=factory)
        self.assertEqual(second["run_status"], "finished")
        self.assertEqual(calls, ["sh.600001", "sh.600001"])
        with self.assertRaises(ValueError):
            corporate.apply(plan, resume_run=True, fetch_factory=factory)

    def test_digest_ignores_vendor_row_order_but_preserves_duplicates(self):
        a = pd.DataFrame({"code": ["sh.600001", "sh.600001"], "v": [1, 2]})
        b = a.iloc[::-1].reset_index(drop=True)
        self.assertEqual(logical_frame_digest(a), logical_frame_digest(b))
        self.assertNotEqual(logical_frame_digest(a),
                            logical_frame_digest(pd.concat([a, a.iloc[[0]]])))


if __name__ == "__main__":
    unittest.main()
