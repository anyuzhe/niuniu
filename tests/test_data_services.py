import json
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from quantlab.data import day_seals
from quantlab.data.data_services import DataStatusService, DataUpdateJobs
from quantlab.data.research_provider import InvalidRequest

TZ = ZoneInfo("Asia/Shanghai")


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
