import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

from quantlab.data import day_seals
from quantlab.data.data_services import DataPreviewService, DataStatusService, DataUpdateJobs, runner_alive
from quantlab.data.research_provider import DataProviderError, InvalidRequest

TZ = ZoneInfo("Asia/Shanghai")
REPO = Path(__file__).resolve().parents[1]


def write_parquet(path: Path, rows: int = 3):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"code": [f"60000{i}" for i in range(rows)], "v": range(rows)}).to_parquet(path, index=False)


class Lake:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "catalog").mkdir()
        (self.root / "catalog/dataset_registry.json").write_text("{}")
        snap = self.root / "lake/bronze/provider=baostock/reference_snapshots/snapshot=2026-09-24"
        snap.mkdir(parents=True)
        pd.DataFrame({"calendar_date": ["2026-09-23", "2026-09-24", "2026-09-25"],
                      "is_trading_day": ["1", "1", "0"]}).to_parquet(snap / "trade_calendar.parquet")
        (snap / "manifest.json").write_text("{}")
        base = self.root / "lake/bronze/provider=ths/limit_up_pool"
        write_parquet(base / "2026-09-24.parquet")
        (base / "_receipts").mkdir()
        (base / "_receipts/public-x.json").write_text(json.dumps(
            {"results": {"2026-09-24": {"status": "ok", "observed_at": "2026-09-24T10:00:00+00:00"}}}))
        write_parquet(self.root / "lake/bronze/provider=eastmoney/monitor_pool/2026-09-24.parquet", 2)


