import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from quantlab.data import dataset_registry as reg  # noqa: E402
from collect import inventory, paths, registry as cli  # noqa: E402


def write(path: Path, days):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"date": pa.array([date.fromisoformat(d) for d in days], pa.date32()),
                             "code": pa.array(["sh.600000"] * len(days))}), path)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "data"
        self.work = base / "work"
        write(self.root / "lake/bronze/provider=x/div_v2/sh_600000.parquet", ["2024-01-02"])
        write(self.root / "lake/bronze/provider=x/div/sh_600000.parquet", ["2023-01-02"])
        (self.root / "catalog").mkdir(parents=True)
        self.spec = {"format": cli.SPEC_FORMAT, "datasets": {
            "ca.div.x": {"status": "current", "kind": "per_symbol_parquet",
                         "path": "lake/bronze/provider=x/div_v2", "qualification": "research_only",
                         "producer": "test", "superseded": ["lake/bronze/provider=x/div"]},
            "ca.div.x.v1": {"status": "superseded", "kind": "per_symbol_parquet",
                            "path": "lake/bronze/provider=x/div", "qualification": "research_only",
                            "producer": "test", "superseded_by": "ca.div.x"}}}
        self.spec_path = self.work / "spec.json"
        self.work.mkdir()
        self.spec_path.write_text(json.dumps(self.spec))

    def tearDown(self):
        self.tmp.cleanup()

    def install(self):
        draft = self.work / "draft.json"
        code, out, _ = run(["--data-root", str(self.root), "draft", "--spec", str(self.spec_path),
                            "--out", str(draft)])
        self.assertEqual(code, 0)
        sha = json.loads(out)["sha256"]
        code, out, err = run(["--data-root", str(self.root), "apply", "--draft", str(draft),
                              "--approve-sha256", sha])
        self.assertEqual(code, 0, err)
        return draft, sha

    def test_absent_registry_keeps_legacy_default(self):
        got = reg.resolve(self.root, "ca.div.x", legacy_default="lake/bronze/provider=x/div")
        self.assertEqual(got.source, "legacy_default")
        self.assertTrue(str(got.path).endswith("provider=x/div"))
        with self.assertRaises(reg.RegistryError):
            reg.resolve(self.root, "ca.div.x")

    def test_registry_resolves_current_and_refuses_superseded(self):
        _draft, sha = self.install()
        got = reg.resolve(self.root, "ca.div.x", legacy_default="lake/bronze/provider=x/div")
        self.assertEqual(got.source, "registry")
        self.assertTrue(str(got.path).endswith("provider=x/div_v2"))
        self.assertEqual(got.registry_sha256, sha)
        with self.assertRaises(reg.RegistryError):
            reg.resolve(self.root, "ca.div.x.v1")
        with self.assertRaises(reg.RegistryError):
            reg.resolve(self.root, "not.registered", legacy_default="lake/bronze/provider=x/div")

    def test_apply_requires_exact_sha_and_keeps_history(self):
        draft = self.work / "draft.json"
        run(["--data-root", str(self.root), "draft", "--spec", str(self.spec_path), "--out", str(draft)])
        code, _, _ = run(["--data-root", str(self.root), "apply", "--draft", str(draft),
                          "--approve-sha256", "0" * 64])
        self.assertEqual(code, 2)
        self.assertFalse((self.root / reg.REGISTRY_RELATIVE).exists())
        _draft, first = self.install()
        self.spec["datasets"]["ca.div.x"]["notes"] = "second"
        self.spec_path.write_text(json.dumps(self.spec))
        _draft, second = self.install()
        self.assertNotEqual(first, second)
        history = list((self.root / reg.HISTORY_RELATIVE).iterdir())
        self.assertEqual(len(history), 1)
        self.assertEqual(hashlib.sha256(history[0].read_bytes()).hexdigest(), first)

    def test_draft_refused_inside_data_root_and_drift_refuses_apply(self):
        code, _, _ = run(["--data-root", str(self.root), "draft", "--spec", str(self.spec_path),
                          "--out", str(self.root / "draft.json")])
        self.assertEqual(code, 2)
        draft = self.work / "draft.json"
        _, out, _ = run(["--data-root", str(self.root), "draft", "--spec", str(self.spec_path),
                         "--out", str(draft)])
        sha = json.loads(out)["sha256"]
        write(self.root / "lake/bronze/provider=x/div_v2/sz_000001.parquet", ["2024-01-03"])
        code, _, err = run(["--data-root", str(self.root), "apply", "--draft", str(draft),
                            "--approve-sha256", sha])
        self.assertEqual(code, 2)
        self.assertIn("drift", err)

    def test_verify_reports_drift_without_blocking_resolve(self):
        self.install()
        write(self.root / "lake/bronze/provider=x/div_v2/sz_000001.parquet", ["2024-01-03"])
        code, out, _ = run(["--data-root", str(self.root), "verify"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["results"][0]["status"], "drift")
        self.assertEqual(reg.resolve(self.root, "ca.div.x").source, "registry")

    def test_fingerprint_matches_inventory(self):
        directory = self.root / "lake/bronze/provider=x/div_v2"
        (directory / "._sh_600000.parquet").write_bytes(b"x")
        entry = inventory.inventory_dataset(directory, self.root, deep_hash=False, workers=1)
        self.assertEqual(entry["listing_fingerprint"], reg.listing_fingerprint(directory)["listing_fingerprint"])

    def test_invalid_registry_fails_closed(self):
        target = self.root / reg.REGISTRY_RELATIVE
        cases = [
            b"{not json",
            json.dumps({"format": "other", "datasets": {}}).encode(),
            json.dumps({"format": reg.FORMAT, "datasets": {"a.b": {
                "status": "current", "kind": "per_symbol_parquet", "path": "../escape",
                "qualification": "research_only", "producer": "t"}}}).encode(),
            json.dumps({"format": reg.FORMAT, "datasets": {"a.b": {
                "status": "current", "kind": "per_symbol_parquet", "path": "lake/missing",
                "qualification": "research_only", "producer": "t"}}}).encode(),
            json.dumps({"format": reg.FORMAT, "datasets": {"a.b": {
                "status": "current", "kind": "per_symbol_parquet", "path": "lake/bronze/provider=x/div",
                "qualification": "research_only", "producer": "t", "surprise": 1}}}).encode(),
        ]
        for payload in cases:
            target.write_bytes(payload)
            with self.assertRaises(reg.RegistryError):
                reg.resolve(self.root, "a.b", legacy_default="lake/bronze/provider=x/div")

    def test_symlinked_component_refused(self):
        os.symlink(self.root / "lake/bronze/provider=x/div_v2", self.root / "lake/bronze/provider=x/link")
        self.spec["datasets"]["ca.div.x"]["path"] = "lake/bronze/provider=x/link"
        self.spec_path.write_text(json.dumps(self.spec))
        with self.assertRaises(reg.RegistryError):
            cli.build_draft(self.root, self.spec)

    def test_views_preview_and_apply_only_touch_reg_views(self):
        import duckdb
        self.install()
        catalog = self.root / "catalog" / "mqc.duckdb"
        con = duckdb.connect(str(catalog))
        con.execute("create table keep_me as select 1 as x")
        con.execute("create view bronze_other as select * from keep_me")
        con.close()
        code, out, _ = run(["--data-root", str(self.root), "views", "--view-root", str(self.root)])
        self.assertEqual(code, 0)
        plan = json.loads(out)
        self.assertEqual([s["view"] for s in plan["statements"]], ["reg_ca_div_x"])
        code, _, _ = run(["--data-root", str(self.root), "views", "--view-root", str(self.root),
                          "--apply", "--approve-sha256", "0" * 64])
        self.assertEqual(code, 2)
        code, _, err = run(["--data-root", str(self.root), "views", "--view-root", str(self.root),
                            "--apply", "--approve-sha256", plan["plan_sha256"]])
        self.assertEqual(code, 0, err)
        con = duckdb.connect(str(catalog), read_only=True)
        self.assertEqual(con.execute("select count(*) from reg_ca_div_x").fetchone()[0], 1)
        self.assertEqual(con.execute("select count(*) from bronze_other").fetchone()[0], 1)
        con.close()


class PathsTest(unittest.TestCase):
    def test_env_override_and_legacy_default(self):
        self.assertEqual(paths.resolve_data_root({}), (paths.LEGACY_DEFAULT, "legacy_default"))
        self.assertEqual(paths.resolve_data_root({paths.ENV_VAR: "/data/x"}),
                         (Path("/data/x"), f"env:{paths.ENV_VAR}"))
        with self.assertRaises(ValueError):
            paths.resolve_data_root({paths.ENV_VAR: "relative/x"})

    def test_no_collector_hardcodes_the_data_root(self):
        for path in (ROOT / "scripts" / "collect").glob("*.py"):
            if path.name == "paths.py":
                continue
            self.assertNotIn("/Volumes/Lexar/niuniu-data", path.read_text(), path.name)

    def test_full_history_corporate_collectors_require_dest(self):
        from collect import cninfo_allotment, ths_dividend
        for module in (ths_dividend, cninfo_allotment):
            self.assertIsNone(module.DEFAULT_DEST)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                module.main(["--dry-run"])
            self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
