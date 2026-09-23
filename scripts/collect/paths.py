"""Single place where the collectors learn the data root (remediation P6).

Before this module, ``/Volumes/Lexar/niuniu-data`` was written out in at least six
collector files.  Every collector now derives its lake, catalog and backup paths
from :data:`DATA_ROOT` here.

Resolution order, evaluated once at import time:

1. ``NIUNIU_DATA_ROOT`` environment variable, if set (must be an absolute path);
2. otherwise the historical Mac location :data:`LEGACY_DEFAULT`.

The legacy default is kept on purpose: the daily collectors bind these paths as
module-level constants and their approved-plan workflows run without extra
arguments on the Mac.  ``DATA_ROOT_SOURCE`` records which rule applied so receipts
and plans can say where the root came from.  Nothing here creates directories.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "NIUNIU_DATA_ROOT"
LEGACY_DEFAULT = Path("/Volumes/Lexar/niuniu-data")


def resolve_data_root(environ=None) -> tuple[Path, str]:
    environ = os.environ if environ is None else environ
    value = environ.get(ENV_VAR, "").strip()
    if value:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError(f"{ENV_VAR} must be an absolute path, got {value!r}")
        return path, f"env:{ENV_VAR}"
    return LEGACY_DEFAULT, "legacy_default"


DATA_ROOT, DATA_ROOT_SOURCE = resolve_data_root()
LAKE = DATA_ROOT / "lake" / "bronze"
CATALOG = DATA_ROOT / "catalog" / "mqc.duckdb"
BACKUPS = DATA_ROOT / "backups"


def bronze(provider: str, dataset: str) -> Path:
    return LAKE / f"provider={provider}" / dataset
