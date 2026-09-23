import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from collect import public_sources as ps  # noqa: E402


def ok_fetch(day):
    return pd.DataFrame({"code": ["600000"], "value": [1.5]}), {"rows_reported": 1}


def empty_fetch(day):
    return pd.DataFrame(), {"note": "nothing"}


def failing_fetch(day):
    raise RuntimeError("HTTP 502")


class PublicSourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = dict(ps.DATASETS)
        ps.DATASETS.clear()
        ps.DATASETS.update({
            "t_ok": ("test", "ok", "date_calendar", ok_fetch),
            "t_empty": ("test", "empty", "date_calendar", empty_fetch),
            "t_fail": ("test", "fail", "date_calendar", failing_fetch),
            "t_snap": ("test", "snap", "snapshot", ok_fetch),
        })

    def tearDown(self):
        ps.DATASETS.clear()
        ps.DATASETS.update(self.saved)
        self.tmp.cleanup()

    def plan(self, name, start=date(2026, 9, 1), end=date(2026, 9, 3)):
        return ps.build_plan(self.root, name, start, end, "unused", date(2026, 9, 23))

    def test_plan_skips_present_and_empty_partitions(self):
        target = ps.dataset_dir(self.root, "t_ok")
        (target / "_empty").mkdir(parents=True)
        (target / "2026-09-01.parquet").write_bytes(b"x")
        (target / "_empty" / "2026-09-02.json").write_text("{}")
        plan = self.plan("t_ok")
        self.assertEqual(plan["partitions"], ["2026-09-03"])
        self.assertEqual(plan["already_present"], ["2026-09-01", "2026-09-02"])

    def test_snapshot_plans_only_today(self):
        self.assertEqual(self.plan("t_snap", None, None)["partitions"], ["2026-09-23"])

    def test_approval_must_match_and_plan_must_be_untampered(self):
        plan = self.plan("t_ok")
        with self.assertRaises(PermissionError):
            ps.apply(plan, "0" * 64, max_seconds=10, throttle=0)
        tampered = dict(plan, partitions=["2026-09-09"])
        with self.assertRaises(PermissionError):
            ps.apply(tampered, plan["plan_sha256"], max_seconds=10, throttle=0)

    def test_apply_writes_data_empty_marker_and_failure(self):
        plan = self.plan("t_ok", end=date(2026, 9, 1))
        result = ps.apply(plan, plan["plan_sha256"], max_seconds=10, throttle=0)
        self.assertTrue(result["complete"])
        frame = pd.read_parquet(ps.dataset_dir(self.root, "t_ok") / "2026-09-01.parquet")
        self.assertEqual(list(frame.columns), ["code", "value", "_observed_at"])

        plan = self.plan("t_empty", end=date(2026, 9, 1))
        ps.apply(plan, plan["plan_sha256"], max_seconds=10, throttle=0)
        target = ps.dataset_dir(self.root, "t_empty")
        self.assertTrue((target / "_empty" / "2026-09-01.json").is_file())
        self.assertFalse((target / "2026-09-01.parquet").exists())

        plan = self.plan("t_fail", end=date(2026, 9, 1))
        result = ps.apply(plan, plan["plan_sha256"], max_seconds=10, throttle=0)
        target = ps.dataset_dir(self.root, "t_fail")
        self.assertFalse(result["complete"])
        self.assertEqual(result.get("failed"), 1)
        self.assertFalse((target / "_empty").exists())
        self.assertFalse(any(target.glob("*.parquet")))
        receipt = json.loads(next((target / "_receipts").glob("*.json")).read_text())
        self.assertIn("HTTP 502", receipt["results"]["2026-09-01"]["error"])


if __name__ == "__main__":
    unittest.main()
