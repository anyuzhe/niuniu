"""Versioned computation fingerprint for cache and compatibility checks.

This deliberately does not replace ``runtime_fingerprint``.  Approval,
SessionGrant, JobQueue guards and exact reproduction continue to bind the full
application runtime.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import re
from pathlib import Path
from quantlab.storage.codec import digest

DEPENDENCIES = ("numpy", "polars", "pyarrow", "duckdb")
EXCLUDED_PREFIXES = ("desktop/",)
RESOURCE_SUFFIXES = (".json",)
VERSION = "computation-runtime-v1"


def _include(relative: str, path: Path) -> bool:
    if any(relative.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if path.suffix == ".py":
        return True
    if path.suffix in RESOURCE_SUFFIXES:
        # Keep factor expressions and vendored computation provenance, but do not
        # treat view resources as computation inputs.
        return not relative.startswith('desktop/')
    return False


def computation_fingerprint() -> dict:
    root = Path(__file__).resolve().parents[1]
    files = {}
    included = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _include(rel, path):
            if path.is_symlink():raise ValueError('Computation source cannot be a symlink: '+rel)
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            included.append(rel)
    dependencies = {}
    for name in DEPENDENCIES:
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError('Computation dependency is unavailable: '+name) from exc
    return {
        "version": VERSION,
        "code_hash": digest(files),
        "python": platform.python_version(),
        "dependencies": dependencies,
        "included_count": len(included),
        "included": included,
        "excluded": list(EXCLUDED_PREFIXES),
        "scope": "Computation-related Python and JSON resources; desktop UI is excluded. Not an approval or exact reproduction runtime.",
    }


def computation_identity(value: dict) -> dict:
    if not isinstance(value,dict) or value.get('version') != VERSION:
        raise ValueError('unsupported computation runtime version')
    if not isinstance(value.get('code_hash'),str) or re.fullmatch(r'[a-f0-9]{64}',value['code_hash']) is None:
        raise ValueError('invalid computation code_hash')
    deps=value.get('dependencies')
    if (not isinstance(value.get('python'),str) or not value['python'] or not isinstance(deps,dict)
            or set(deps)!=set(DEPENDENCIES) or any(not isinstance(v,str) or not v for v in deps.values())):
        raise ValueError('invalid computation interpreter/dependency contract')
    return {k:value[k] for k in ('version','code_hash','python','dependencies')}


def computation_cache_key(value: dict) -> str:
    # A dependency or interpreter change invalidates cached values even if source bytes match.
    return digest(computation_identity(value))


def compatible_computation_runtime(saved: dict | None, current: dict | None = None) -> tuple[bool, str]:
    if saved is None:
        return False, 'legacy archive has no computation_runtime; exact full runtime is required'
    if current is None:current=computation_fingerprint()
    try:left,right=computation_identity(saved),computation_identity(current)
    except ValueError as exc:return False,str(exc)
    for key in left:
        if left[key]!=right[key]:return False,'computation runtime differs: '+key
    return True,'computation runtime compatible; not an approval or cross-application exact reproduction claim'


def manifest_runtime_compatible(manifest: dict, current_runtime: dict, current_computation: dict | None = None) -> tuple[bool, str]:
    # Full runtime omits JSON and numpy. It must not bypass the stronger new contract.
    if 'computation_runtime' in manifest:
        return compatible_computation_runtime(manifest['computation_runtime'],current_computation)
    if manifest.get('runtime') == current_runtime:
        return True,'legacy full application runtime exact'
    return False,'legacy archive requires exact full runtime'


def archived_runtimes_compatible(left: dict,right: dict) -> tuple[bool,str]:
    if 'computation_runtime' in left and 'computation_runtime' in right:
        return compatible_computation_runtime(left['computation_runtime'],right['computation_runtime'])
    if left.get('runtime')!=right.get('runtime'):
        return False,'legacy archives require matching full application runtime'
    for item in (left,right):
        if 'computation_runtime' in item:
            try:computation_identity(item['computation_runtime'])
            except ValueError as exc:return False,str(exc)
    return True,'legacy/full application runtime exact; not resource-level legacy certification'
