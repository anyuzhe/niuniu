import json
import sys
import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import baostock_dividend as dividend_mod
from collect import baostock_reference_snapshot as reference_mod
from collect import baostock_daily_status as status_mod
from collect import bars_incremental as apply_mod
from collect import migrate_empty_parquet as migration_mod
from collect import ths_dividend as ths_mod
from collect import coverage
from collect import scan_gaps


BAR_SCHEMA = {
    "date": pl.Date, "code": pl.String,
    "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
    "close": pl.Float64, "volume": pl.Int64, "amount": pl.Float64,
    "adjustflag": pl.String, "fetch_ts": pl.String,
}


def write_bar(path: Path, code: str, days: list[str]):
    frame = pl.DataFrame({
        "date": [date.fromisoformat(day) for day in days],
        "code": [code] * len(days),
        "open": [1.0] * len(days), "high": [1.0] * len(days),
        "low": [1.0] * len(days), "close": [1.0] * len(days),
        "volume": [100] * len(days), "amount": [100.0] * len(days),
        "adjustflag": ["3"] * len(days), "fetch_ts": ["old"] * len(days),
    }, schema=BAR_SCHEMA)
    frame.write_parquet(path)


class GapPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.dataset = root / "daily"
        self.dataset.mkdir()
        self.calendar = root / "calendar.parquet"
        pd.DataFrame({
            "calendar_date": ["2026-09-18", "2026-09-19", "2026-09-20",
                              "2026-09-21", "2026-09-22"],
            "is_trading_day": ["1", "0", "0", "1", "1"],
        }).to_parquet(self.calendar)
        self.stock_basic = root / "stock_basic.parquet"
        pd.DataFrame([
            {"code": "sh.600001", "ipoDate": "2020-01-01", "type": "1", "status": "1"},
            {"code": "sh.600002", "ipoDate": "2020-01-01", "type": "1", "status": "1"},
            {"code": "sh.600003", "ipoDate": "2026-09-21", "type": "1", "status": "1"},
            {"code": "sh.600004", "ipoDate": "2020-01-01", "type": "1", "status": "0"},
            {"code": "sh.000001", "ipoDate": "1991-01-01", "type": "2", "status": "1"},
        ]).to_parquet(self.stock_basic)
        write_bar(self.dataset / "sh_600001.parquet", "sh.600001",
                  ["2026-09-18", "2026-09-21", "2026-09-22"])
        write_bar(self.dataset / "sh_600002.parquet", "sh.600002", ["2026-09-18"])
        write_bar(self.dataset / "sh_600004.parquet", "sh.600004", ["2026-09-18"])

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **kwargs):
        return scan_gaps.build_plan(
            "baostock-daily", target_end=date(2026, 9, 22),
            calendar_path=self.calendar, stock_basic_path=self.stock_basic,
            dataset_dir=self.dataset, **kwargs)

    def test_calendar_skips_weekend(self):
        cal = coverage.TradingCalendar(self.calendar)
        self.assertEqual(cal.between(date(2026, 9, 18), date(2026, 9, 22)),
                         [date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 22)])

    def test_default_target_uses_close_cutoff(self):
        cal = coverage.TradingCalendar(self.calendar)
        before = coverage.default_target_end(cal, datetime(2026, 9, 22, 17, 59))
        after = coverage.default_target_end(cal, datetime(2026, 9, 22, 18, 0))
        self.assertEqual(before, date(2026, 9, 21))
        self.assertEqual(after, date(2026, 9, 22))

    def test_min5_refreshes_partial_target_day(self):
        plan = scan_gaps.build_plan(
            "baostock-min5", target_end=date(2026, 9, 22),
            calendar_path=self.calendar, stock_basic_path=self.stock_basic,
            dataset_dir=self.dataset)
        actions = {row["symbol"]: row for row in plan["actions"]}
        self.assertEqual(actions["sh.600001"]["action"], "refresh_last")
        self.assertEqual(actions["sh.600001"]["fetch_start"], "2026-09-22")

    def test_plan_detects_tail_and_missing_symbol_and_excludes_delisted(self):
        plan = self.build()
        self.assertEqual(plan["universe"]["listed_symbols"], 3)
        self.assertEqual(plan["universe"]["excluded_nonlisted_files"], 1)
        self.assertEqual(plan["summary"]["up_to_date"], 1)
        self.assertEqual(plan["summary"]["tail"], 1)
        self.assertEqual(plan["summary"]["full"], 1)
        actions = {row["symbol"]: row for row in plan["actions"]}
        self.assertEqual(actions["sh.600002"]["fetch_start"], "2026-09-18")
        self.assertEqual(actions["sh.600003"]["fetch_start"], "2026-09-21")
        self.assertNotIn("sh.600004", actions)

    def test_plan_is_deterministic_and_limit_is_hash_bound(self):
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        limited = self.build(action_limit=1)
        self.assertEqual(limited["summary"]["actions_total"], 2)
        self.assertEqual(limited["summary"]["actions_in_plan"], 1)
        self.assertNotEqual(first["plan_sha256"], limited["plan_sha256"])
        self.assertEqual(limited["plan_sha256"], scan_gaps.canonical_digest(limited))

    def test_vendor_floor_is_not_reported_as_retryable_history(self):
        cal = coverage.TradingCalendar(self.calendar)
        missing = {"present": False, "rows": 0, "min_date": None,
                   "max_date": None, "days": set()}
        result = coverage.compute_gap(
            missing, cal, target_end=date(2026, 9, 22),
            first_start=date(2010, 1, 1), vendor_floor=date(2026, 9, 21))
        self.assertEqual(result["fetch_start"], date(2026, 9, 21))
        self.assertTrue(result["known_vendor_limit"])


