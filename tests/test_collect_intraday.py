"""Intraday recorder, board-constituents snapshot and background job runner (scripts/collect)."""
import json
import os
import signal
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from collect import job_runner, sector_constituents  # noqa: E402
from collect import sector_intraday_recorder as recorder  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
DAY = "2026-09-28"


def at(clock):
    return datetime.fromisoformat(f"{DAY}T{clock}+08:00")


class SlotWindowTests(unittest.TestCase):
    def test_a_slot_is_only_taken_inside_its_window(self):
        morning = {"09:25", "10:00"}
        cases = [("09:25:10", set(), set(), [], []),
                 ("09:25:40", set(), set(), ["09:25"], []),
                 ("09:31:00", set(), set(), [], ["09:25"]),  # continuous trading has started
                 ("10:03:00", set(), {"09:25"}, ["10:00"], []),
                 ("10:06:00", {"09:25"}, set(), [], ["10:00"]),
                 ("12:30:00", morning, set(), ["11:30"], []),  # prices stand still over lunch
                 ("14:59:00", morning | {"11:30", "14:00"}, set(), ["14:57"], []),
                 ("15:10:00", morning | {"11:30", "14:00", "14:57"}, set(), ["15:00"], []),
                 ("15:21:00", morning | {"11:30", "14:00", "14:57"}, set(), [], ["15:00"])]
        for clock, done, missed, capture, lapsed in cases:
            self.assertEqual(recorder.slot_actions(at(clock), DAY, done, missed), (capture, lapsed), clock)

    def test_delay_and_missed_slots_are_receipted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{"symbol": "sh.600000", "last": 9.9, "status": "trading"}]
            with mock.patch("quantlab.data.stock_intraday.capture", return_value=(rows, {"requested": 1})), \
                    mock.patch("quantlab.data.stock_intraday.universe", return_value=["sh.600000"]):
                entry = recorder.stock_snapshot(root, None, "10:00", due=datetime.now(TZ).timestamp() - 42)
            self.assertEqual(entry["status"], "ok")
            self.assertGreaterEqual(entry["delay_seconds"], 42)
            missed = recorder.mark_missed(root, "09:25")
            self.assertIn("09:30", missed["reason"])
            receipt = root / recorder.STOCK_SNAPSHOTS / "_receipts" / f"{datetime.now(TZ).date()}.json"
            self.assertEqual([s["status"] for s in json.loads(receipt.read_text())["samples"]], ["ok", "missed"])


class RecorderLockTests(unittest.TestCase):
    def test_only_one_recorder_at_a_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = recorder.hold_single_instance(Path(tmp))
            self.assertIsNotNone(first)
            self.assertIsNone(recorder.hold_single_instance(Path(tmp)))
            self.assertEqual(recorder.main(["--data-root", tmp, "--once"]), 1)  # leaves before any request
            first.close()
            again = recorder.hold_single_instance(Path(tmp))
            self.assertIsNotNone(again)
            again.close()


class ConstituentsRefreshTests(unittest.TestCase):
    def test_slices_until_complete_and_gives_up_after_five_failed_passes(self):
        asked = []
        results = iter([{"timed_out": True}, {"complete": True}])
        refresh = recorder.ConstituentsRefresh(Path("/unused"),
                                               run=lambda root, max_seconds: asked.append(max_seconds) or next(results))
        refresh.step(3)  # too little time left in the minute: nothing is asked
        for _ in range(3):
            refresh.step(40)
        self.assertEqual(asked, [40, 40])
        self.assertTrue(refresh.done)
        failing = recorder.ConstituentsRefresh(Path("/unused"),
                                               run=lambda root, max_seconds: {"timed_out": False, "failed": 3})
        for _ in range(7):
            failing.step(30)
        self.assertEqual((failing.done, failing.passes), (True, 5))
        broken = recorder.ConstituentsRefresh(Path("/unused"), run=mock.Mock(side_effect=RuntimeError("down")))
        for _ in range(7):
            broken.step(30)
        self.assertEqual(broken.run.call_count, 5)


