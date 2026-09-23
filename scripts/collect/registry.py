"""Draft, verify and apply the dataset registry; preview/apply registry catalog views.

Remediation stage 1.  Same two-phase contract as the collectors: every write needs
the exact SHA-256 of a draft the operator has reviewed.

  draft   read-only; spec + disk facts → draft JSON (+ its SHA) outside the data root
  verify  read-only; recompute listing fingerprints of the installed registry
  apply   write catalog/dataset_registry.json from an approved draft; the previous
          registry (if any) is copied to catalog/registry_history/ first
  views   preview (default) or apply ``reg_*`` DuckDB views for current Parquet
          datasets; never touches tables or non-``reg_`` views

Nothing here moves, renames or deletes data files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from collect import paths  # noqa: E402
from quantlab.data import dataset_registry as reg  # noqa: E402

SPEC_FORMAT = "niuniu-dataset-registry-spec-v1"
DEFAULT_SPEC = Path(__file__).resolve().parent / "registry_spec.json"
VIEW_PREFIX = "reg_"
VIEW_KINDS = {"per_symbol_parquet", "single_table"}


def canonical(body) -> bytes:
    return (json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def build_draft(data_root: Path, spec: dict) -> dict:
    if spec.get("format") != SPEC_FORMAT:
        raise reg.RegistryError(f"spec format must be {SPEC_FORMAT}")
    datasets = {}
    for name, entry in sorted(spec["datasets"].items()):
        entry = dict(entry)
        directory = reg._safe_relative(data_root, entry["path"], field=name)
        if directory.is_dir():
            entry.update(reg.listing_fingerprint(directory))
        else:
            entry.update({"listing_fingerprint": None, "files": 0, "bytes": 0})
        entry.setdefault("content_manifest_sha256", None)
        datasets[name] = entry
    body = {
        "format": reg.FORMAT,
        "datasets": datasets,
        "created_from": {"spec_sha256": hashlib.sha256(canonical(spec)).hexdigest()},
        "fingerprint_semantics": {
            "listing_fingerprint": "sha256(sorted relpath,size,mtime_ns) at draft time; change detection only; "
                                   "drift after a later approved collection is expected and does not block resolve",
            "content_manifest_sha256": "null until a stage pins bytes (e.g. stage 4 qfq inputs)",
        },
    }
    reg.parse_registry(canonical(body), data_root)  # the draft must itself be valid
    return body


def view_name(dataset: str) -> str:
    return VIEW_PREFIX + re.sub(r"[^a-z0-9]+", "_", dataset.lower()).strip("_")


def view_statements(registry: reg.Registry, view_root: str) -> list[tuple[str, str]]:
    """``CREATE OR REPLACE VIEW`` for current per-symbol / single-table datasets.

    ``view_root`` is the data-root path as the *catalog's user* sees it (the Mac
    path), which may differ from where this process reads the data.
    """
    if "'" in view_root:
        raise ValueError("view root must not contain quotes")
    out = []
    for name in registry.current_names():
        entry = registry.entry(name)
        if entry["kind"] not in VIEW_KINDS:
            continue
        glob = f"{view_root.rstrip('/')}/{entry['path']}/*.parquet"
        sql = (f"CREATE OR REPLACE VIEW {view_name(name)} AS SELECT * FROM "
               f"read_parquet('{glob}', union_by_name=true)")
        out.append((view_name(name), sql))
    return out


def cmd_draft(args) -> int:
    data_root = Path(args.data_root).resolve()
    out = Path(args.out)
    if _inside(out, data_root):
        print("拒绝：草稿必须写在数据根之外", file=sys.stderr)
        return 2
    spec = json.loads(Path(args.spec).read_text())
    payload = canonical(build_draft(data_root, spec))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    print(json.dumps({"draft": str(out), "sha256": hashlib.sha256(payload).hexdigest()}))
    return 0


def cmd_verify(args) -> int:
    registry = reg.load_registry(args.data_root)
    if registry is None:
        print(json.dumps({"registry": "absent"}))
        return 3
    results = reg.verify(registry)
    print(json.dumps({"registry_sha256": registry.sha256, "results": results}, ensure_ascii=False, indent=1))
    return 0 if all(r["status"] != "drift" for r in results) else 3


def cmd_apply(args) -> int:
    data_root = Path(args.data_root).resolve()
    payload = Path(args.draft).read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != args.approve_sha256:
        print(f"拒绝：草稿 SHA {actual} 与批准值不符", file=sys.stderr)
        return 2
    draft = reg.parse_registry(payload, data_root)
    drift = [r for r in reg.verify(draft) if r["status"] == "drift"]
    if drift:
        print(json.dumps({"refused": "listing drift since draft", "drift": drift}, ensure_ascii=False, indent=1),
              file=sys.stderr)
        return 2
    target = data_root / reg.REGISTRY_RELATIVE
    history = data_root / reg.HISTORY_RELATIVE
    previous = None
    if target.exists():
        old = target.read_bytes()
        previous = hashlib.sha256(old).hexdigest()
        if previous == actual:
            print(json.dumps({"unchanged": str(target), "sha256": actual}))
            return 0
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = history / f"{stamp}-{previous[:16]}.json"
        shutil.copy2(target, backup)
        if hashlib.sha256(backup.read_bytes()).hexdigest() != previous:
            raise RuntimeError("registry backup verification failed")
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(payload)
    if hashlib.sha256(tmp.read_bytes()).hexdigest() != actual:
        raise RuntimeError("registry readback verification failed")
    os.replace(tmp, target)
    print(json.dumps({"installed": str(target), "sha256": actual, "previous_sha256": previous}))
    return 0


def cmd_views(args) -> int:
    registry = reg.load_registry(args.data_root)
    if registry is None:
        print("拒绝：数据根没有注册表", file=sys.stderr)
        return 2
    statements = view_statements(registry, args.view_root)
    plan = {"registry_sha256": registry.sha256, "view_root": args.view_root,
            "statements": [{"view": v, "sql": s} for v, s in statements]}
    plan_sha = hashlib.sha256(canonical(plan)).hexdigest()
    print(json.dumps({**plan, "plan_sha256": plan_sha}, ensure_ascii=False, indent=1))
    if not args.apply:
        return 0
    if args.approve_sha256 != plan_sha:
        print("拒绝：视图计划 SHA 与批准值不符", file=sys.stderr)
        return 2
    import duckdb
    catalog = Path(args.data_root).resolve() / "catalog" / "mqc.duckdb"
    con = duckdb.connect(str(catalog))
    try:
        existing = dict(con.execute("select view_name, sql from duckdb_views() where not internal").fetchall())
        tables = {r[0] for r in con.execute("select table_name from duckdb_tables()").fetchall()}
        for view, _sql in statements:
            if view in tables:
                raise RuntimeError(f"refusing: {view} is a table")
        history = Path(args.data_root).resolve() / reg.HISTORY_RELATIVE
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (history / f"{stamp}-views-before.json").write_bytes(canonical(
            {"views": {k: v for k, v in sorted(existing.items()) if k.startswith(VIEW_PREFIX)},
             "plan_sha256": plan_sha}))
        con.execute("BEGIN")
        for _view, sql in statements:
            con.execute(sql)
        con.execute("COMMIT")
    finally:
        con.close()
    print(json.dumps({"applied_views": len(statements), "plan_sha256": plan_sha}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=str(paths.DATA_ROOT),
                        help="数据根（默认取 collect.paths：NIUNIU_DATA_ROOT 或历史路径）")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--spec", default=str(DEFAULT_SPEC))
    d.add_argument("--out", required=True)
    sub.add_parser("verify")
    a = sub.add_parser("apply")
    a.add_argument("--draft", required=True)
    a.add_argument("--approve-sha256", required=True)
    v = sub.add_parser("views")
    v.add_argument("--view-root", default=str(paths.LEGACY_DEFAULT),
                   help="写入视图 SQL 的数据根路径（目录库使用方看到的路径）")
    v.add_argument("--apply", action="store_true")
    v.add_argument("--approve-sha256")
    args = parser.parse_args(argv)
    return {"draft": cmd_draft, "verify": cmd_verify, "apply": cmd_apply, "views": cmd_views}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