class ThsCollectorTests(unittest.TestCase):
    def test_http_200_stock_page_without_tables_is_typed_empty_evidence(self):
        def no_tables(**_kwargs):
            raise ValueError("No tables found")

        response = SimpleNamespace(
            status_code=200,
            content=b"<title>Test Corp (600001) dividend</title>",
            text="<title>Test Corp (600001) dividend</title>",
            encoding=None,
        )
        fake_akshare = SimpleNamespace(stock_fhps_detail_ths=no_tables)
        fake_requests = SimpleNamespace(get=lambda *_args, **_kwargs: response)
        with patch.dict(sys.modules, {"akshare": fake_akshare, "requests": fake_requests}):
            frame = ths_mod.make_fetcher()("sh.600001")
        self.assertEqual(len(frame), 0)
        self.assertEqual(frame.attrs["http_status"], 200)
        self.assertEqual(frame.attrs["table_count"], 0)
        self.assertEqual(len(frame.attrs["response_sha256"]), 64)


class EmptyMigrationTests(unittest.TestCase):
    def test_verified_empty_parquet_is_backed_up_and_replaced_by_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dest = root / "dataset"; dest.mkdir()
            source = dest / "sh_600001.parquet"
            pd.DataFrame(columns=["code", "value"]).to_parquet(source, index=False)
            receipt = root / "source-receipt.json"
            from collect.envelope import sha256_file
            receipt.write_text(json.dumps({"empty": [{"code": "sh.600001",
                                                       "sha256": sha256_file(source)}]}))
            plan = migration_mod.build_plan(dest, receipt)
            backup = root / "backup"
            self.assertEqual(migration_mod.main([
                "--dest", str(dest), "--receipt", str(receipt), "--apply",
                "--approve-sha256", plan["plan_sha256"],
                "--backup-root", str(backup)]), 0)
            self.assertFalse(source.exists())
            self.assertTrue((backup / source.name).is_file())
            marker = dest / "_empty" / "sh_600001.json"
            self.assertEqual(json.loads(marker.read_text())["status"], "empty")


class StatusCollectorTests(unittest.TestCase):
    def test_review_mode_does_not_start_status_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "status"
            listed = {"sh.600001": date(2020, 1, 1)}
            with patch.object(status_mod.coverage, "listed_a_shares", return_value=listed), \
                 patch.object(status_mod, "StatusSession") as session:
                self.assertEqual(status_mod.main(["--dest", str(dest), "--limit", "1",
                                                  "--end", "2026-09-22"]), 0)
                session.assert_not_called()
            self.assertFalse(dest.exists())


class DividendCollectorTests(unittest.TestCase):
    def test_review_mode_does_not_start_provider_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "dividend"
            listed = {"sh.600001": date(2020, 1, 1)}
            with patch.object(dividend_mod.coverage, "listed_a_shares", return_value=listed), \
                 patch.object(dividend_mod, "DividendSession") as session:
                self.assertEqual(dividend_mod.main(["--dest", str(dest), "--limit", "1"]), 0)
                session.assert_not_called()
            self.assertFalse(dest.exists())


