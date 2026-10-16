import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import scheduler as s  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")


class FakeJobs:
    def __init__(self, root):
        self.base = root / "catalog/jobs"
        self.data_root = root
        self.runs, self.started, self.autostarts = [], [], 0
        self.early_started, self.same_day_started, self.blocked, self.same_day_blocked = [], [], None, None

    def _runs(self):
        return self.runs

    def _running(self, ids):
        return next((r for r in self.runs if r["job_id"] in ids and r["state"] in ("queued", "running")), None)

    def autostart(self, job_id):
        self.autostarts += 1
        return {"started": True, "job_id": job_id, "reason": None, "run_id": "r"}

    def plan(self, job_id, params):
        blocked = self.same_day_blocked if job_id == "same_day_public" else self.blocked
        return {"plan_id": f"{job_id}|{params['date']}", "blocked_reason": blocked}

    def run(self, plan_id, trigger):
        job_id, day = plan_id.split("|")
        {"daily_close_update": self.started, "same_day_public": self.same_day_started}.get(
            job_id, self.early_started).append(day)
        self.runs.append({"job_id": job_id, "params": {"date": day}, "state": "running",
                          "created_at": "2026-09-29T16:30:00"})
        return {"run_id": "run-" + day}


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "catalog/seals").mkdir(parents=True)
        (self.root / "catalog/seals/2026-09-24.json").write_text("{}")
        self.jobs = FakeJobs(self.root)
        self.trading = s.TradingDays(fetch=lambda: {"2026-09-23", "2026-09-24", "2026-09-28", "2026-09-29"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_recorder_once_per_day_in_window(self):
        memo = {}
        s.tick(self.jobs, self.root, datetime(2026, 9, 29, 9, 5, tzinfo=TZ), self.trading, memo)
        self.assertEqual(self.jobs.autostarts, 0)
        s.tick(self.jobs, self.root, datetime(2026, 9, 29, 9, 11, tzinfo=TZ), self.trading, memo)
        s.tick(self.jobs, self.root, datetime(2026, 9, 29, 9, 12, tzinfo=TZ), self.trading, memo)
        self.assertEqual(self.jobs.autostarts, 1)
        s.tick(self.jobs, self.root, datetime(2026, 10, 3, 9, 30, tzinfo=TZ), self.trading, memo)  # Saturday
        self.assertEqual(self.jobs.autostarts, 1)

    def test_close_updates_oldest_first_one_at_a_time(self):
        memo = {}
        s.tick(self.jobs, self.root, datetime(2026, 9, 29, 15, 30, tzinfo=TZ), self.trading, memo)
        self.assertEqual(self.jobs.started, [])
        self.jobs.runs.clear()        # (the early run it started at 15:30 has finished)
        now = datetime(2026, 9, 29, 16, 31, tzinfo=TZ)
        s.tick(self.jobs, self.root, now, self.trading, memo, probe=lambda day: True)
        self.assertEqual(self.jobs.started, ["2026-09-28"])       # nothing behind the 09-24 seal
        s.tick(self.jobs, self.root, now, self.trading, memo, probe=lambda day: True)
        self.assertEqual(len(self.jobs.started), 1)               # one running: wait
        self.jobs.runs[-1]["state"] = "succeeded"
        s.tick(self.jobs, self.root, now, self.trading, memo, probe=lambda day: True)
        self.assertEqual(self.jobs.started, ["2026-09-28", "2026-09-29"])
        self.jobs.runs[-1]["state"] = "failed"                    # failed today: not retried
        memo.clear()
        s.tick(self.jobs, self.root, now, self.trading, memo, probe=lambda day: True)
        self.assertEqual(len(self.jobs.started), 2)
        self.assertEqual(s.pending_days(self.jobs, self.root, now, self.trading), [])

    def test_early_update_once_between_1545_and_1630(self):
        memo = {}
        at = lambda h, m: datetime(2026, 9, 29, h, m, tzinfo=TZ)
        s.tick(self.jobs, self.root, at(15, 44), self.trading, memo)
        self.assertEqual(self.jobs.early_started, [])             # TDX serves incomplete 1-minute bars until ~15:40
        s.tick(self.jobs, self.root, at(15, 45), self.trading, memo)
        self.assertEqual(self.jobs.early_started, ["2026-09-29"])
        self.jobs.runs[-1]["state"] = "succeeded"
        memo.clear()
        s.tick(self.jobs, self.root, at(16, 0), self.trading, memo)
        self.assertEqual(self.jobs.early_started, ["2026-09-29"])  # once a day, even after a scheduler restart
        self.assertEqual(self.jobs.started, [])

    def test_early_update_skips_unconfirmed_sealed_blocked_and_failed(self):
        at = datetime(2026, 9, 29, 15, 30, tzinfo=TZ)
        s.tick(self.jobs, self.root, at, s.TradingDays(fetch=lambda: {"2026-09-28"}), {})   # no TDX bar for today
        self.assertEqual(self.jobs.early_started, [])
        (self.root / "catalog/seals/2026-09-29.json").write_text("{}")
        s.tick(self.jobs, self.root, at, self.trading, {})
        self.assertEqual(self.jobs.early_started, [])
        (self.root / "catalog/seals/2026-09-29.json").unlink()
        self.jobs.blocked = "x"
        memo = {}
        s.tick(self.jobs, self.root, at, self.trading, memo)
        s.tick(self.jobs, self.root, at, self.trading, memo)
        self.assertEqual(self.jobs.early_started, [])
        self.jobs.blocked = None
        self.jobs.runs.append({"job_id": "daily_close_early", "params": {"date": "2026-09-29"}, "state": "failed",
                               "created_at": "2026-09-29T15:11:00"})
        s.tick(self.jobs, self.root, at, self.trading, {})
        self.assertEqual(self.jobs.early_started, [])             # a failed run is not retried by itself

    def test_close_update_waits_for_baostock_today_but_not_for_older_days(self):
        probes, memo = [], {}
        now = datetime(2026, 9, 29, 16, 31, tzinfo=TZ)

        def probe(day):
            probes.append(day)
            return False
        s.tick(self.jobs, self.root, now, self.trading, memo, probe=probe)
        self.assertEqual(self.jobs.started, ["2026-09-28"])       # an older day runs without asking Baostock
        self.assertEqual(probes, [])
        self.jobs.runs[-1]["state"] = "succeeded"
        s.tick(self.jobs, self.root, now, self.trading, memo, probe=probe)
        self.assertEqual(probes, ["2026-09-29"])
        self.assertEqual(self.jobs.started, ["2026-09-28"])       # today waits: Baostock has not published it
        s.tick(self.jobs, self.root, now, self.trading, memo, probe=probe)
        self.assertEqual(probes, ["2026-09-29"])                  # not asked again within 10 minutes
        memo["baostock_next"] = 0
        s.tick(self.jobs, self.root, now, self.trading, memo, probe=lambda day: True)
        self.assertEqual(self.jobs.started, ["2026-09-28", "2026-09-29"])

    def test_same_day_public_starts_once_from_1830_next_to_the_early_run(self):
        memo = {}
        at = lambda h, m: datetime(2026, 9, 29, h, m, tzinfo=TZ)
        self.jobs.runs.append({"job_id": "daily_close_early", "params": {"date": "2026-09-29"}, "state": "running",
                               "created_at": "2026-09-29T15:45:00"})
        s.tick(self.jobs, self.root, at(18, 29), self.trading, memo, probe=lambda d: False)
        self.assertEqual(self.jobs.same_day_started, [])
        s.tick(self.jobs, self.root, at(18, 30), self.trading, memo, probe=lambda d: False)
        self.assertEqual(self.jobs.same_day_started, ["2026-09-29"])    # the slow early run does not hold it back
        s.tick(self.jobs, self.root, at(18, 31), self.trading, memo, probe=lambda d: True)
        self.assertEqual(self.jobs.same_day_started, ["2026-09-29"])
        self.assertEqual(self.jobs.started, [])                         # the update waits for both
        self.jobs.runs[-1]["state"] = "succeeded"
        s.tick(self.jobs, self.root, at(18, 40), self.trading, {"same_day": "2026-09-29"}, probe=lambda d: True)
        self.assertEqual(self.jobs.same_day_started, ["2026-09-29"])    # once a day, even after a scheduler restart

    def test_close_update_waits_for_same_day_public(self):
        self.jobs.runs.append({"job_id": "same_day_public", "params": {"date": "2026-09-29"}, "state": "running",
                               "created_at": "2026-09-29T18:30:00"})
        s.tick(self.jobs, self.root, datetime(2026, 9, 29, 18, 40, tzinfo=TZ), self.trading, {}, probe=lambda d: True)
        self.assertEqual(self.jobs.started, [])
        self.jobs.runs[-1]["state"] = "succeeded"
        s.tick(self.jobs, self.root, datetime(2026, 9, 29, 18, 41, tzinfo=TZ), self.trading, {}, probe=lambda d: True)
        self.assertEqual(self.jobs.started, ["2026-09-28"])

    def test_same_day_public_leaves_a_failed_run_alone_and_skips_blocked_sealed_and_non_trading_days(self):
        at = datetime(2026, 9, 29, 19, 0, tzinfo=TZ)
        self.jobs.runs.append({"job_id": "same_day_public", "params": {"date": "2026-09-29"}, "state": "failed",
                               "created_at": "2026-09-29T18:30:00"})
        s.tick(self.jobs, self.root, at, self.trading, {}, probe=lambda d: False)
        self.assertEqual(self.jobs.same_day_started, [])               # not retried by itself
        self.jobs.runs.clear()
        s.tick(self.jobs, self.root, at, s.TradingDays(fetch=lambda: {"2026-09-28"}), {}, probe=lambda d: False)
        self.assertEqual(self.jobs.same_day_started, [])               # no TDX bar for today: holiday
        self.jobs.same_day_blocked = "今天只能当天观察的数据都已采"
        memo = {}
        s.tick(self.jobs, self.root, at, self.trading, memo, probe=lambda d: False)
        s.tick(self.jobs, self.root, at, self.trading, memo, probe=lambda d: False)
        self.assertEqual(self.jobs.same_day_started, [])
        self.assertEqual(memo["same_day"], "2026-09-29")               # blocked is logged once, not every minute
        self.jobs.same_day_blocked = None
        (self.root / "catalog/seals/2026-09-29.json").write_text("{}")
        s.tick(self.jobs, self.root, at, self.trading, {}, probe=lambda d: False)
        self.assertEqual(self.jobs.same_day_started, [])
        (self.root / "catalog/seals/2026-09-29.json").unlink()
        s.tick(self.jobs, self.root, datetime(2026, 10, 3, 19, 0, tzinfo=TZ), self.trading, {}, probe=lambda d: False)  # Saturday
        self.assertEqual(self.jobs.same_day_started, [])

    def test_same_day_public_defers_to_a_close_update_running_on_the_day(self):
        self.jobs.runs.append({"job_id": "daily_close_update", "params": {"date": "2026-09-29"}, "state": "running",
                               "created_at": "2026-09-29T16:35:00"})
        memo = {}
        s.tick(self.jobs, self.root, datetime(2026, 9, 29, 18, 35, tzinfo=TZ), self.trading, memo, probe=lambda d: True)
        self.assertEqual(self.jobs.same_day_started, [])               # it collects them itself
        self.assertNotIn("same_day", memo)                             # and we look again once it has ended
        self.jobs.runs[-1]["state"] = "failed"
        s.tick(self.jobs, self.root, datetime(2026, 9, 29, 19, 5, tzinfo=TZ), self.trading, memo, probe=lambda d: False)
        self.assertEqual(self.jobs.same_day_started, ["2026-09-29"])   # it failed first: the small job picks up what is missing

    def test_close_update_does_not_start_while_early_runs(self):
        self.jobs.runs.append({"job_id": "daily_close_early", "params": {"date": "2026-09-29"}, "state": "running",
                               "created_at": "2026-09-29T15:11:00"})
        s.tick(self.jobs, self.root, datetime(2026, 9, 29, 16, 40, tzinfo=TZ), self.trading, {}, probe=lambda d: True)
        self.assertEqual(self.jobs.started, [])


if __name__ == "__main__":
    unittest.main()
