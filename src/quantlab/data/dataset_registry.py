"""Dataset registry: which physical directory is the *current* version of a dataset.

Remediation stage 1 (P2).  The data root keeps every historical directory in place;
``catalog/dataset_registry.json`` declares, per logical dataset name, the one
directory that is ``current`` and the directories it ``supersedes``.

Contract:

* The registry is optional.  When the file is absent, :func:`resolve` returns the
  caller's legacy default path and says so (``source="legacy_default"``); existing
  behaviour is unchanged.
* When the file is present it is authoritative: malformed JSON, unknown fields,
  paths escaping the data root, symlinked path components, a missing current
  directory or an unknown dataset name all raise.  There is no silent fallback.
* ``listing_fingerprint`` detects that a directory changed (path, size, mtime).
  It does not pin bytes.  ``content_manifest_sha256`` pins bytes when present.
* The registry never upgrades qualification: ``research_only`` stays research_only.
* ``version_ledger`` optionally points at an F21 observation/revision ledger for the
  same dataset.  The registry does not interpret event revisions and F21 does not
  choose the current directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

FORMAT = "niuniu-dataset-registry-v1"
REGISTRY_RELATIVE = "catalog/dataset_registry.json"
HISTORY_RELATIVE = "catalog/registry_history"
STATUSES = ("current", "superseded", "legacy", "quarantine")
KINDS = ("per_symbol_parquet", "single_table", "dated_snapshots", "catalog_backed", "capture_tree")
NAME = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ENTRY_FIELDS = {
    "status", "kind", "path", "qualification", "producer", "files", "bytes",
    "listing_fingerprint", "content_manifest_sha256", "superseded", "superseded_by",
    "known_issues", "notes", "version_ledger",
}
REQUIRED_ENTRY = {"status", "kind", "path", "qualification", "producer"}
TOP_FIELDS = {"format", "datasets", "fingerprint_semantics", "created_from"}
MAX_BYTES = 1024 * 1024


class RegistryError(ValueError):
    pass


def is_skipped(name: str) -> bool:
    return name.startswith("._") or name == ".DS_Store"


def listing_fingerprint(directory: Path) -> dict:
    """SHA-256 over sorted ``relpath\\tsize\\tmtime_ns`` (same rule as inventory.py)."""
    digest = hashlib.sha256()
    files = size = 0
    for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not is_skipped(d))
        for name in sorted(filenames):
            if is_skipped(name):
                continue
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            st = path.stat()
            rel = path.relative_to(directory).as_posix()
            digest.update(f"{rel}\t{st.st_size}\t{st.st_mtime_ns}\n".encode())
            files += 1
            size += st.st_size
    return {"listing_fingerprint": digest.hexdigest(), "files": files, "bytes": size}


def _safe_relative(data_root: Path, relative: str, *, field: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise RegistryError(f"{field}: path must be a non-empty string")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise RegistryError(f"{field}: path must be relative inside the data root: {relative!r}")
    current = data_root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise RegistryError(f"{field}: symlinked path component refused: {current}")
    return current


def _validate_entry(name: str, entry, data_root: Path) -> None:
    where = f"datasets[{name}]"
    if not NAME.match(name):
        raise RegistryError(f"{where}: invalid dataset name")
    if not isinstance(entry, dict):
        raise RegistryError(f"{where}: entry must be an object")
    unknown = set(entry) - ENTRY_FIELDS
    if unknown:
        raise RegistryError(f"{where}: unknown fields {sorted(unknown)}")
    missing = REQUIRED_ENTRY - set(entry)
    if missing:
        raise RegistryError(f"{where}: missing fields {sorted(missing)}")
    if entry["status"] not in STATUSES:
        raise RegistryError(f"{where}: status must be one of {STATUSES}")
    if entry["kind"] not in KINDS:
        raise RegistryError(f"{where}: kind must be one of {KINDS}")
    path = _safe_relative(data_root, entry["path"], field=f"{where}.path")
    if entry["status"] == "current" and not path.is_dir():
        raise RegistryError(f"{where}: current directory missing: {entry['path']}")
    for key in ("listing_fingerprint", "content_manifest_sha256"):
        value = entry.get(key)
        if value is not None and not (isinstance(value, str) and HEX64.match(value)):
            raise RegistryError(f"{where}.{key}: must be 64 lowercase hex or null")
    for rel in entry.get("superseded", []) or []:
        _safe_relative(data_root, rel, field=f"{where}.superseded")
    ledger = entry.get("version_ledger")
    if ledger is not None:
        if not isinstance(ledger, dict) or set(ledger) - {"path", "sha256", "summary_path", "summary_sha256"}:
            raise RegistryError(f"{where}.version_ledger: unexpected shape")
        for key in ("sha256", "summary_sha256"):
            if key in ledger and not HEX64.match(str(ledger[key])):
                raise RegistryError(f"{where}.version_ledger.{key}: must be 64 hex")


@dataclass(frozen=True)
class Registry:
    data_root: Path
    path: Path
    sha256: str
    datasets: dict

    def entry(self, name: str) -> dict:
        if name not in self.datasets:
            raise RegistryError(f"dataset not registered: {name}")
        return self.datasets[name]

    def current_names(self) -> list[str]:
        return sorted(n for n, e in self.datasets.items() if e["status"] == "current")


def parse_registry(payload: bytes, data_root: Path, *, path: Path | None = None) -> Registry:
    if len(payload) > MAX_BYTES:
        raise RegistryError("registry exceeds size limit")
    try:
        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"registry is not valid JSON: {exc}") from exc
    if not isinstance(body, dict) or body.get("format") != FORMAT:
        raise RegistryError(f"registry format must be {FORMAT}")
    unknown = set(body) - TOP_FIELDS
    if unknown:
        raise RegistryError(f"unknown top-level fields {sorted(unknown)}")
    datasets = body.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        raise RegistryError("registry has no datasets")
    data_root = Path(data_root).resolve()
    for name, entry in datasets.items():
        _validate_entry(name, entry, data_root)
    current_paths = [e["path"] for e in datasets.values() if e["status"] == "current"]
    if len(current_paths) != len(set(current_paths)):
        raise RegistryError("two current datasets share one directory")
    return Registry(data_root, path or data_root / REGISTRY_RELATIVE,
                    hashlib.sha256(payload).hexdigest(), datasets)


def load_registry(data_root) -> Registry | None:
    """Return the registry, ``None`` when absent; raise when present but invalid."""
    data_root = Path(data_root).resolve()
    path = data_root / REGISTRY_RELATIVE
    if path.is_symlink():
        raise RegistryError("registry file must not be a symlink")
    if not path.exists():
        return None
    return parse_registry(path.read_bytes(), data_root, path=path)


@dataclass(frozen=True)
class ResolvedDataset:
    name: str
    path: Path
    source: str               # "registry" | "legacy_default"
    registry_sha256: str | None
    entry: dict | None


def resolve(data_root, name: str, *, legacy_default: str | None = None) -> ResolvedDataset:
    """Physical directory of the current version of ``name``.

    Without a registry file the caller's ``legacy_default`` (relative to the data
    root) is returned unchanged.  With a registry, ``name`` must be registered and
    ``current``; the legacy default is ignored.
    """
    data_root = Path(data_root).resolve()
    registry = load_registry(data_root)
    if registry is None:
        if legacy_default is None:
            raise RegistryError(f"no registry and no legacy default for {name}")
        return ResolvedDataset(name, _safe_relative(data_root, legacy_default, field=name),
                               "legacy_default", None, None)
    entry = registry.entry(name)
    if entry["status"] != "current":
        raise RegistryError(f"dataset {name} is {entry['status']}, not current")
    return ResolvedDataset(name, data_root / entry["path"], "registry", registry.sha256, entry)


def verify(registry: Registry, names=None) -> list[dict]:
    """Recompute listing fingerprints for current entries that carry one."""
    results = []
    for name in sorted(names or registry.current_names()):
        entry = registry.entry(name)
        expected = entry.get("listing_fingerprint")
        actual = listing_fingerprint(registry.data_root / entry["path"])
        results.append({
            "name": name, "path": entry["path"],
            "expected": expected, "actual": actual["listing_fingerprint"],
            "files": actual["files"], "bytes": actual["bytes"],
            "status": ("unpinned" if expected is None else
                       "match" if expected == actual["listing_fingerprint"] else "drift"),
        })
    return results
