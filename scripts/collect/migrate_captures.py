"""Copy workspace market-data captures into the data root (remediation stage 2, D1).

  plan      read-only: list every file under <workspace>/_market_data with size and
            SHA-256; print the plan and its SHA
  apply     copy exactly the planned files to <data-root>/lake/_market_data, verify
            each copy, write CAPTURE_ROOT.json and a receipt; resumable
  redirect  point the workspace at the new root (<workspace>/_market_data.redirect.json)
  pointer   rewrite catalog/retro_daily_tail.json to the migrated capture (same pack
            index digest); the previous pointer is kept under catalog/retro_daily_tail.history/

Sources are never modified or deleted: historical manifests keep resolving the old
absolute paths.  Every write step needs the exact plan SHA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from collect import paths  # noqa: E402
from quantlab.data import capture_root as cr  # noqa: E402

PLAN_FORMAT = "niuniu-capture-migration-plan-v1"
RECEIPT_DIR = "_migration"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(body) -> bytes:
    return (json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode()


def _files(source: Path):
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("._"))
        for name in sorted(filenames):
            if name.startswith("._") or name == ".DS_Store":
                continue
            path = Path(dirpath) / name
            if path.is_symlink():
                raise ValueError(f"symlink inside capture tree refused: {path}")
            if path.is_file():
                yield path


def build_plan(workspace: Path, data_root: Path) -> dict:
    workspace = Path(os.path.abspath(workspace))
    source = cr.legacy_root(workspace)
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"source capture tree missing or symlinked: {source}")
    if cr.read_redirect(workspace) is not None:
        raise ValueError("workspace is already redirected; nothing to migrate")
    target = Path(os.path.abspath(data_root)) / "lake" / cr.DIRECTORY_NAME
    files = []
    for path in _files(source):
        st = path.stat()
        files.append({"path": path.relative_to(source).as_posix(), "bytes": st.st_size,
                      "sha256": sha256_file(path)})
    core = {"format": PLAN_FORMAT, "source": str(source), "target": str(target),
            "workspace": str(workspace), "files": files,
            "total_bytes": sum(f["bytes"] for f in files)}
    core["capture_root_id"] = hashlib.sha256(b"niuniu-capture-root|" + canonical(core)).hexdigest()
    core["plan_sha256"] = hashlib.sha256(canonical(core)).hexdigest()
    return core


def _check_plan(plan: dict, approve: str) -> None:
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    if plan.get("format") != PLAN_FORMAT or hashlib.sha256(canonical(body)).hexdigest() != plan.get("plan_sha256"):
        raise PermissionError("plan content does not match its plan_sha256")
    if approve != plan["plan_sha256"]:
        raise PermissionError("approval SHA does not match the plan")


def apply(plan: dict, approve: str) -> dict:
    _check_plan(plan, approve)
    source, target = Path(plan["source"]), Path(plan["target"])
    cr._no_symlink_ancestors(target.parent)
    marker = target / cr.MARKER_NAME
    if marker.exists():
        existing = json.loads(marker.read_text())
        if existing.get("capture_root_id") != plan["capture_root_id"]:
            raise ValueError("target already belongs to a different capture root")
    planned = {f["path"] for f in plan["files"]}
    for path in _files(target):
        rel = path.relative_to(target).as_posix()
        if rel != cr.MARKER_NAME and not rel.startswith(RECEIPT_DIR + "/") and rel not in planned:
            raise ValueError(f"target holds an unplanned file: {rel}")
    # Verify the whole source against the plan before copying anything, so a stale
    # plan never leaves a partial target behind.
    for entry in plan["files"]:
        src = source / entry["path"]
        if not src.is_file() or src.stat().st_size != entry["bytes"] or sha256_file(src) != entry["sha256"]:
            raise ValueError(f"source changed since plan: {entry['path']}")
    target.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for entry in plan["files"]:
        src, dst = source / entry["path"], target / entry["path"]
        if dst.is_file() and dst.stat().st_size == entry["bytes"] and sha256_file(dst) == entry["sha256"]:
            skipped += 1
            continue
        if sha256_file(src) != entry["sha256"]:
            raise ValueError(f"source changed since plan: {entry['path']}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".migrating")
        shutil.copy2(src, tmp)
        if sha256_file(tmp) != entry["sha256"]:
            tmp.unlink()
            raise ValueError(f"copy verification failed: {entry['path']}")
        os.replace(tmp, dst)
        copied += 1
    receipt = {"plan_sha256": plan["plan_sha256"], "capture_root_id": plan["capture_root_id"],
               "source": plan["source"], "target": plan["target"], "files": len(plan["files"]),
               "copied": copied, "already_present": skipped, "total_bytes": plan["total_bytes"],
               "finished_at": datetime.now(timezone.utc).isoformat()}
    receipts = target / RECEIPT_DIR
    receipts.mkdir(exist_ok=True)
    (receipts / f"receipt-{plan['plan_sha256'][:16]}.json").write_bytes(canonical(receipt))
    (receipts / f"plan-{plan['plan_sha256'][:16]}.json").write_bytes(canonical(plan))
    if not marker.exists():
        marker.write_bytes(canonical({"format": cr.MARKER_FORMAT, "capture_root_id": plan["capture_root_id"],
                                      "migrated_from": plan["source"], "plan_sha256": plan["plan_sha256"]}))
    return receipt


def verify_target(plan: dict) -> list[str]:
    target = Path(plan["target"])
    bad = []
    for entry in plan["files"]:
        path = target / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            bad.append(entry["path"])
    return bad


def write_redirect(plan: dict, approve: str) -> Path:
    _check_plan(plan, approve)
    bad = verify_target(plan)
    if bad:
        raise ValueError(f"target incomplete; {len(bad)} files differ (first: {bad[0]})")
    workspace = Path(plan["workspace"])
    redirect = workspace / cr.REDIRECT_NAME
    body = {"format": cr.REDIRECT_FORMAT, "capture_root": plan["target"],
            "capture_root_id": plan["capture_root_id"]}
    if redirect.exists():
        if json.loads(redirect.read_text()) == body:
            return redirect
        raise ValueError("a different redirect already exists")
    tmp = redirect.with_name(redirect.name + ".tmp")
    tmp.write_bytes(canonical(body))
    os.replace(tmp, redirect)
    if cr.capture_root(workspace) != Path(plan["target"]):
        raise RuntimeError("redirect did not take effect")
    return redirect


def rewrite_retro_pointer(plan: dict, approve: str, data_root: Path) -> dict:
    _check_plan(plan, approve)
    pointer = Path(os.path.abspath(data_root)) / "catalog" / "retro_daily_tail.json"
    old_bytes = pointer.read_bytes()
    old = json.loads(old_bytes)
    source = Path(plan["source"])
    capture = Path(old["capture_path"])
    try:
        rel = capture.relative_to(source)
    except ValueError:
        raise ValueError("current pointer does not point into the migrated source tree")
    new_capture = Path(plan["target"]) / rel
    if not new_capture.is_dir():
        raise ValueError(f"migrated capture missing: {new_capture}")
    index_old = json.loads((capture / "packs" / "index.json").read_bytes())
    index_new = json.loads((new_capture / "packs" / "index.json").read_bytes())
    if index_old != index_new or index_new.get("checksum") != old["digest"]:
        raise ValueError("migrated pack index differs from the pointer digest")
    new = dict(old, capture_path=str(new_capture),
               written_by="data-remediation-stage2-20260923")
    history = pointer.parent / "retro_daily_tail.history"
    history.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = history / f"{stamp}-{hashlib.sha256(old_bytes).hexdigest()[:16]}.json"
    backup.write_bytes(old_bytes)
    tmp = pointer.with_name(pointer.name + ".tmp")
    tmp.write_bytes(json.dumps(new, ensure_ascii=False, indent=2).encode() + b"\n")
    os.replace(tmp, pointer)
    return {"pointer": str(pointer), "old_capture_path": str(capture), "new_capture_path": str(new_capture),
            "backup": str(backup), "digest": old["digest"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=str(paths.DATA_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--workspace", required=True, help="工作空间目录（含 _market_data 的 artifacts）")
    p.add_argument("--out", required=True)
    for name in ("apply", "redirect", "pointer"):
        s = sub.add_parser(name)
        s.add_argument("--plan", required=True)
        s.add_argument("--approve-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "plan":
        plan = build_plan(Path(args.workspace), Path(args.data_root))
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(canonical(plan))
        print(json.dumps({"plan": str(out), "files": len(plan["files"]), "total_bytes": plan["total_bytes"],
                          "target": plan["target"], "plan_sha256": plan["plan_sha256"]}))
        return 0
    plan = json.loads(Path(args.plan).read_text())
    if args.command == "apply":
        print(json.dumps(apply(plan, args.approve_sha256), ensure_ascii=False))
    elif args.command == "redirect":
        print(json.dumps({"redirect": str(write_redirect(plan, args.approve_sha256))}))
    else:
        print(json.dumps(rewrite_retro_pointer(plan, args.approve_sha256, Path(args.data_root)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
