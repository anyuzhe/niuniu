"""Shared deterministic-plan and atomic-write helpers for daily collectors."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_digest(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("plan_sha256", None)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def symbol_file(root: Path, code: str) -> Path:
    return root / (code.replace(".", "_", 1) + ".parquet")


def empty_marker(root: Path, code: str) -> Path:
    return root / "_empty" / (code.replace(".", "_", 1) + ".json")


def select_reference_file(asof: date, *, lake: Path, fallback: Path,
                          name: str) -> tuple[Path, str | None]:
    """Prefer the latest completed, hash-verified reference snapshot <= asof."""
    if name not in ("stock_basic", "trade_calendar"):
        raise ValueError("unsupported reference source")
    candidates = sorted((lake / "provider=baostock" / "reference_snapshots").glob("snapshot=*"))
    dated = []
    for path in candidates:
        try:
            day = date.fromisoformat(path.name.removeprefix("snapshot="))
        except ValueError:
            continue
        if day <= asof:
            dated.append((day, path))
    if not dated:
        return fallback, None
    _, snapshot = max(dated)
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("run_status") != "completed":
        raise ValueError(f"latest reference snapshot incomplete: {snapshot}")
    entries = [x for x in manifest.get("results", []) if x.get("name") == name]
    if len(entries) != 1 or entries[0].get("status") != "ok" or entries[0].get("file") != f"{name}.parquet":
        raise ValueError(f"reference {name} manifest invalid")
    path = snapshot / f"{name}.parquet"
    if sha256_file(path) != entries[0].get("sha256"):
        raise ValueError(f"reference {name} hash changed")
    return path, sha256_file(manifest_path)


def select_stock_basic(asof: date, *, lake: Path, fallback: Path) -> tuple[Path, str | None]:
    return select_reference_file(asof, lake=lake, fallback=fallback, name="stock_basic")


def observed_state(root: Path, code: str) -> dict[str, Any]:
    parquet = symbol_file(root, code)
    marker = empty_marker(root, code)
    if parquet.exists() and marker.exists():
        raise ValueError(f"both parquet and empty marker exist for {code}")
    return {
        "parquet_sha256": sha256_file(parquet) if parquet.is_file() else None,
        "empty_marker_sha256": sha256_file(marker) if marker.is_file() else None,
    }


def validate_observed_state(root: Path, action: dict[str, Any]) -> None:
    actual = observed_state(root, action["code"])
    expected = {key: action.get(key) for key in
                ("parquet_sha256", "empty_marker_sha256")}
    if actual != expected:
        raise ValueError(f"local state changed after plan for {action['code']}")


def _stable_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    import pandas as pd
    if bool(pd.isna(value)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite value in provider frame")
        return {"float": repr(value)}
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)


def logical_frame_digest(frame) -> str:
    """Order-insensitive, duplicate-preserving digest of a provider frame."""
    columns = sorted(str(column) for column in frame.columns)
    rows = []
    for values in frame.reindex(columns=columns).itertuples(index=False, name=None):
        normalized = [_stable_value(value) for value in values]
        rows.append(json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")))
    rows.sort()
    payload = {"columns": columns, "rows": rows}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def atomic_parquet(frame, path: Path) -> str:
    import pandas as pd
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    back = pd.read_parquet(tmp)
    if len(back) != len(frame) or list(back.columns) != list(frame.columns):
        tmp.unlink(missing_ok=True)
        raise ValueError(f"parquet read-back mismatch: {path}")
    os.replace(tmp, path)
    return sha256_file(path)


def backup_verified(source: Path, backup: Path, expected_sha256: str) -> dict[str, str]:
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        raise FileExistsError(backup)
    if sha256_file(source) != expected_sha256:
        raise ValueError(f"source changed before backup: {source}")
    shutil.copy2(source, backup)
    if sha256_file(backup) != expected_sha256:
        raise IOError(f"backup hash mismatch: {source}")
    return {"path": str(backup), "sha256": expected_sha256}


@contextmanager
def run_lock(root: Path, name: str):
    """Exclude concurrent writes; stale locks require manual inspection."""
    path = root / "_receipts" / f".{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(fd)
        path.unlink()


def write_empty_marker(root: Path, code: str, source: str,
                       observed_on: str, evidence: dict[str, Any] | None = None) -> dict[str, str]:
    marker = empty_marker(root, code)
    value: dict[str, Any] = {"code": code, "status": "empty", "source": source,
                             "observed_on": observed_on}
    if evidence:
        value["evidence"] = evidence
    write_json_atomic(marker, value)
    return {"path": str(marker), "sha256": sha256_file(marker)}
