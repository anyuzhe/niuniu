"""Read the DATA-owned catalog without re-validating DATA correctness.

The catalog is the handoff boundary: DATA decides whether a dataset is READY;
CODE only discovers and reads that declaration. This module performs format
and basic technical checks only. It never scans the data root for substitutes.
"""
from __future__ import annotations

from pathlib import Path
import os
import re


CATALOG_FORMAT = "niuniu-data-catalog-v1"
STATUSES = ("READY", "NOT_READY", "REVIEW_REQUIRED", "DEPRECATED")
DELIVERIES = ("FILE", "DATABASE", "API", "STREAM")
LEGACY_DELIVERY = "LEGACY_PATH"
MAX_CATALOG_BYTES = 256 * 1024
_READY_HEADING = "## 3. 可供 CODE 使用的数据（READY）"
_OTHER_HEADINGS = (
    "## 4. 尚不可用、待审查或只供 DATA 内部使用",
    "## 4. 尚不可用或只供 DATA 内部使用",
)
_ABS_PATH = re.compile(r"`(/[^`]+)`")


class DataCatalogError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def default_data_catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "reference" / "data-catalog.md"


def _path(value=None) -> Path:
    path = default_data_catalog_path() if value is None else Path(value)
    if path.is_symlink():
        raise DataCatalogError("DATA_CATALOG_PATH_REJECTED", "DATA catalog must not be a symlink")
    if not path.is_file():
        raise DataCatalogError("DATA_CATALOG_NOT_CONFIGURED", "DATA catalog file is not available")
    return path.resolve()


def _split_markdown_row(line: str) -> list[str]:
    text = line.strip()
    if not (text.startswith("|") and text.endswith("|")):
        raise DataCatalogError("DATA_CATALOG_FORMAT_INVALID", "catalog table row is malformed")
    cells, current, in_code, escaped = [], [], False, False
    for ch in text[1:-1]:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            current.append(ch)
            escaped = True
        elif ch == "`":
            current.append(ch)
            in_code = not in_code
        elif ch == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    cells.append("".join(current).strip())
    return cells


def _code_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "`":
        return value[1:-1]
    return value


def read_data_catalog(catalog_path=None) -> dict:
    path = _path(catalog_path)
    raw = path.read_bytes()
    if len(raw) > MAX_CATALOG_BYTES:
        raise DataCatalogError("DATA_CATALOG_TOO_LARGE", "DATA catalog exceeds 256 KiB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DataCatalogError("DATA_CATALOG_FORMAT_INVALID", "DATA catalog must be UTF-8") from exc

    section = None
    entries = []
    seen = set()
    for line in text.splitlines():
        if line == _READY_HEADING:
            section = "ready"
            continue
        if line in _OTHER_HEADINGS:
            section = "other"
            continue
        if line.startswith("## "):
            section = None
            continue
        if section is None or not line.lstrip().startswith("| `"):
            continue
        cells = _split_markdown_row(line)
        if len(cells) == 8:
            dataset_id = _code_value(cells[0])
            delivery = _code_value(cells[1]).upper()
            content, address, fmt, coverage, status_cell, code_use = cells[2:]
        elif len(cells) == 7:
            # Compatibility with the first DATA/CODE catalog revision, whose
            # third column was simply “路径” and had no delivery-mode column.
            dataset_id = _code_value(cells[0])
            delivery = LEGACY_DELIVERY
            content, address, fmt, coverage, status_cell, code_use = cells[1:]
        else:
            raise DataCatalogError("DATA_CATALOG_FORMAT_INVALID", "DATA catalog rows must have 7 or 8 columns")
        status = _code_value(status_cell).upper()
        if not dataset_id or len(dataset_id) > 128:
            raise DataCatalogError("DATA_CATALOG_FORMAT_INVALID", "invalid dataset id")
        if dataset_id in seen:
            raise DataCatalogError("DATA_CATALOG_FORMAT_INVALID", "duplicate dataset id: " + dataset_id)
        if delivery not in (*DELIVERIES, LEGACY_DELIVERY):
            raise DataCatalogError("DATA_CATALOG_FORMAT_INVALID", "invalid delivery mode for " + dataset_id)
        if status not in STATUSES:
            raise DataCatalogError("DATA_CATALOG_FORMAT_INVALID", "invalid DATA status for " + dataset_id)
        # DATA may group reviewed and still-pending API entries under one human-facing
        # section. The row's explicit DATA status is authoritative; CODE must not
        # invent a second status from Markdown placement.
        seen.add(dataset_id)
        entries.append({
            "dataset_id": dataset_id,
            "delivery": delivery,
            "content": content,
            "address": address,
            "format_granularity": fmt,
            "coverage_usage": coverage,
            "status": status,
            "code_use": code_use,
        })
    if not entries:
        raise DataCatalogError("DATA_CATALOG_FORMAT_INVALID", "DATA catalog contains no dataset rows")
    counts = {status: sum(row["status"] == status for row in entries) for status in STATUSES}
    return {"format": CATALOG_FORMAT, "entries": entries, "counts": counts}


def list_data_catalog(catalog_path=None, *, status="READY", delivery="ALL", offset=0, limit=20) -> dict:
    if status not in (*STATUSES, "ALL"):
        raise DataCatalogError("INVALID_ARGUMENT", "status must be READY/NOT_READY/REVIEW_REQUIRED/DEPRECATED/ALL")
    if delivery not in (*DELIVERIES, "ALL"):
        raise DataCatalogError("INVALID_ARGUMENT", "delivery must be FILE/DATABASE/API/STREAM/ALL")
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 20:
        raise DataCatalogError("INVALID_ARGUMENT", "invalid pagination")
    catalog = read_data_catalog(catalog_path)
    rows = [
        row for row in catalog["entries"]
        if (status == "ALL" or row["status"] == status)
        and (delivery == "ALL" or row["delivery"] == delivery
             or (delivery == "FILE" and row["delivery"] == LEGACY_DELIVERY))
    ]
    page = rows[offset:offset + limit]
    return {
        "format": CATALOG_FORMAT,
        "data_authority": "DATA",
        "filters": {"status": status, "delivery": delivery},
        "rows": page,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "returned": len(page),
            "total": len(rows),
            "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
        },
        "limitations": [
            "CODE treats DATA status/coverage as authoritative and does not re-audit data correctness.",
            "No data-root discovery or provider fallback is performed.",
        ],
    }


