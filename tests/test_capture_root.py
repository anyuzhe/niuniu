import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from quantlab.data import capture_root as cr  # noqa: E402
from collect import migrate_captures as mig  # noqa: E402


class CaptureRootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.workspace = base / "artifacts"
        self.data_root = base / "data"
        (self.data_root / "lake").mkdir(parents=True)
        (self.data_root / "catalog").mkdir()
        src = self.workspace / "_market_data"
        capture = src / "retro_daily" / "0b774158-3a3b-561f-9c18-23fd895db4aa"
        (capture / "packs").mkdir(parents=True)
        (capture / "packs" / "index.json").write_text(json.dumps({"checksum": "a" * 64, "packs": {}}))
        (capture / "plan.json").write_text("{}")
        (src / "daily_market" / "2026-09-16").mkdir(parents=True)
        (src / "daily_market" / "2026-09-16" / "accepted.json").write_text('{"x":1}')
        (src / "daily_market" / "._accepted.json").write_bytes(b"appledouble")
        (self.data_root / "catalog" / "retro_daily_tail.json").write_text(json.dumps({
            "format": "retro-daily-tail-pointer-v1", "capture_path": str(capture),
            "coverage_end": "2026-09-15", "digest": "a" * 64, "scope": "test"}))

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self):
        return mig.build_plan(self.workspace, self.data_root)

    def test_default_is_legacy_workspace_tree(self):
        self.assertEqual(cr.capture_root(self.workspace), self.workspace / "_market_data")

    def test_full_migration_redirect_and_pointer(self):
        plan = self.plan()
        self.assertEqual(len(plan["files"]), 3)  # AppleDouble sidecar excluded
        with self.assertRaises(PermissionError):
            mig.apply(plan, "0" * 64)
        receipt = mig.apply(plan, plan["plan_sha256"])
        self.assertEqual((receipt["copied"], receipt["already_present"]), (3, 0))
        again = mig.apply(plan, plan["plan_sha256"])  # resumable, no rewrite
        self.assertEqual((again["copied"], again["already_present"]), (0, 3))
        target = Path(plan["target"])
        self.assertEqual(target, self.data_root / "lake" / "_market_data")
        # sources untouched
        self.assertTrue((self.workspace / "_market_data" / "daily_market" / "2026-09-16" / "accepted.json").is_file())
        mig.write_redirect(plan, plan["plan_sha256"])
        self.assertEqual(cr.capture_root(self.workspace), target)
        result = mig.rewrite_retro_pointer(plan, plan["plan_sha256"], self.data_root)
        pointer = json.loads((self.data_root / "catalog" / "retro_daily_tail.json").read_text())
        self.assertTrue(pointer["capture_path"].startswith(str(target)))
        self.assertEqual(pointer["digest"], "a" * 64)
        self.assertTrue(Path(result["backup"]).is_file())
        # the migrated capture's parents[2] behaves as an un-redirected workspace
        self.assertEqual(cr.capture_root(Path(pointer["capture_path"]).parents[2]), target)

    def test_plan_refuses_changed_source_and_unplanned_target_file(self):
        plan = self.plan()
        (self.workspace / "_market_data" / "daily_market" / "2026-09-16" / "accepted.json").write_text('{"x":2}')
        with self.assertRaises(ValueError):
            mig.apply(plan, plan["plan_sha256"])
        plan = self.plan()
        target = Path(plan["target"])
        target.mkdir(parents=True)
        (target / "stray.txt").write_text("x")
        with self.assertRaises(ValueError):
            mig.apply(plan, plan["plan_sha256"])

    def test_tampered_plan_is_refused(self):
        plan = self.plan()
        plan["target"] = str(self.data_root / "elsewhere" / "_market_data")
        with self.assertRaises(PermissionError):
            mig.apply(plan, plan["plan_sha256"])

    def test_redirect_requires_complete_target(self):
        plan = self.plan()
        with self.assertRaises(ValueError):
            mig.write_redirect(plan, plan["plan_sha256"])
        self.assertFalse((self.workspace / cr.REDIRECT_NAME).exists())

    def test_invalid_redirects_fail_closed(self):
        plan = self.plan()
        mig.apply(plan, plan["plan_sha256"])
        redirect = self.workspace / cr.REDIRECT_NAME
        good = {"format": cr.REDIRECT_FORMAT, "capture_root": plan["target"],
                "capture_root_id": plan["capture_root_id"]}
        bad_cases = [
            "{not json",
            json.dumps(dict(good, extra=1)),
            json.dumps(dict(good, capture_root="relative/_market_data")),
            json.dumps(dict(good, capture_root=str(self.data_root / "lake"))),
            json.dumps(dict(good, capture_root_id="b" * 64)),
            json.dumps(dict(good, capture_root=str(self.data_root / "missing" / "_market_data"))),
        ]
        for text in bad_cases:
            redirect.write_text(text)
            with self.assertRaises(cr.CaptureRootError, msg=text[:40]):
                cr.capture_root(self.workspace)

    def test_stores_follow_redirect(self):
        from quantlab.data.daily_market_archive import DailyMarketArchive
        from quantlab.data.retro_daily import RetroDailyStore
        from quantlab.data.baostock_series import SeriesService
        plan = self.plan()
        mig.apply(plan, plan["plan_sha256"])
        mig.write_redirect(plan, plan["plan_sha256"])
        target = Path(plan["target"])
        self.assertEqual(RetroDailyStore(self.workspace).root, target / "retro_daily")
        self.assertEqual(DailyMarketArchive(self.workspace).root, target / "daily_market")
        self.assertEqual(SeriesService(self.workspace).root, target / "baostock_series")
        from quantlab.data.forward_daily import ForwardReferenceArchive
        from quantlab.data.public_evidence import PublicEvidenceArchive
        self.assertEqual(ForwardReferenceArchive(self.workspace).root, target / "forward_reference")
        self.assertEqual(PublicEvidenceArchive(self.workspace, sources=[]).root, target / "public_evidence")
        from quantlab.data.baostock_ingest import import_root
        self.assertEqual(import_root(self.workspace), target / "baostock")

    def test_cli_plan_prints_sha(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = mig.main(["--data-root", str(self.data_root), "plan", "--workspace", str(self.workspace),
                             "--out", str(Path(self.tmp.name) / "plan.json")])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out.getvalue())["plan_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
