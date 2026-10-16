from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect import status_fast  # noqa: E402

PREV, DAY = "2026-10-15", "2026-10-16"
COLS = ["date", "code", "tradestatus", "isST", "fetch_ts"]


def status_rows(code, *pairs):
    return pd.DataFrame([[d, code, t, s, "2026-10-15T20:00:00+08:00"] for d, t, s in pairs], columns=COLS)


class FakeSession:
    def __init__(self, answers, calls):
        self.answers, self.calls = answers, calls

    def __call__(self, code):
        self.calls.append(code)
        answer = self.answers[code]
        if isinstance(answer, Exception):
            raise answer
        return pd.DataFrame([[d, code, t, s, "2026-10-17T05:00:00+08:00"] for d, t, s in answer], columns=COLS)

    def close(self):
        pass


class StatusFastTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "status"
        self.raw = self.tmp / "raw"
        self.root.mkdir()
        self.raw.mkdir()
        patch = mock.patch.object(status_fast.coverage, "DATA_ROOT", self.tmp)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(status_fast, "MIN_BARS", 2)
        patch.start()
        self.addCleanup(patch.stop)
        # sh.600001 trades, not ST; sh.600002 suspended today; sh.600003 ST yesterday;
        # sh.600004 has no bar today; sh.600005 lags a day behind
        self.add("sh.600001", [(PREV, "1", "0")], volume=1000)
        self.add("sh.600002", [(PREV, "1", "0")], volume=0)
        self.add("sh.600003", [(PREV, "1", "1")], volume=500)
        self.add("sh.600004", [(PREV, "1", "0")], volume=None)
        self.add("sh.600005", [("2026-10-14", "1", "0")], volume=300)

    def add(self, code, rows, volume):
        stem = code.replace(".", "_")
        status_rows(code, *rows).to_parquet(self.root / f"{stem}.parquet", index=False)
        days = [date(2026, 10, 15)] + ([date(2026, 10, 16)] if volume is not None else [])
        table = pa.table({"date": pa.array(days, pa.date32()), "code": [code] * len(days),
                          "volume": pa.array([10] * (len(days) - 1) + [volume] if volume is not None else [10],
                                             pa.int64())})
        pq.write_table(table, self.raw / f"{stem}.parquet")

    def read(self, code):
        return pd.read_parquet(self.root / (code.replace(".", "_") + ".parquet"))

    def plan(self, **kw):
        return status_fast.build_plan(self.root, date(2026, 10, 16), raw_dir=self.raw, names=kw.get("names"),
                                      names_info=kw.get("names_info"))

    def modes(self, plan):
        return {a["code"]: (a["mode"], a["reasons"]) for a in plan["actions"]}

    def test_plan_derives_what_the_bar_decides_and_asks_about_the_rest(self):
        plan = self.plan()
        self.assertEqual(self.modes(plan), {
            "sh.600001": ("derive", []), "sh.600002": ("derive", []),
            "sh.600003": ("query", ["st_yesterday"]), "sh.600004": ("query", ["no_bar"])})
        self.assertEqual(plan["lagging"], ["sh.600005"])
        self.assertEqual((plan["derive"], plan["query"]), (2, 2))
        derived = {a["code"]: (a["tradestatus"], a["isST"]) for a in plan["actions"] if a["mode"] == "derive"}
        self.assertEqual(derived, {"sh.600001": ("1", "0"), "sh.600002": ("0", "0")})

    def test_a_name_that_disagrees_with_the_carried_flag_is_asked(self):
        plan = self.plan(names={"sh.600001": True, "sh.600002": False, "sh.600003": True},
                         names_info={"path": "x", "sha256": "y", "count": 3})
        self.assertEqual(self.modes(plan)["sh.600001"], ("query", ["name_differs"]))
        self.assertEqual(self.modes(plan)["sh.600002"], ("derive", []))
        self.assertEqual(self.modes(plan)["sh.600003"], ("query", ["st_yesterday"]))  # name agrees, still asked

    def test_name_marks(self):
        self.assertTrue(status_fast.name_flag("*ST联光"))
        self.assertTrue(status_fast.name_flag("元道退"))
        self.assertFalse(status_fast.name_flag("浦发银行"))

    def test_too_few_bars_means_the_day_is_not_in_yet(self):
        with mock.patch.object(status_fast, "MIN_BARS", 10), self.assertRaisesRegex(ValueError, "not complete"):
            self.plan()

    def test_apply_writes_derived_rows_and_asks_baostock_only_for_the_rest(self):
        plan = self.plan()
        calls = []
        answers = {"sh.600003": [(DAY, "1", "0")], "sh.600004": [(DAY, "0", "0")]}
        result = status_fast.apply(plan, throttle=0, session_factory=lambda *a: FakeSession(answers, calls))
        self.assertEqual(result["run_status"], "finished")
        self.assertEqual(sorted(calls), ["sh.600003", "sh.600004"])
        last = {c: tuple(self.read(c).iloc[-1][["date", "tradestatus", "isST"]]) for c in
                ("sh.600001", "sh.600002", "sh.600003", "sh.600004")}
        self.assertEqual(last, {"sh.600001": (DAY, "1", "0"), "sh.600002": (DAY, "0", "0"),
                                "sh.600003": (DAY, "1", "0"), "sh.600004": (DAY, "0", "0")})
        self.assertEqual(len(self.read("sh.600005")), 1)  # lagging symbol untouched
        backups = sorted(p.name for p in (self.tmp / "backups").glob("status-fast-*/*"))
        self.assertEqual(backups, ["sh_600003.parquet", "sh_600004.parquet"])  # only asked rows are backed up
        prov = json.loads((self.root / "_receipts" / f"status-fast-provenance-{DAY}.json").read_text())
        self.assertEqual((prov["derived"], prov["asked"], prov["failed"], prov["reconciled"]),
                         (["sh.600001", "sh.600002"], ["sh.600003", "sh.600004"], [], False))

    def test_a_failed_question_leaves_that_file_alone_and_fails_the_run(self):
        plan = self.plan()
        answers = {"sh.600003": RuntimeError("timeout"), "sh.600004": [(DAY, "1", "0")]}
        result = status_fast.apply(plan, throttle=0, session_factory=lambda *a: FakeSession(answers, []))
        self.assertEqual(result["run_status"], "finished_with_errors")
        self.assertEqual(len(self.read("sh.600003")), 1)
        prov = json.loads((self.root / "_receipts" / f"status-fast-provenance-{DAY}.json").read_text())
        self.assertEqual(prov["failed"], ["sh.600003"])

    def test_provider_without_the_day_is_never_replaced_by_a_guess(self):
        plan = self.plan()
        answers = {"sh.600003": [], "sh.600004": [(DAY, "1", "0")]}
        result = status_fast.apply(plan, throttle=0, session_factory=lambda *a: FakeSession(answers, []))
        self.assertEqual(result["run_status"], "finished_with_errors")
        self.assertEqual(len(self.read("sh.600003")), 1)

    def test_apply_refuses_a_second_run_unless_resuming_and_a_changed_file(self):
        plan = self.plan()
        answers = {"sh.600003": [(DAY, "1", "0")], "sh.600004": [(DAY, "1", "0")]}
        status_fast.apply(plan, throttle=0, session_factory=lambda *a: FakeSession(answers, []))
        with self.assertRaises(FileExistsError):
            status_fast.apply(plan, throttle=0, session_factory=lambda *a: FakeSession(answers, []))
        other = json.loads(json.dumps(plan))
        other["actions"][0]["parquet_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "identity"):
            status_fast.apply(other, throttle=0, session_factory=lambda *a: FakeSession(answers, []))

    def test_resume_accepts_files_written_before_a_crash(self):
        plan = self.plan()
        answers = {"sh.600003": [(DAY, "1", "0")], "sh.600004": [(DAY, "1", "0")]}
        status_fast.apply(plan, throttle=0, session_factory=lambda *a: FakeSession(answers, []))
        receipt = self.root / "_receipts" / f"status-fast-{plan['plan_sha256'][:16]}.json"
        body = json.loads(receipt.read_text())
        body.update(run_status="running", results=[r for r in body["results"] if r["code"] != "sh.600001"])
        receipt.write_text(json.dumps(body))
        result = status_fast.apply(plan, throttle=0, resume_run=True,
                                   session_factory=lambda *a: FakeSession(answers, []))
        self.assertEqual(result["run_status"], "finished")
        self.assertEqual(len(self.read("sh.600001")), 2)  # not appended twice

    def run_day(self, truth_for_derived):
        plan = self.plan()
        answers = {"sh.600003": [(DAY, "1", "1")], "sh.600004": [(DAY, "1", "0")]}
        status_fast.apply(plan, throttle=0, session_factory=lambda *a: FakeSession(answers, []))
        return truth_for_derived

    def test_reconcile_fixes_a_derived_row_that_baostock_contradicts(self):
        self.run_day(None)
        plan = status_fast.build_reconcile_plan(self.root)
        self.assertEqual([a["code"] for a in plan["actions"]], ["sh.600001", "sh.600002"])
        # Baostock says sh.600001 turned ST that day; sh.600002 is as derived
        truth = {"sh.600001": [(DAY, "1", "1")], "sh.600002": [(DAY, "0", "0")]}
        result = status_fast.reconcile_apply(plan, throttle=0, session_factory=lambda *a: FakeSession(truth, []))
        self.assertEqual(result["run_status"], "finished")
        self.assertEqual([c["code"] for c in result["changed"]], ["sh.600001"])
        self.assertEqual(tuple(self.read("sh.600001").iloc[-1][["tradestatus", "isST"]]), ("1", "1"))
        self.assertEqual(tuple(self.read("sh.600001").iloc[0][["tradestatus", "isST"]]), ("1", "0"))  # other rows kept
        self.assertTrue(list((self.tmp / "backups").glob("status-reconcile-*/sh_600001.parquet")))
        prov = json.loads((self.root / "_receipts" / f"status-fast-provenance-{DAY}.json").read_text())
        self.assertTrue(prov["reconciled"])
        with self.assertRaisesRegex(ValueError, "nothing to reconcile"):
            status_fast.build_reconcile_plan(self.root)

    def test_reconcile_failure_keeps_the_days_open(self):
        self.run_day(None)
        plan = status_fast.build_reconcile_plan(self.root)
        truth = {"sh.600001": RuntimeError("timeout"), "sh.600002": [(DAY, "0", "0")]}
        result = status_fast.reconcile_apply(plan, throttle=0, session_factory=lambda *a: FakeSession(truth, []))
        self.assertEqual(result["run_status"], "finished_with_errors")
        self.assertFalse(json.loads((self.root / "_receipts" / f"status-fast-provenance-{DAY}.json").read_text())["reconciled"])


if __name__ == "__main__":
    unittest.main()
