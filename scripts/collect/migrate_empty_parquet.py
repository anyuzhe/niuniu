"""Migrate verified zero-row parquet outputs to typed empty-result markers.

This removes schema-breaking placeholder parquet files without losing evidence.
The original run receipt remains unchanged; a separate migration receipt records
backups, hashes and marker paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect.envelope import empty_marker_path, sha256_file, symbol_filename  # noqa: E402


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def build_plan(destination: Path, receipt_path: Path) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    actions = []
    import pandas as pd
    for entry in receipt.get("empty", []):
        code = entry["code"]
        path = destination / symbol_filename(code)
        if not path.is_file():
            continue
        if entry.get("sha256") != sha256_file(path):
            raise ValueError(f"empty parquet changed after receipt: {code}")
        frame = pd.read_parquet(path)
        if len(frame) != 0:
            raise ValueError(f"receipt says empty but parquet has rows: {code}")
        actions.append({"code": code, "path": str(path.resolve()),
                        "sha256": entry["sha256"], "columns": list(frame.columns)})
    plan = {"kind": "empty_parquet_marker_migration", "schema_version": 1,
            "destination": str(destination.resolve()),
            "source_receipt": str(receipt_path.resolve()),
            "source_receipt_sha256": sha256_file(receipt_path),
            "actions": actions}
    plan["plan_sha256"] = digest(plan)
    return plan


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-sha256")
    parser.add_argument("--backup-root")
    args = parser.parse_args(argv)
    destination, receipt_path = Path(args.dest), Path(args.receipt)
    plan = build_plan(destination, receipt_path)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.apply:
        return 0
    if args.approve_sha256 != plan["plan_sha256"]:
        print("REFUSED: approval hash mismatch", file=sys.stderr); return 2
    backup_root = (Path(args.backup_root) if args.backup_root else
                   Path("/Volumes/Lexar/niuniu-data/backups") /
                   f"empty-marker-{plan['plan_sha256'][:16]}")
    results = []
    for action in plan["actions"]:
        source = Path(action["path"]); backup = backup_root / source.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists(): raise FileExistsError(backup)
        shutil.copy2(source, backup)
        if sha256_file(backup) != action["sha256"]: raise IOError(f"backup mismatch: {source}")
        marker = empty_marker_path(destination, action["code"])
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker_value = {"code": action["code"], "status": "empty",
                        "source_receipt": str(receipt_path.resolve()),
                        "source_parquet_sha256": action["sha256"],
                        "note": "verified zero-row parquet migrated to marker"}
        tmp = marker.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(marker_value, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, marker)
        source.unlink()
        results.append({"code": action["code"], "backup": str(backup),
                        "marker": str(marker), "marker_sha256": sha256_file(marker)})
    migration = {"plan": plan, "results": results, "status": "completed"}
    output = destination / "_receipts" / f"empty-marker-{plan['plan_sha256'][:16]}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(migration, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, output)
    print(f"migration receipt: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
