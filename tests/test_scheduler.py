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

    def _runs(self):
        return self.runs

    def _running(self, ids):
        return next((r for r in self.runs if r["job_id"] in ids and r["state"] in ("queued", "running")), None)

    def autostart(self, job_id):
        self.autostarts += 1
        return {"started": True, "job_id": job_id, "reason": None, "run_id": "r"}

    def plan(self, job_id, params):
        return {"plan_id": "p" + params["date"], "blocked_reason": None}

    def run(self, plan_id, trigger):
        day = plan_id[1:]
        self.started.append(day)
        self.runs.append({"job_id": "daily_close_update", "params": {"date": day}, "state": "running",
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
        now = datetime(2026, 9, 29, 16, 31, tzinfo=TZ)
        s.tick(self.jobs, self.root, now, self.trading, memo)
        self.assertEqual(self.jobs.started, ["2026-09-28"])       # nothing behind the 09-24 seal
        s.tick(self.jobs, self.root, now, self.trading, memo)
        self.assertEqual(len(self.jobs.started), 1)               # one running: wait
        self.jobs.runs[-1]["state"] = "succeeded"
        s.tick(self.jobs, self.root, now, self.trading, memo)
        self.assertEqual(self.jobs.started, ["2026-09-28", "2026-09-29"])
        self.jobs.runs[-1]["state"] = "failed"                    # failed today: not retried
        memo.clear()
        s.tick(self.jobs, self.root, now, self.trading, memo)
        self.assertEqual(len(self.jobs.started), 2)
        self.assertEqual(s.pending_days(self.jobs, self.root, now, self.trading), [])


if __name__ == "__main__":
    unittest.main()