class SealTests(unittest.TestCase):
    def setUp(self):
        self.lake = Lake()
        self.root = self.lake.root

    def tearDown(self):
        self.lake.tmp.cleanup()

    def test_seal_pending_missing_verify_and_guard(self):
        plan = day_seals.plan(self.root, "2026-09-24", today="2026-09-25")
        sealed_ids = {s["dataset_id"] for s in plan["seal_now"]}
        self.assertTrue({"limit_up_pool_ths", "monitor_pool_em", "reference_snapshot_baostock"} <= sealed_ids)
        self.assertIn("announcements_cninfo", {p["dataset_id"] for p in plan["pending"]})
        self.assertIn("share_buyback_em", {p["dataset_id"] for p in plan["missing"]})
        manifest = day_seals.seal(self.root, "2026-09-24", log=lambda *_: None)
        self.assertEqual(manifest["revision"], 1)
        entry = next(e for e in manifest["entries"] if e["dataset_id"] == "limit_up_pool_ths")
        self.assertEqual(entry["files"][0]["rows"], 3)
        self.assertEqual(entry["observed_at"], "2026-09-24T10:00:00+00:00")
        self.assertTrue(day_seals.is_sealed_path(self.root, self.root / "lake/bronze/provider=ths/limit_up_pool",
                                                 "2026-09-24"))
        self.assertFalse(day_seals.is_sealed(self.root, "announcements_cninfo", "2026-09-24"))
        self.assertEqual(day_seals.verify(self.root, "2026-09-24", log=lambda *_: None)["verify_status"], "ok")
        # a pending item arrives later and is added as revision 2; sealed entries unchanged
        write_parquet(self.root / "lake/bronze/provider=cninfo/announcements/2026-09-24.parquet")
        again = day_seals.seal(self.root, "2026-09-24", log=lambda *_: None)
        self.assertEqual(again["revision"], 2)
        self.assertIn("announcements_cninfo", {e["dataset_id"] for e in again["entries"]})
        # tamper -> mismatch
        write_parquet(self.root / "lake/bronze/provider=ths/limit_up_pool/2026-09-24.parquet", 5)
        check = day_seals.verify(self.root, "2026-09-24", log=lambda *_: None)
        self.assertEqual(check["verify_status"], "mismatch")
        self.assertEqual(check["problems"][0]["problem"], "changed")
        recent = day_seals.recent(self.root)
        self.assertEqual(recent[0]["verify_status"], "mismatch")

    def test_revoke_then_seal_again_keeps_every_revision(self):
        quiet = lambda *_: None  # noqa: E731
        day_seals.seal(self.root, "2026-09-24", log=quiet)
        day_seals.verify(self.root, "2026-09-24", log=quiet)
        first = (self.root / "catalog/seals/_history/2026-09-24.r1.json").read_bytes()
        day_seals.revoke(self.root, "2026-09-24", "重采涨停池", log=quiet)
        write_parquet(self.root / "lake/bronze/provider=ths/limit_up_pool/2026-09-24.parquet", 5)
        again = day_seals.seal(self.root, "2026-09-24", log=quiet)
        # numbering continues after a revoke, so the revoked revision stays in _history untouched
        self.assertEqual(again["revision"], 2)
        self.assertEqual((self.root / "catalog/seals/_history/2026-09-24.r1.json").read_bytes(), first)
        # the old verification went with the revoked seal; the new one has not been verified yet
        self.assertEqual(day_seals.recent(self.root)[0]["verify_status"], "never")
        self.assertTrue(any((self.root / "catalog/seals/_revoked").glob("2026-09-24-*/verify.json")))
        self.assertEqual(day_seals.plan(self.root, "2026-09-24", today="2026-09-25")["revision"], 2)

    def test_revoke_moves_files(self):
        day_seals.seal(self.root, "2026-09-24", log=lambda *_: None)
        with self.assertRaises(day_seals.SealError):
            day_seals.revoke(self.root, "2026-09-24", "", log=lambda *_: None)
        record = day_seals.revoke(self.root, "2026-09-24", "重采涨停池", log=lambda *_: None)
        self.assertGreater(record["moved_files"], 0)
        self.assertIsNone(day_seals.load_manifest(self.root, "2026-09-24"))
        self.assertFalse((self.root / "lake/bronze/provider=ths/limit_up_pool/2026-09-24.parquet").exists())
        self.assertTrue(any((self.root / "catalog/seals/_revoked").rglob("2026-09-24.parquet")))


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.lake = Lake()
        self.root = self.lake.root
        self.now = datetime(2026, 9, 24, 23, 0, tzinfo=TZ)
        self.jobs = DataUpdateJobs(self.root, now_fn=lambda: self.now)

    def tearDown(self):
        self.lake.tmp.cleanup()

    def test_list_and_plans(self):
        ids = {j["job_id"] for j in self.jobs.list_jobs()["jobs"]}
        self.assertTrue({"daily_close_update", "sector_recorder_start", "sector_recorder_stop", "backfill_day",
                         "seal_day", "verify_seal", "revoke_seal"} <= ids)
        plan = self.jobs.plan("daily_close_update", {"date": "2026-09-24"})
        self.assertIsNone(plan["blocked_reason"])
        actions = {s["name"]: s["action"] for s in plan["steps"]}
        self.assertEqual(actions["参考快照"], "skip_existing")
        self.assertEqual(actions["封存"], "seal")
        self.assertTrue(any(s["overwrites"] for s in plan["steps"]))
        self.assertIsNotNone(plan["expires_at"])
        holiday = self.jobs.plan("daily_close_update", {"date": "2026-09-25"})
        self.assertEqual(holiday["blocked_reason"], "2026-09-25 不是交易日")
        with self.assertRaises(InvalidRequest):
            self.jobs.plan("nope", {})
        with self.assertRaises(InvalidRequest):
            self.jobs.plan("seal_day", {"bad": 1})

    def test_sealed_day_blocks_backfill(self):
        day_seals.seal(self.root, "2026-09-24", log=lambda *_: None)
        plan = self.jobs.plan("backfill_day", {"date": "2026-09-24"})
        fetch = [s for s in plan["steps"] if s["action"] == "fetch"]
        self.assertFalse(any("limit_up_pool_ths" in s["datasets"] for s in fetch))
        stop = self.jobs.plan("sector_recorder_stop", {})
        self.assertEqual(stop["blocked_reason"], "盘中记录器没有在运行")

    def test_today_is_accepted_for_a_required_date(self):
        from quantlab.data.data_services import _date_param
        self.assertEqual(_date_param({"date": "today"}, "date", required=True, today="2026-09-24"), "2026-09-24")
        with self.assertRaises(InvalidRequest):
            _date_param({}, "date", required=True, today="2026-09-24")
        with self.assertRaises(InvalidRequest):
            self.jobs.run("../plans/x")

    def test_disk_missing_blocks(self):
        jobs = DataUpdateJobs(self.root / "nope", now_fn=lambda: self.now)
        self.assertIn("数据盘未连接", jobs.plan("seal_day", {"date": "2026-09-24"})["blocked_reason"])

    def test_run_seal_in_background_and_read_status(self):
        plan = self.jobs.plan("seal_day", {"date": "2026-09-24"})
        self.assertIsNone(plan["blocked_reason"])
        run = self.jobs.run(plan["plan_id"])
        for _ in range(60):
            state = self.jobs.status(run["run_id"])
            if state["state"] not in ("queued", "running"):
                break
            time.sleep(0.5)
        self.assertEqual(state["state"], "succeeded", self.jobs.log(run["run_id"])["lines"][-20:])
        self.assertEqual(state["result"]["seal"]["date"], "2026-09-24")
        self.assertTrue(self.jobs.log(run["run_id"])["lines"])
        self.assertEqual(self.jobs.list_runs()["runs"][0]["run_id"], run["run_id"])
        again = self.jobs.plan("seal_day", {"date": "2026-09-24"})
        self.assertIn("已封存", again["blocked_reason"])
        seals = DataStatusService(self.root, now_fn=lambda: self.now).list_status()["seals"]
        self.assertEqual(seals[0]["verify_status"], "ok")