class ReferenceSnapshotTests(unittest.TestCase):
    def test_plan_is_deterministic_and_date_bound(self):
        dest = Path("/tmp/reference-test")
        first = reference_mod.build_plan(date(2026, 9, 22), dest)
        second = reference_mod.build_plan(date(2026, 9, 22), dest)
        self.assertEqual(first, second)
        self.assertNotEqual(first["plan_sha256"],
                            reference_mod.build_plan(date(2026, 9, 21), dest)["plan_sha256"])

    def test_review_and_bad_approval_do_not_create_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "batch"
            self.assertEqual(reference_mod.main([
                "--snapshot-date", "2026-09-22", "--dest", str(dest)]), 0)
            self.assertFalse(dest.exists())
            self.assertEqual(reference_mod.main([
                "--snapshot-date", "2026-09-22", "--dest", str(dest),
                "--apply", "--approve-sha256", "0" * 64]), 2)
            self.assertFalse(dest.exists())


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "daily"
        self.dataset.mkdir()
        write_bar(self.dataset / "sh_600001.parquet", "sh.600001", ["2026-09-18"])
        self.calendar = self.root / "calendar.parquet"
        pd.DataFrame({"calendar_date": ["2026-09-18", "2026-09-21"],
                      "is_trading_day": ["1", "1"]}).to_parquet(self.calendar)
        self.stock = self.root / "stock.parquet"
        pd.DataFrame([{"code": "sh.600001", "ipoDate": "2020-01-01",
                       "type": "1", "status": "1"}]).to_parquet(self.stock)
        self.plan = scan_gaps.build_plan(
            "baostock-daily", target_end=date(2026, 9, 21),
            calendar_path=self.calendar, stock_basic_path=self.stock,
            dataset_dir=self.dataset)
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_review_mode_never_initializes_provider(self):
        with patch.object(apply_mod, "_provider_fetcher") as provider:
            self.assertEqual(apply_mod.main(["--plan", str(self.plan_path)]), 0)
            provider.assert_not_called()

    def test_apply_requires_exact_approval_hash_before_provider(self):
        with patch.object(apply_mod, "_provider_fetcher") as provider:
            with self.assertRaises(PermissionError):
                apply_mod.main(["--plan", str(self.plan_path), "--apply"])
            with self.assertRaises(PermissionError):
                apply_mod.main(["--plan", str(self.plan_path), "--apply",
                                "--approve-sha256", "0" * 64])
            provider.assert_not_called()

    def test_tampered_plan_is_rejected(self):
        payload = dict(self.plan)
        payload["target_end"] = "2099-01-01"
        self.plan_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            apply_mod.load_plan(self.plan_path)

    def test_stale_target_is_rejected_before_network(self):
        with patch.dict(scan_gaps.DATASETS["baostock-daily"], {"dir": self.dataset}):
            checked = apply_mod.validate_plan_state(self.plan)
            self.assertEqual(len(checked), 1)
            with (self.dataset / "sh_600001.parquet").open("ab") as handle:
                handle.write(b"changed")
            with self.assertRaises(ValueError):
                apply_mod.validate_plan_state(self.plan)

    def test_provider_request_timeout_interrupts_stall(self):
        def stalled(_symbol, _start, _end):
            time.sleep(1)
            return []
        with self.assertRaises(TimeoutError):
            apply_mod.call_with_timeout(stalled, "sh.600001", "2026-09-18",
                                        "2026-09-21", 0.02)

    def test_receipt_checkpoint_is_atomic_and_readable(self):
        path = self.root / "receipt.json"
        apply_mod.write_receipt_checkpoint(path, {"run_status": "running", "n": 1})
        self.assertEqual(json.loads(path.read_text()), {"run_status": "running", "n": 1})
        self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_merge_replaces_approved_last_day(self):
        action = dict(self.plan["actions"][0])
        action["path"] = self.dataset / "sh_600001.parquet"
        rows = [["2026-09-18", "sh.600001", "2", "2", "2", "2", "200", "400", "3", "1"],
                ["2026-09-21", "sh.600001", "3", "3", "3", "3", "300", "900", "3", "1"]]
        schema = pl.read_parquet_schema(action["path"])
        merged, stats = apply_mod.merge_rows(action, rows, "baostock-daily", schema)
        self.assertEqual(merged.height, 2)
        self.assertEqual(stats["returned_end"], "2026-09-21")
        self.assertEqual(merged.filter(pl.col("date") == date(2026, 9, 18))["close"][0], 2.0)

    def test_suspended_daily_rows_are_not_filled_with_zero(self):
        action = dict(self.plan["actions"][0])
        action["path"] = self.dataset / "sh_600001.parquet"
        rows = [["2026-09-18", "sh.600001", "", "", "", "", "", "", "3", "0"],
                ["2026-09-21", "sh.600001", "3", "3", "3", "3", "300", "900", "3", "1"]]
        schema = pl.read_parquet_schema(action["path"])
        merged, stats = apply_mod.merge_rows(action, rows, "baostock-daily", schema)
        self.assertEqual(stats["suspended_rows_ignored"], 1)
        self.assertEqual(merged.filter(pl.col("date") == date(2026, 9, 18))["close"][0], 1.0)
        self.assertEqual(merged.filter(pl.col("date") == date(2026, 9, 21))["close"][0], 3.0)

    def test_all_suspended_daily_rows_are_explicit_not_empty_data(self):
        action = dict(self.plan["actions"][0])
        action["path"] = self.dataset / "sh_600001.parquet"
        rows = [["2026-09-18", "sh.600001", "", "", "", "", "", "", "3", "0"]]
        schema = pl.read_parquet_schema(action["path"])
        with self.assertRaises(apply_mod.SuspendedRange):
            apply_mod.merge_rows(action, rows, "baostock-daily", schema)


if __name__ == "__main__":
    unittest.main()