def get_data_catalog_entry(catalog_path=None, *, dataset_id: str) -> dict:
    if not isinstance(dataset_id, str) or not dataset_id or len(dataset_id) > 128:
        raise DataCatalogError("INVALID_ARGUMENT", "invalid dataset_id")
    catalog = read_data_catalog(catalog_path)
    row = next((item for item in catalog["entries"] if item["dataset_id"] == dataset_id), None)
    if row is None:
        raise DataCatalogError("DATASET_NOT_LISTED", "DATA has not listed this dataset")
    return dict(row)


def is_data_ready(catalog_path=None, *, dataset_id: str) -> bool:
    try:
        return get_data_catalog_entry(catalog_path, dataset_id=dataset_id)["status"] == "READY"
    except DataCatalogError:
        return False


def get_ready_data_source(catalog_path=None, *, dataset_id: str) -> dict:
    row = get_data_catalog_entry(catalog_path, dataset_id=dataset_id)
    if row["status"] != "READY":
        raise DataCatalogError("DATASET_NOT_READY", "DATA has not marked this dataset READY: " + row["status"])
    addresses = _ABS_PATH.findall(row["address"])
    technical = {"checked": False, "paths": []}
    if row["delivery"] in ("FILE", "DATABASE", LEGACY_DELIVERY) and addresses:
        technical["checked"] = True
        for value in addresses:
            path = Path(value)
            technical["paths"].append({
                "path": value,
                "exists": path.exists(),
                "readable": os.access(path, os.R_OK) if path.exists() else False,
            })
        if not all(item["exists"] and item["readable"] for item in technical["paths"]):
            raise DataCatalogError("DATA_SOURCE_UNREADABLE", "DATA-listed READY path is missing or unreadable")
    return {
        "format": CATALOG_FORMAT,
        "data_authority": "DATA",
        "entry": row,
        "technical_check": technical,
        "data_correctness_revalidated_by_code": False,
        "fallback_performed": False,
    }


__all__ = [
    "CATALOG_FORMAT", "STATUSES", "DELIVERIES", "LEGACY_DELIVERY", "DataCatalogError",
    "default_data_catalog_path", "read_data_catalog", "list_data_catalog",
    "get_data_catalog_entry", "is_data_ready", "get_ready_data_source",
]