class ConstituentsResumeTests(unittest.TestCase):
    class Client:
        def call(self, service, tool, args):
            if tool.endswith("ths_index_list"):
                return {"data": {"item": [{"thscode": f"88{i:04d}.TI", "name": f"B{i}"} for i in range(600)]}}
            return {"data": {"item": [{"thscode": "600000.SH", "name": "浦发银行"}]}}

    def test_a_line_cut_short_is_fetched_again(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sector_constituents, "PACE", 0):
            root = Path(tmp)
            partial = root / "lake/bronze/provider=fuyao/sector_board_constituents/_partial" / f"{DAY}.jsonl"
            partial.parent.mkdir(parents=True)
            row = json.dumps({"board_code": "880000.TI", "board_name": "B0", "board_type": "concept",
                              "observed_at": "x", "status": "ok",
                              "members": [{"symbol": "sh.600000", "name": "浦发银行"}]}, ensure_ascii=False)
            partial.write_text(row + "\n" + row[:40])  # the process was killed in the middle of a line
            result = sector_constituents.run(root, max_seconds=60, client=self.Client(), today=DAY)
            self.assertTrue(result["complete"])
            self.assertEqual((result["rows"], result["skipped_partial_lines"]), (600, 1))
            lines = partial.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[1], row[:40])  # left as found; new rows start on their own line
            self.assertTrue(all(json.loads(line) for line in lines[2:]))


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        handler = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, handler)  # Runner installs its own handler

    def runner(self, steps, state="queued"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run_dir = Path(tmp.name) / "catalog/jobs/runs/r1"
        run_dir.mkdir(parents=True)
        (run_dir / "plan.json").write_text(json.dumps({"job_id": "daily_close_update", "plan_id": "p" * 32,
                                                       "data_root": tmp.name, "steps": steps}))
        (run_dir / "state.json").write_text(json.dumps({"run_id": "r1", "job_id": "daily_close_update", "state": state,
                                                        "pid": None, "result": {"datasets": [], "seal": None}}))
        runner = job_runner.Runner(run_dir)
        self.addCleanup(runner.log_file.close)
        self.addCleanup(lambda: getattr(runner, "lock_handle", None) and runner.lock_handle.close())
        return runner, run_dir

    @staticmethod
    def step(kind, name):
        return {"name": name, "action": "fetch", "kind": kind, "dates": [DAY], "weight": 1}

    @staticmethod
    def state(run_dir):
        return json.loads((run_dir / "state.json").read_text())

    def test_an_incomplete_qfq_rebuild_fails_the_run_after_the_other_steps(self):
        runner, run_dir = self.runner([self.step("qfq", "前复权重建"), self.step("status_index", "刷新状态")])
        replies = {"plan": '{"plan_sha256": "abc", "codes": 3}', "apply": '{"complete": false, "total_done": 1, "codes": 3}'}
        runner.sh = lambda args, **_: replies.get(args[1], "")
        later = []
        runner.step_status_index = lambda step, share: later.append(step["kind"])
        self.assertEqual(runner.run(), 1)
        state = self.state(run_dir)
        self.assertEqual(state["state"], "failed")
        self.assertIn("前复权日线没有完成", state["error"])
        self.assertEqual(later, ["status_index"])  # the seal and status steps still ran
        qfq = next(d for d in state["result"]["datasets"] if d["dataset_id"] == "qfq_published_f24")
        self.assertTrue(qfq["failures"])

    def test_a_constituents_failure_is_recorded_and_the_update_goes_on(self):
        runner, run_dir = self.runner([self.step("constituents", "板块成分快照")])
        with mock.patch("collect.sector_constituents.run", side_effect=RuntimeError("board catalog looks incomplete")):
            self.assertEqual(runner.run(), 0)
        state = self.state(run_dir)
        self.assertEqual(state["state"], "succeeded")
        entry = next(d for d in state["result"]["datasets"] if d["dataset_id"] == "sector_board_constituents")
        self.assertIn("成分快照失败", entry["failures"][0])

    def test_the_runner_holds_its_lock_and_never_starts_a_cancelled_run(self):
        from quantlab.data.data_services import runner_alive
        runner, run_dir = self.runner([self.step("probe", "探针")])
        seen = []
        runner.step_probe = lambda step, share: seen.append(runner_alive(run_dir, self.state(run_dir)))
        self.assertEqual(runner.run(), 0)
        self.assertEqual(seen, [True])
        runner.lock_handle.close()  # the process has exited: a running state with a free lock reads as gone
        self.assertFalse(runner_alive(run_dir, {"state": "running", "pid": os.getpid()}))
        cancelled, cancelled_dir = self.runner([self.step("probe", "探针")], state="cancelled")
        cancelled.step_probe = mock.Mock()
        self.assertEqual(cancelled.run(), 1)
        cancelled.step_probe.assert_not_called()
        self.assertEqual(self.state(cancelled_dir)["state"], "cancelled")


if __name__ == "__main__":
    unittest.main()
