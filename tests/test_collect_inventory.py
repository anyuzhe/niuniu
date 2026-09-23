import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import inventory


def write(path: Path, days, extra=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = {"date": pa.array([date.fromisoformat(d) for d in days], pa.date32()),
            "code": pa.array(["sh.600000"] * len(days))}
    if extra:
        cols["amount"] = pa.array([1.0] * len(days))
    pq.write_table(pa.table(cols), path)


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "data"
        self.out = base / "report" / "inventory.json"
        ds = self.root / "lake/bronze/provider=x/bars"
        write(ds / "sh_600000.parquet", ["2024-01-02", "2024-01-03"])
        write(ds / "sh_600001.parquet", ["2023-12-29"], extra=True)
        (ds / "._sh_600000.parquet").write_bytes(b"appledouble")
        (ds / "_empty").mkdir()
        (ds / "_empty" / "sz_000001.json").write_text("{}")
        (ds / "_receipts").mkdir()
        (ds / "_receipts" / "r.json").write_text("{}")
        (ds / "broken.parquet").write_bytes(b"not parquet")
        snap = self.root / "lake/bronze/provider=x/reference_snapshots/snapshot=2026-09-22"
        write(snap / "calendar.parquet", ["2026-09-22"])
        (self.root / "lake/silver/empty_layer").mkdir(parents=True)
        (self.root / "backups").mkdir()
        (self.root / "backups" / "b.bin").write_bytes(b"12345")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *extra):
        return inventory.main(["--data-root", str(self.root), "--out", str(self.out), "--no-catalog", *extra])

    def entry(self, report, suffix):
        return next(d for d in report["datasets"] if d["path"].endswith(suffix))

    def test_facts_and_findings(self):
        code = self.run_main()
        self.assertEqual(code, 1)  # broken parquet is reported, not hidden
        report = json.loads(self.out.read_text())
        bars = self.entry(report, "provider=x/bars")
        self.assertEqual(bars["parquet"], 3)
        self.assertEqual(bars["empty_markers"], 1)
        self.assertEqual(bars["receipts"], 1)
        self.assertEqual(bars["rows_total"], 3)
        self.assertFalse(bars["schema_is_uniform"])
        self.assertEqual(len(bars["column_signatures"]), 2)
        self.assertEqual(bars["date_min"], "2023-12-29")
        self.assertEqual(bars["date_max"], "2024-01-03")
        self.assertEqual([e["path"] for e in bars["errors"]], ["broken.parquet"])
        self.assertIsNone(bars["content_manifest_sha256"])
        # AppleDouble sidecar excluded from counts
        self.assertEqual(bars["files"], 5)
        snap = self.entry(report, "snapshot=2026-09-22")
        self.assertEqual(snap["rows_total"], 1)
        empty = self.entry(report, "silver/empty_layer")
        self.assertEqual(empty["files"], 0)
        backups = next(o for o in report["other_directories"] if o["path"] == "backups")
        self.assertEqual(backups["bytes"], 5)

    def test_deterministic_digest_and_read_only(self):
        before = sorted((p, p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file())
        a = inventory.build_report(self.root, include_catalog=False)
        b = inventory.build_report(self.root, include_catalog=False)
        self.assertEqual(a["report_digest"], b["report_digest"])
        after = sorted((p, p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(before, after)

    def test_listing_vs_content_fingerprint(self):
        target = self.root / "lake/bronze/provider=x/bars/sh_600000.parquet"
        a = inventory.build_report(self.root, deep_hash=True, include_catalog=False)
        stat = target.stat()
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        b = inventory.build_report(self.root, deep_hash=True, include_catalog=False)
        ea, eb = self.entry(a, "provider=x/bars"), self.entry(b, "provider=x/bars")
        self.assertNotEqual(ea["listing_fingerprint"], eb["listing_fingerprint"])
        self.assertEqual(ea["content_manifest_sha256"], eb["content_manifest_sha256"])
        write(target, ["2024-01-02", "2024-01-04"])
        c = inventory.build_report(self.root, deep_hash=True, include_catalog=False)
        self.assertNotEqual(ea["content_manifest_sha256"],
                            self.entry(c, "provider=x/bars")["content_manifest_sha256"])

    def test_refuses_output_inside_data_root(self):
        code = inventory.main(["--data-root", str(self.root), "--out",
                               str(self.root / "inventory.json"), "--no-catalog"])
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "inventory.json").exists())

    def test_only_filter_and_captures(self):
        captures = Path(self.tmp.name) / "artifacts/_market_data"
        write(captures / "daily_market/2026-09-16/x/daily.parquet", ["2026-09-16"])
        report = inventory.build_report(self.root, include_catalog=False, only=["snapshot="],
                                        captures_root=captures)
        self.assertEqual([d["path"] for d in report["datasets"]],
                         ["lake/bronze/provider=x/reference_snapshots/snapshot=2026-09-22"])
        self.assertEqual(report["captures"][0]["path"], "daily_market")
        self.assertEqual(report["captures"][0]["rows_total"], 1)


if __name__ == "__main__":
    unittest.main()