class CalendarLake:
    """Reference snapshot of 2026-09-24 whose trade calendar runs 2026-09-14..09-25 (weekends closed)."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "catalog").mkdir()
        (self.root / "catalog/dataset_registry.json").write_text("{}")
        snap = self.root / "lake/bronze/provider=baostock/reference_snapshots/snapshot=2026-09-24"
        snap.mkdir(parents=True)
        days = [date(2026, 9, 14) + timedelta(days=i) for i in range(12)]
        pd.DataFrame({"calendar_date": [d.isoformat() for d in days],
                      "is_trading_day": ["1" if d.weekday() < 5 else "0" for d in days]}).to_parquet(
            snap / "trade_calendar.parquet")
        (snap / "manifest.json").write_text("{}")


class PublicStepsTests(unittest.TestCase):
    def setUp(self):
        self.lake = CalendarLake()
        self.root = self.lake.root

    def tearDown(self):
        self.lake.tmp.cleanup()

    def plan(self, now, job_id, params):
        return DataUpdateJobs(self.root, now_fn=lambda: now.replace(tzinfo=TZ)).plan(job_id, params)

    @staticmethod
    def fetched(plan, dataset_id):
        return sorted(p[2] for s in plan["steps"] if s["action"] == "fetch"
                      for p in s.get("public") or [] if p[1] == dataset_id)

    def test_backfill_hands_the_collectors_a_calendar_that_covers_the_day(self):
        # the only snapshot is 09-24's; the collectors used to be told to read snapshot=2026-09-21
        plan = self.plan(datetime(2026, 9, 24, 20), "backfill_day", {"date": "2026-09-21"})
        self.assertIsNone(plan["blocked_reason"])
        step = next(s for s in plan["steps"] if s["action"] == "fetch")
        self.assertEqual(step["calendar"], "2026-09-24")
        out = self.root / "ths-plan.json"
        proc = subprocess.run([sys.executable, str(REPO / "scripts/collect/public_sources.py"), "--data-root",
                               str(self.root), "plan", "--dataset", "ths_limit_up", "--out", str(out),
                               "--today", "2026-09-21", "--calendar-snapshot", step["calendar"],
                               "--start", "2026-09-21", "--end", "2026-09-21"],
                              capture_output=True, text=True, cwd=REPO)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertEqual(json.loads(out.read_text())["partitions"], ["2026-09-21"])
        late = self.plan(datetime(2026, 9, 27, 20), "backfill_day", {"date": "2026-09-26"})
        self.assertIn("没有覆盖 2026-09-26 的交易日历", late["blocked_reason"])

    def test_close_update_covers_the_days_nobody_ran_it(self):
        monday = self.plan(datetime(2026, 9, 21, 20), "daily_close_update", {"date": "2026-09-21"})
        self.assertIsNone(monday["blocked_reason"])
        self.assertEqual(self.fetched(monday, "announcements_cninfo"), ["2026-09-18", "2026-09-19", "2026-09-20"])
        self.assertEqual(self.fetched(monday, "institution_survey_em"), ["2026-09-19", "2026-09-20", "2026-09-21"])
        self.assertEqual(self.fetched(monday, "holder_trades_em"), ["2026-09-19", "2026-09-20", "2026-09-21"])
        self.assertEqual(self.fetched(monday, "margin_detail_exchange"), ["2026-09-18"])
        self.assertEqual(self.fetched(monday, "limit_up_pool_ths"), ["2026-09-21"])
        public = [s for s in monday["steps"] if s["kind"] == "public" and s["action"] == "fetch"]
        self.assertTrue(public and all(s["calendar"] == "2026-09-21" for s in public))
        tuesday = self.plan(datetime(2026, 9, 22, 20), "daily_close_update", {"date": "2026-09-22"})
        self.assertEqual(self.fetched(tuesday, "announcements_cninfo"), ["2026-09-21"])
        self.assertEqual(self.fetched(tuesday, "institution_survey_em"), ["2026-09-22"])


class JobProcessTests(unittest.TestCase):
    RUN = "20260924-090000-abcdef"

    def setUp(self):
        self.lake = Lake()
        self.root = self.lake.root
        self.now = datetime(2026, 9, 24, 9, 0, tzinfo=TZ)
        self.fake_python = self.root / "fake_python.sh"
        self.fake_python.write_text("#!/bin/sh\nsleep 2\n")
        self.fake_python.chmod(0o755)

    def tearDown(self):
        self.lake.tmp.cleanup()

    def jobs(self, root=None, python=None):
        return DataUpdateJobs(root or self.root, python=python or str(self.fake_python), now_fn=lambda: self.now)

    def running_run(self, pid, *, hold_lock):
        import fcntl
        run_dir = self.root / "catalog/jobs/runs" / self.RUN
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text(json.dumps({
            "run_id": self.RUN, "job_id": "sector_recorder_start", "state": "running", "pid": pid,
            "created_at": "2026-09-24T09:00:00+08:00", "result": {"datasets": [], "seal": None}}))
        handle = (run_dir / "runner.lock").open("a+")
        self.addCleanup(handle.close)
        if hold_lock:
            fcntl.flock(handle, fcntl.LOCK_EX)
        return run_dir

    def test_two_launchers_start_the_recorder_once(self):
        for _ in range(5):
            lake = Lake()
            try:
                barrier, results = threading.Barrier(2), []

                def launcher():
                    jobs = self.jobs(lake.root)
                    barrier.wait()
                    results.append(jobs.autostart())

                threads = [threading.Thread(target=launcher) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(30)
                self.assertEqual(sorted(r["started"] for r in results), [False, True])
                self.assertEqual(len(list((lake.root / "catalog/jobs/runs").glob("*/state.json"))), 1)
            finally:
                lake.tmp.cleanup()

    def test_a_reused_pid_is_not_taken_for_the_runner(self):
        # after a restart the old pid belongs to another live process, but the runner's lock is free
        self.running_run(os.getpid(), hold_lock=False)
        jobs = self.jobs()
        with mock.patch("os.killpg") as killpg, mock.patch("os.kill", wraps=os.kill) as kill:
            self.assertEqual(jobs.cancel(self.RUN)["state"], "interrupted")
        killpg.assert_not_called()
        self.assertFalse([c for c in kill.call_args_list if c.args[1:] == (signal.SIGTERM,)])
        self.assertIsNone(jobs.plan("sector_recorder_start", {})["blocked_reason"])

    def test_cancel_signals_a_live_runner_and_reports_how_it_ended(self):
        run_dir = self.running_run(999_999, hold_lock=True)
        self.assertTrue(runner_alive(run_dir, json.loads((run_dir / "state.json").read_text())))

        def runner_finishes(pid, sig):  # the runner writes its own final state when signalled
            state = json.loads((run_dir / "state.json").read_text())
            state["state"] = "succeeded"
            (run_dir / "state.json").write_text(json.dumps(state))

        with mock.patch("os.killpg", side_effect=runner_finishes) as killpg:
            self.assertEqual(self.jobs().cancel(self.RUN)["state"], "succeeded")
        killpg.assert_called_once_with(999_999, signal.SIGTERM)

    def test_a_start_that_fails_does_not_block_the_job(self):
        jobs = self.jobs(python=str(self.root / "no-such-python"))
        plan = jobs.plan("seal_day", {"date": "2026-09-24"})
        with self.assertRaises(DataProviderError):
            jobs.run(plan["plan_id"])
        self.assertEqual(jobs.list_runs()["runs"][0]["state"], "failed")
        self.assertIsNone(jobs.plan("seal_day", {"date": "2026-09-24"})["blocked_reason"])


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.lake = Lake()
        self.root = self.lake.root
        daily = self.root / "lake/bronze/provider=baostock/stock_kline_daily"
        daily.mkdir(parents=True)
        pd.DataFrame({"date": [f"2026-09-{d:02d}" for d in range(1, 25)], "code": "sh.600000",
                      "close": [float(d) for d in range(24)]}).to_parquet(daily / "sh_600000.parquet")
        entries = [{"dataset_id": d, "status": "READY", "delivery": "FILE"}
                   for d in ("bars_daily_baostock_raw", "limit_up_pool_ths")]
        patcher = mock.patch("quantlab.data.data_services._catalog_entries", return_value=entries)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = DataPreviewService(self.root)

    def tearDown(self):
        self.lake.tmp.cleanup()

    def test_per_symbol_preview_counts_the_whole_file(self):
        value = self.service.preview("bars_daily_baostock_raw", limit=5)
        self.assertEqual((value["total_rows"], value["truncated"], len(value["rows"])), (24, True, 5))
        self.assertEqual(value["rows"][0]["date"], "2026-09-24")
        one = self.service.preview("bars_daily_baostock_raw", limit=5, filters={"date": "2026-09-10"})
        self.assertEqual((one["total_rows"], one["truncated"]), (1, False))

    def test_filters_are_validated_and_codes_normalised(self):
        from quantlab.data.data_services import _preview_code
        for filters in ({"date": "../../../../../outside"}, {"date": "2026/09/24"}, {"code": "../../x"},
                        {"code": "60051"}):
            with self.assertRaises(InvalidRequest, msg=str(filters)):
                self.service.preview("limit_up_pool_ths", filters=filters)
        self.assertEqual([_preview_code(c) for c in ("920001", "430047", "600519", "900901", "000001", "SZ300750",
                                                     "sh.600000")],
                         ["bj.920001", "bj.430047", "sh.600519", "sh.900901", "sz.000001", "sz.300750", "sh.600000"])
        value = self.service.preview("limit_up_pool_ths", filters={"code": "sh.600001", "date": "2026-09-24"})
        self.assertEqual(value["total_rows"], 1)


class AutostartTests(unittest.TestCase):
    def test_autostart_only_whitelisted_and_respects_blocks(self):
        lake = Lake()
        try:
            jobs = DataUpdateJobs(lake.root, now_fn=lambda: datetime(2026, 9, 24, 8, 30, tzinfo=TZ))
            started = []
            jobs.run = lambda plan_id, trigger="user": started.append((plan_id, trigger)) or {"run_id": "r1"}
            with self.assertRaises(InvalidRequest):
                jobs.autostart("daily_close_update")
            result = jobs.autostart()
            self.assertTrue(result["started"])
            self.assertEqual(started[0][1], "autostart")
            holiday = DataUpdateJobs(lake.root, now_fn=lambda: datetime(2026, 9, 25, 8, 30, tzinfo=TZ))
            self.assertEqual(holiday.autostart()["reason"], "今天不是交易日")
            late = DataUpdateJobs(lake.root, now_fn=lambda: datetime(2026, 9, 24, 16, 0, tzinfo=TZ))
            self.assertEqual(late.autostart()["reason"], "今天已收盘")
        finally:
            lake.tmp.cleanup()


class StatusIndexTests(unittest.TestCase):
    def test_index_never_writes_into_data_files(self):
        from quantlab.data.data_services import refresh_status_index
        lake = Lake()
        try:
            base = lake.root / "lake/bronze/provider=baostock/stock_kline_daily"
            for code in ("sh_600000", "sz_300750"):
                path = base / f"{code}.parquet"
                path.parent.mkdir(parents=True, exist_ok=True)
                pd.DataFrame({"date": ["2026-09-23", "2026-09-24"], "close": [1.0, 2.0]}).to_parquet(path)
            index = refresh_status_index(lake.root, log=lambda *_: None)
            for path in base.glob("*.parquet"):
                self.assertEqual(path.read_bytes()[:4], b"PAR1")
            self.assertTrue((lake.root / "catalog/dataset_status.json").is_file())
            entry = index["datasets"]["bars_daily_baostock_raw"]
            self.assertEqual((entry["rows"], entry["files"], entry["latest_date"]), (4, 2, "2026-09-24"))
        finally:
            lake.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
