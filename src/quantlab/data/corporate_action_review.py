"""Bounded, read-only review of local corporate-action evidence.

This module exposes candidate observations only.  It never rebuilds or publishes an
adjustment factor, changes Provider values, or treats supplier agreement as official
adjudication.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from io import BytesIO
from pathlib import Path
import hashlib
import json
import math
import os
import re

import duckdb
import polars as pl
import pyarrow.parquet as pq


CONTRACT_VERSION = "niuniu-corporate-action-review-v1"
MAX_DAYS = 3660
MAX_LIMIT = 20
MAX_OFFSET = 20_000
MAX_TDX_ROWS = 2_000
MAX_PARQUET_BYTES = 8 * 1024 * 1024
MAX_TOTAL_PARQUET_BYTES = 24 * 1024 * 1024
MAX_PARQUET_ROWS = 20_000
MAX_OUTPUT_BYTES = 192 * 1024
MAX_EVENT_SOURCE_OBSERVATIONS = 100

_PATHS = {
    "tdx": "catalog/mqc.duckdb",
    "eastmoney": "lake/bronze/provider=eastmoney/corporate_actions_dividend/{file}.parquet",
    "ths": "lake/bronze/provider=ths/corporate_actions_dividend/{file}.parquet",
    "qfq": "lake/silver/qfq_kline_daily/{file}.parquet",
}

_CONTRACT = {
    "contract_version": CONTRACT_VERSION,
    "purpose": "bounded_read_only_candidate_evidence_review",
    "public_interfaces": {
        "get_adjustment_review_contract": "get_adjustment_review_contract() -> dict",
        "inspect_corporate_action_sources": (
            "inspect_corporate_action_sources(data_root, symbol, start, end, "
            "offset=0, limit=20) -> dict"
        ),
    },
    "fixed_sources": dict(_PATHS),
    "query_bounds": {
        "one_symbol": True,
        "symbol_pattern": "^(sh|sz|bj)\\.\\d{6}$",
        "explicit_iso_dates": True,
        "maximum_natural_days_inclusive": MAX_DAYS,
        "offset": [0, MAX_OFFSET],
        "limit": [1, MAX_LIMIT],
    },
    "budgets": {
        "tdx_rows_max": MAX_TDX_ROWS,
        "parquet_bytes_each_max": MAX_PARQUET_BYTES,
        "parquet_bytes_total_max": MAX_TOTAL_PARQUET_BYTES,
        "parquet_rows_each_max": MAX_PARQUET_ROWS,
        "event_source_observations_max": MAX_EVENT_SOURCE_OBSERVATIONS,
        "encoded_output_bytes_max": MAX_OUTPUT_BYTES,
    },
    "parser": {
        "supported_examples": [
            "10派4.6元(含税)",
            "10送2转3派1.5元(含税)",
            "10转增3股",
            "每股派0.5元(含税)",
            "不分配不转增",
        ],
        "normalization": "Decimal; declared base normalized to per 10 shares",
        "blocked": [
            "after_tax_cash",
            "cash_tax_basis_unspecified",
            "pending_or_unknown_plan",
            "unrecognized_residual_syntax",
            "differentiated_holder_terms",
            "restricted_or_circulating_holder_terms",
            "multiple_share_bases",
        ],
        "unknown_never_becomes_three_zeroes": True,
    },
    "aggregation": {
        "within_source_only": True,
        "exact_duplicates_fold_with_all_locators": True,
        "distinct_identified_plans_may_form_candidate_total": True,
        "unidentified_or_conflicting_versions_block": True,
        "cross_supplier_values_are_never_added": True,
    },
    "comparison_states": ["agreement", "disagreement", "insufficient", "blocked"],
    "authority": "candidate_not_adjudicated",
    "official_verified": False,
    "lineage_verified": False,
    "reconstruction_authorized": False,
    "known_issue_list_status": "not_bound",
    "qfq_use": "stored consecutive factor diagnostic only; never proves a missing or complete adjustment",
    "tdx_verification": "catalog_rows_only; source-page bytes are not verified by this interface",
    "warnings": [
        "Supplier agreement or disagreement does not certify upstream truth.",
        "Three provider labels do not establish three independent lineages.",
        "TDX c-slot names are statistically inferred candidates, not protocol-certified fields.",
        "No corrected prices or replacement factor are generated.",
        "EM ratio fields lack an explicit tax basis in this contract; raw values remain blocked, not assumed pre-tax.",
    ],
}


def get_adjustment_review_contract() -> dict:
    """Return a detached JSON-compatible copy of the review contract."""
    return json.loads(json.dumps(_CONTRACT, ensure_ascii=False, sort_keys=True))


def _is_redirect(path: Path) -> bool:
    return path.is_symlink() or bool(hasattr(path, "is_junction") and path.is_junction())


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _reject_redirect_ancestors(path: Path) -> None:
    """Reject an existing symlink/junction at any ancestor, including the leaf."""
    absolute = _absolute_without_resolving(path)
    chain = [absolute]
    chain.extend(absolute.parents)
    for candidate in reversed(chain):
        if os.path.lexists(candidate) and _is_redirect(candidate):
            raise ValueError("path ancestor symlink/junction rejected")


def _fixed_path(root: Path, relative: str) -> Path:
    path = root.joinpath(*relative.split("/"))
    _reject_redirect_ancestors(path)
    if not _absolute_without_resolving(path).is_relative_to(root):
        raise ValueError("fixed source path escaped data_root")
    return path


def _validate_inputs(data_root, symbol, start, end, offset, limit):
    if not isinstance(data_root, (str, os.PathLike)) or isinstance(data_root, bytes):
        raise TypeError("data_root must be a path string or PathLike")
    if not isinstance(symbol, str) or not re.fullmatch(r"(?:sh|sz|bj)\.\d{6}", symbol):
        raise ValueError("symbol must be one normalized sh/sz/bj code")
    if type(start) is not str or type(end) is not str:
        raise TypeError("start and end must be explicit ISO date strings")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        raise ValueError("start and end must be YYYY-MM-DD")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("invalid ISO date") from exc
    if first > last:
        raise ValueError("start must be <= end")
    if (last - first).days + 1 > MAX_DAYS:
        raise ValueError("date range exceeds 3660 natural days")
    if type(offset) is not int or not 0 <= offset <= MAX_OFFSET:
        raise TypeError("offset must be an integer from 0 to 20000")
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise TypeError("limit must be an integer from 1 to 20")
    supplied = Path(data_root)
    _reject_redirect_ancestors(supplied)
    root = _absolute_without_resolving(supplied)
    if not root.is_dir():
        raise ValueError("data_root must be an existing directory")
    return root, first, last


def _stat_identity(value) -> tuple:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _error(source: str, code: str, message: str, locator=None) -> dict:
    row = {"source": source, "code": code, "message": str(message)[:500]}
    if locator is not None:
        row["locator"] = locator
    return row


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return _dstr(value)
    raise TypeError(type(value).__name__)


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=_json_default)


def _strict_json(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON key: " + str(key))
            out[key] = value
        return out
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=lambda token: (_ for _ in ()).throw(ValueError("nonfinite JSON number: " + token)))
    if not isinstance(value, dict):
        raise ValueError("record_json must contain one object")
    return value


def _dstr(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _decimal(value, *, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise ValueError("numeric value is missing")
    if isinstance(value, bool):
        raise ValueError("boolean is not numeric")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError("invalid decimal value") from exc
    if not number.is_finite():
        raise ValueError("nonfinite numeric value")
    return number


def _source_file(symbol: str) -> str:
    return symbol.replace(".", "_")


class _ReadBudget:
    def __init__(self):
        self.bytes = 0


def _read_parquet(root: Path, relative: str, source: str, budget: _ReadBudget):
    """Parse the exact bytes hashed, then re-read and compare at final review."""
    path = _fixed_path(root, relative)
    evidence = {
        "status": "missing",
        "path": relative,
        "verification": "exact_parquet_bytes_parsed",
        "source_bytes_verified": False,
    }
    if not os.path.lexists(path):
        return None, evidence, []
    if _is_redirect(path) or not path.is_file():
        error = _error(source, "PATH_REJECTED", "fixed source is a link or not a regular file")
        evidence["status"] = "error"
        return None, evidence, [error]
    before = path.stat()
    if before.st_size > MAX_PARQUET_BYTES:
        evidence.update(status="error", bytes=before.st_size)
        return None, evidence, [_error(source, "SOURCE_BYTES_BUDGET_EXCEEDED", "Parquet exceeds per-file byte budget")]
    if budget.bytes + before.st_size > MAX_TOTAL_PARQUET_BYTES:
        evidence.update(status="error", bytes=before.st_size)
        return None, evidence, [_error(source, "TOTAL_SOURCE_BYTES_BUDGET_EXCEEDED", "Parquet reads exceed total byte budget")]
    try:
        payload = path.read_bytes()
        after_read = path.stat()
        if len(payload) != before.st_size or _stat_identity(before) != _stat_identity(after_read):
            raise ValueError("source changed while bytes were read")
        digest = hashlib.sha256(payload).hexdigest()
        metadata = pq.ParquetFile(BytesIO(payload)).metadata
        if metadata.num_rows > MAX_PARQUET_ROWS or metadata.num_columns > 64 or metadata.num_row_groups > 256:
            evidence.update(status="error", sha256=digest, bytes=len(payload))
            return None, evidence, [_error(source, "SOURCE_ROWS_BUDGET_EXCEEDED", "Parquet metadata exceeds decoding budget")]
        frame = pl.read_parquet(BytesIO(payload))
        # A final byte-for-byte review catches same-size replacement while parsing.
        final_payload = path.read_bytes()
        final_stat = path.stat()
        if _stat_identity(before) != _stat_identity(final_stat) or final_payload != payload:
            raise ValueError("source changed during parse/final review")
    except Exception as exc:
        evidence.update(status="error", bytes=before.st_size)
        if "payload" in locals():
            evidence["sha256"] = hashlib.sha256(payload).hexdigest()
        return None, evidence, [_error(source, "PARQUET_READ_FAILED", type(exc).__name__ + ": " + str(exc))]
    budget.bytes += len(payload)
    evidence.update(status="available", sha256=digest, bytes=len(payload), rows=frame.height,
                    source_bytes_verified=True)
    if frame.height > MAX_PARQUET_ROWS:
        evidence["status"] = "error"
        return None, evidence, [_error(source, "SOURCE_ROWS_BUDGET_EXCEEDED", "Parquet exceeds row budget")]
    return frame, evidence, []


def _source_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if text in ("", "--", "None", "NaT", "nan"):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError("source date is not an ISO date")
    return date.fromisoformat(text)


def _jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return _dstr(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite source value")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _implemented(value):
    if value is None:
        return False, "implementation_status_missing"
    text = re.sub(r"\s+", "", str(value))
    if any(word in text for word in ("未实施", "待实施", "不实施", "停止实施", "终止", "取消", "预案")):
        return False, "not_effective"
    if text in {'实施方案', '实施分配', '已实施', '实施'}:
        return True, "effective"
    return False, "implementation_status_unrecognized"


def _scheme_identity(row: dict, source: str):
    # Publication/registration dates can change when a plan is revised. They are
    # provenance, not independent scheme identities to be summed a second time.
    keys = ("方案标识", "方案ID", "报告期")
    identity = {}
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() not in ("", "None", "NaT", "nan", "--"):
            identity[key] = _jsonable(value)
    return identity or None


def _parse_plan_text(value) -> dict:
    """Parse only the deliberately small, whole-string grammar in the contract."""
    original = None if value is None else str(value)
    result = {
        "status": "unknown",
        "raw_text": original,
        "declared_base_shares": None,
        "normalized_base_shares": "10",
        "tax_basis": "unknown",
        "components": None,
        "blockers": [],
    }
    if original is None or not original.strip():
        result["blockers"] = ["empty_plan_text"]
        return result
    text = re.sub(r"\s+", "", original)
    text = text.replace("（", "(").replace("）", ")")
    compact = re.sub(r"[，,。；;]", "", text)
    if any(word in compact for word in ("待定", "未定", "未确定", "未公布", "未披露", "方案未知", "暂无")):
        result["blockers"] = ["pending_or_unknown_plan"]
        return result
    if any(word in compact for word in ("限售", "流通", "社会公众", "控股股东", "其他股东", "不同股东", "差异化")):
        result.update(status="blocked", blockers=["differentiated_or_holder_specific_plan"])
        return result
    no_distribution = {
        "不分配不转增", "不分配利润不转增股本", "本年度不分配不转增",
        "不送股不分配不转增", "不分配不送股不转增",
    }
    if compact in no_distribution:
        result.update(
            status="not_distributing",
            declared_base_shares="10",
            tax_basis="not_applicable",
            components={
                "cash_pre_tax_per_10_shares": "0",
                "stock_bonus_per_10_shares": "0",
                "capitalization_per_10_shares": "0",
                "stock_total_per_10_shares": "0",
            },
        )
        return result

    bases = []
    bases.extend(Decimal(m.group(1)) for m in re.finditer(r"每(\d+(?:\.\d+)?)股", compact))
    if "每股" in compact:
        bases.append(Decimal(1))
    if len(set(bases)) > 1:
        result.update(status="blocked", blockers=["multiple_share_bases"])
        return result

    rest = compact
    match = re.match(r"^每股", rest)
    if match:
        base = Decimal(1)
    else:
        match = re.match(r"^每(\d+(?:\.\d+)?)股", rest)
        if match:
            base = Decimal(match.group(1))
        else:
            match = re.match(r"^(\d+(?:\.\d+)?)(?:股)?", rest)
            if not match:
                result["blockers"] = ["unrecognized_base"]
                return result
            base = Decimal(match.group(1))
    if base <= 0:
        result.update(status="blocked", blockers=["invalid_share_base"])
        return result
    rest = rest[match.end():]
    values = {"cash": None, "song": None, "zhuan": None}
    tax_basis = "not_applicable"
    token_count = 0
    while rest:
        token = re.match(r"^送(\d+(?:\.\d+)?)(?:股)?", rest)
        kind = "song"
        if token is None:
            token = re.match(r"^转(?:增)?(\d+(?:\.\d+)?)(?:股)?", rest)
            kind = "zhuan"
        if token is None:
            token = re.match(r"^派(\d+(?:\.\d+)?)元(?:\((含税|税前|税后)\))?", rest)
            kind = "cash"
        if token is None:
            result.update(status="unknown", declared_base_shares=_dstr(base),
                          blockers=["unrecognized_residual_syntax"])
            return result
        if values[kind] is not None:
            result.update(status="blocked", declared_base_shares=_dstr(base),
                          blockers=["repeated_component_clause"])
            return result
        values[kind] = Decimal(token.group(1))
        if kind == "cash":
            marker = token.group(2)
            tax_basis = "pre_tax" if marker in ("含税", "税前") else "after_tax" if marker == "税后" else "unspecified"
        token_count += 1
        rest = rest[token.end():]
    if token_count == 0:
        result["blockers"] = ["no_supported_component"]
        return result
    scale = Decimal(10) / base
    cash = (values["cash"] or Decimal(0)) * scale
    song = (values["song"] or Decimal(0)) * scale
    zhuan = (values["zhuan"] or Decimal(0)) * scale
    components = {
        "cash_pre_tax_per_10_shares": _dstr(cash) if tax_basis == "pre_tax" or values["cash"] is None else None,
        "stock_bonus_per_10_shares": _dstr(song),
        "capitalization_per_10_shares": _dstr(zhuan),
        "stock_total_per_10_shares": _dstr(song + zhuan),
    }
    blockers = []
    if values["cash"] is not None and tax_basis == "unspecified":
        blockers.append("cash_tax_basis_unspecified")
    if tax_basis == "after_tax":
        blockers.append("after_tax_cash_not_comparable")
    result.update(
        status="blocked" if blockers else "parsed",
        declared_base_shares=_dstr(base),
        tax_basis=tax_basis,
        components=components,
        blockers=blockers,
    )
    return result


def _locator(source: str, path: str, index: int, **extra):
    value = {"source": source, "path": path, "row_index": index}
    value.update(extra)
    return value


def _base_observation(source, locator, status, raw, identity=None):
    return {
        "source": source,
        "locator": locator,
        "observation_status": status,
        "scheme_identity": identity,
        "raw": raw,
        "candidate": None,
        "blockers": [],
    }


def _check_row_symbol(row: dict, symbol: str):
    if "code" in row and row["code"] is not None and str(row["code"]).strip() not in ("", symbol):
        raise ValueError("source row symbol mismatch")


def _parquet_observations(frame, source, relative, symbol, first, last):
    observations = defaultdict(list)
    errors = []
    unassigned = []
    required = (
        ("A股除权除息日", "方案进度", "分红方案说明")
        if source == "ths" else
        ("除权除息日", "方案进度", "现金分红-现金分红比例", "送转股份-送转总比例")
    )
    missing = [name for name in required if name not in frame.columns]
    if missing:
        return observations, unassigned, [_error(source, "SOURCE_SCHEMA_INVALID", "missing columns: " + ", ".join(missing))]
    for index, row in enumerate(frame.to_dicts()):
        locator = _locator(source, relative, index)
        try:
            _check_row_symbol(row, symbol)
            status_value = row.get("方案进度")
            effective, status = _implemented(status_value)
            date_key = "A股除权除息日" if source == "ths" else "除权除息日"
            exdate = _source_date(row.get(date_key))
            raw = {"implementation_status": _jsonable(status_value), "ex_date": exdate.isoformat() if exdate else None}
            if source == "ths":
                raw.update(plan_text=_jsonable(row.get("分红方案说明")), report_period=_jsonable(row.get("报告期")))
            else:
                raw.update(cash_ratio=_jsonable(row.get("现金分红-现金分红比例")),
                           stock_total_ratio=_jsonable(row.get("送转股份-送转总比例")))
            raw['scheme_metadata'] = {key: _jsonable(row.get(key)) for key in
                ('方案标识', '方案ID', '报告期', '实施公告日', '公告日期', 'A股股权登记日', '股权登记日') if key in row}
            identity = _scheme_identity(row, source)
            obs = _base_observation(source, locator, "effective" if effective else "not_effective", raw, identity)
            if exdate is None:
                if effective:
                    raise ValueError("effective row has no ex-date")
                obs["blockers"] = [status]
                if len(unassigned) < MAX_LIMIT:
                    unassigned.append(obs)
                elif not any(error['code'] == 'UNASSIGNED_OBSERVATIONS_LIMIT' for error in errors):
                    errors.append(_error(source, 'UNASSIGNED_OBSERVATIONS_LIMIT',
                        'unassigned non-effective observations exceed preview limit; remaining rows are not displayed'))
                continue
            if exdate < first or exdate > last:
                continue
            if not effective:
                obs["blockers"] = [status]
                observations[exdate].append(obs)
                continue
            if source == "ths":
                parsed = _parse_plan_text(row.get("分红方案说明"))
                obs["parse"] = parsed
                obs["blockers"] = list(parsed["blockers"])
                if parsed["status"] in ("parsed", "not_distributing"):
                    obs["candidate"] = {
                        "base_shares": "10",
                        "declared_base_shares": parsed["declared_base_shares"],
                        "tax_basis": parsed["tax_basis"],
                        "components": parsed["components"],
                        "slot_authority": "explicit_limited_text_parse",
                    }
            else:
                cash_raw = row.get("现金分红-现金分红比例")
                stock_raw = row.get("送转股份-送转总比例")
                cash = _decimal(cash_raw, allow_none=True)
                stock = _decimal(stock_raw, allow_none=True)
                if any(value is not None and value < 0 for value in (cash, stock)):
                    raise ValueError("negative corporate-action component")
                # The fixed EM field does not itself declare tax basis. Preserve
                # values for review, but never invent zero or normalize to pre-tax.
                obs['provider_component_candidates'] = {
                    'cash_ratio': _dstr(cash) if cash is not None else None,
                    'stock_total_ratio': _dstr(stock) if stock is not None else None,
                    'tax_basis': 'unspecified', 'unit_basis': 'per_10_source_field_candidate',
                }
                obs['blockers'] = ['cash_tax_basis_unspecified']
                if cash is None: obs['blockers'].append('cash_component_missing')
                if stock is None: obs['blockers'].append('stock_component_missing')
            observations[exdate].append(obs)
        except Exception as exc:
            errors.append(_error(source, "SOURCE_ROW_INVALID", type(exc).__name__ + ": " + str(exc), locator))
    return observations, unassigned, errors


def _read_tdx(root, symbol, first, last):
    relative = _PATHS["tdx"]
    path = _fixed_path(root, relative)
    evidence = {
        "status": "missing",
        "path": relative,
        "verification": "catalog_rows_only",
        "source_bytes_verified": False,
        "source_page_bytes_verified": False,
    }
    if not os.path.lexists(path):
        return defaultdict(list), evidence, []
    if _is_redirect(path) or not path.is_file():
        evidence["status"] = "error"
        return defaultdict(list), evidence, [_error("tdx", "PATH_REJECTED", "catalog is a link or not a regular file")]
    before = path.stat()
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            rows = con.execute(
                "SELECT date, code, event_time, observed_at, record_json, source_id, record_index "
                "FROM tdx_capital_changes WHERE code = ? AND date >= ?::DATE AND date <= ?::DATE "
                "ORDER BY date, source_id, record_index LIMIT ?",
                [symbol, first.isoformat(), last.isoformat(), MAX_TDX_ROWS + 1],
            ).fetchall()
            columns = [item[0] for item in con.description]
        after = path.stat()
        if _stat_identity(before) != _stat_identity(after):
            raise ValueError("catalog changed during query")
    except Exception as exc:
        evidence["status"] = "error"
        return defaultdict(list), evidence, [_error("tdx", "CATALOG_READ_FAILED", type(exc).__name__ + ": " + str(exc))]
    evidence.update(status="available", rows_read=len(rows),
                    catalog_file_identity=list(_stat_identity(before)))
    if len(rows) > MAX_TDX_ROWS:
        evidence["status"] = "error"
        return defaultdict(list), evidence, [_error("tdx", "TDX_ROWS_BUDGET_EXCEEDED", "fixed MAX+1 query exceeded row budget")]
    observations = defaultdict(list)
    errors = []
    for index, values in enumerate(rows):
        row = dict(zip(columns, values))
        locator = {
            "source": "tdx",
            "path": relative,
            "source_id": _jsonable(row.get("source_id")),
            "record_index": _jsonable(row.get("record_index")),
            "observed_at": _jsonable(row.get("observed_at")),
        }
        try:
            exdate = _source_date(row.get("date"))
            if exdate is None:
                raise ValueError("TDX row has no event date")
            if row.get("code") != symbol:
                raise ValueError("TDX row symbol mismatch")
            record = _strict_json(row.get("record_json"))
            code = str(record.get("code", ""))
            exchange = str(record.get("exchange", ""))
            if code and (code != symbol.split(".")[1] or exchange and exchange != symbol.split(".")[0]):
                raise ValueError("record_json symbol mismatch")
            original_date = _source_date(record.get("date"))
            if original_date is not None and original_date != exdate:
                raise ValueError("record_json date mismatch")
            category = record.get("category_name") or record.get("category_raw")
            obs = _base_observation(
                "tdx", locator,
                "effective" if category == "除权除息" else "unsupported",
                {"category": _jsonable(category), "record_json": _jsonable(record)},
                None,
            )
            if category != "除权除息":
                obs["blockers"] = ["unsupported_tdx_category"]
                observations[exdate].append(obs)
                continue
            components = {}
            for key, output_key in (
                ("c1_float", "cash_pre_tax_per_10_shares"),
                ("c2_float", "rights_price_per_share"),
                ("c3_float", "stock_total_per_10_shares"),
                ("c4_float", "rights_per_10_shares"),
            ):
                number = _decimal(record.get(key))
                if number < 0:
                    raise ValueError("negative TDX slot candidate")
                components[output_key] = _dstr(number)
            components.update(stock_bonus_per_10_shares=None, capitalization_per_10_shares=None)
            obs["candidate"] = {
                "base_shares": "10",
                "declared_base_shares": "10",
                "tax_basis": "pre_tax_statistically_inferred_candidate",
                "components": components,
                "slot_authority": "statistically_inferred_slot",
            }
            observations[exdate].append(obs)
        except Exception as exc:
            errors.append(_error("tdx", "TDX_ROW_INVALID", type(exc).__name__ + ": " + str(exc), locator))
    if errors:
        evidence["status"] = "partial"
    return observations, evidence, errors


def _candidate_signature(obs):
    candidate = obs["candidate"]
    return _canonical({"candidate": candidate, "identity": obs.get("scheme_identity"),
                       "text": obs.get("raw", {}).get("plan_text")})


def _component_values(candidate):
    values = candidate["components"]
    return {
        "cash_pre_tax_per_10_shares": _decimal(values["cash_pre_tax_per_10_shares"]),
        "stock_total_per_10_shares": _decimal(values["stock_total_per_10_shares"]),
    }


def _aggregate_source(source, observations):
    result = {
        "status": "observed" if observations else "no_observation",
        "observations": observations,
        "candidate_components": [],
        "candidate_total": None,
        "blockers": [],
    }
    if len(observations) > MAX_EVENT_SOURCE_OBSERVATIONS:
        result["observations"] = []
        result["status"] = "blocked"
        result["blockers"] = ["event_source_observations_budget_exceeded"]
        return result
    blocked = sorted({blocker for obs in observations if obs["observation_status"] == "effective" for blocker in obs.get("blockers", [])})
    candidates = [obs for obs in observations if obs.get("candidate") is not None and not obs.get("blockers")]
    groups = {}
    for obs in candidates:
        signature = _candidate_signature(obs)
        groups.setdefault(signature, {"observation": obs, "locators": []})["locators"].append(obs["locator"])
    unique = list(groups.values())
    for group in unique:
        obs = group["observation"]
        result["candidate_components"].append({
            "scheme_identity": obs.get("scheme_identity"),
            "raw_text": obs.get("raw", {}).get("plan_text"),
            "candidate": obs["candidate"],
            "locators": group["locators"],
            "candidate_only": True,
        })
    if blocked:
        result["blockers"].extend(blocked)
    if source == "tdx" and len(unique) > 1:
        candidate_only = {_canonical(group["observation"]["candidate"]) for group in unique}
        if len(candidate_only) > 1:
            result["blockers"].append("tdx_unresolved_duplicate_or_version_conflict")
        else:
            # Same candidate repeated with differing raw metadata is still a duplicate,
            # never a second distributable scheme.
            first = unique[0]
            first["locators"].extend(locator for group in unique[1:] for locator in group["locators"])
            unique = [first]
            result["candidate_components"] = result["candidate_components"][:1]
            result["candidate_components"][0]["locators"] = first["locators"]
    elif len(unique) > 1:
        identities = [group["observation"].get("scheme_identity") for group in unique]
        if any(identity is None for identity in identities):
            result["blockers"].append("multiple_plans_without_distinguishing_identity")
        elif len({_canonical(identity) for identity in identities}) != len(identities):
            result["blockers"].append("same_identity_has_conflicting_versions")
        else:
            texts = [group["observation"].get("raw", {}).get("plan_text") for group in unique]
            nonempty = [text for text in texts if text]
            if len(nonempty) != len(set(nonempty)):
                result["blockers"].append("same_text_has_different_scheme_identities")
    result["blockers"] = sorted(set(result["blockers"]))
    if result["blockers"]:
        result["status"] = "blocked"
        return result
    if not unique:
        if observations:
            result["blockers"] = ["no_effective_comparable_candidate"]
        return result
    totals = {"cash_pre_tax_per_10_shares": Decimal(0), "stock_total_per_10_shares": Decimal(0)}
    for group in unique:
        values = _component_values(group["observation"]["candidate"])
        for key in totals:
            totals[key] += values[key]
    first_candidate = unique[0]["observation"]["candidate"]
    simple = True
    if source == "tdx":
        extra = first_candidate["components"]
        simple = _decimal(extra["rights_price_per_share"]) == 0 and _decimal(extra["rights_per_10_shares"]) == 0
    result["candidate_total"] = {
        "base_shares": "10",
        "tax_basis": "pre_tax_candidate",
        "cash_pre_tax_per_10_shares": _dstr(totals["cash_pre_tax_per_10_shares"]),
        "stock_total_per_10_shares": _dstr(totals["stock_total_per_10_shares"]),
        "component_count": len(unique),
        "aggregation_scope": "within_source_only",
        "candidate_only": True,
        "simple_comparable": simple,
    }
    if len(unique) > 1:
        result["candidate_total"]["distinct_scheme_aggregation"] = True
    return result


def _qfq_index(frame, evidence, errors, symbol):
    if frame is None:
        return None
    missing = [key for key in ("date", "factor") if key not in frame.columns]
    if missing:
        evidence["status"] = "error"
        errors.append(_error("qfq", "SOURCE_SCHEMA_INVALID", "missing columns: " + ", ".join(missing)))
        return None
    if 'code' not in frame.columns or frame.filter(pl.col('code').is_null() | (pl.col('code') != symbol)).height:
        evidence['status'] = 'error'
        errors.append(_error('qfq', 'SOURCE_SYMBOL_MISMATCH', 'qfq source must match the requested code on every row'))
        return None
    values = defaultdict(list)
    for index, row in enumerate(frame.select("date", "factor").to_dicts()):
        locator = _locator("qfq", evidence["path"], index)
        try:
            day = _source_date(row["date"])
            if day is None:
                raise ValueError("qfq date missing")
            factor = _decimal(row["factor"])
            if factor <= 0:
                raise ValueError("qfq factor must be finite and positive")
            values[day].append((factor, locator))
        except Exception as exc:
            errors.append(_error("qfq", "QFQ_ROW_INVALID", type(exc).__name__ + ": " + str(exc), locator))
    if errors:
        evidence["status"] = "partial"
    return values


def _qfq_diagnostic(index, evidence, exdate):
    base = {
        "status": "unavailable",
        "diagnostic_only": True,
        "missing_adjustment_inferred": False,
        "completeness_certified": False,
        "corrected_factor": None,
        "corrected_prices": None,
    }
    if evidence["status"] == "missing":
        return {**base, "reason": "qfq_source_missing"}
    if evidence["status"] in ("error", "partial") or index is None:
        return {**base, "status": "blocked", "reason": "qfq_source_invalid_or_incomplete"}
    rows = index.get(exdate, [])
    if not rows:
        return {**base, "reason": "factor_missing_for_event_date"}
    distinct = {factor for factor, _ in rows}
    if len(distinct) != 1:
        return {**base, "status": "blocked", "reason": "conflicting_factors_on_event_date",
                "locators": [locator for _, locator in rows]}
    prior_days = [day for day in index if day < exdate]
    if not prior_days:
        return {**base, "reason": "previous_factor_missing"}
    previous_date = max(prior_days)
    previous_rows = index[previous_date]
    previous_distinct = {factor for factor, _ in previous_rows}
    if len(previous_distinct) != 1:
        return {**base, "status": "blocked", "reason": "conflicting_previous_factors",
                "previous_date": previous_date.isoformat()}
    current = next(iter(distinct))
    previous = next(iter(previous_distinct))
    with localcontext() as context:
        context.prec = 34
        ratio = current / previous
    direction = "increase" if current > previous else "decrease" if current < previous else "unchanged"
    return {
        **base,
        "status": "available",
        "event_date": exdate.isoformat(),
        "previous_stored_date": previous_date.isoformat(),
        "factor": _dstr(current),
        "previous_factor": _dstr(previous),
        "factor_ratio": _dstr(ratio),
        "factor_change_direction": direction,
        "locators": [locator for _, locator in rows],
        "previous_locators": [locator for _, locator in previous_rows],
        "interpretation": "stored_factor_change_only_no_underadjustment_or_completeness_inference",
    }


def _comparison(source_results, globally_blocked):
    comparable = {}
    for source, result in source_results.items():
        total = result.get("candidate_total")
        if total and total.get("simple_comparable"):
            comparable[source] = total
    if globally_blocked or any(result.get("status") == "blocked" for result in source_results.values()):
        return {"status": "blocked", "comparable_sources": sorted(comparable),
                "component_disagreements": [], "adjudication": None}
    if len(comparable) < 2:
        return {"status": "insufficient", "comparable_sources": sorted(comparable),
                "component_disagreements": [], "adjudication": None}
    disagreements = []
    for component in ("cash_pre_tax_per_10_shares", "stock_total_per_10_shares"):
        values = {source: total[component] for source, total in sorted(comparable.items())}
        if len(set(values.values())) > 1:
            disagreements.append({"component": component, "candidate_values": values,
                                  "wrong_source_determined": False})
    return {
        "status": "disagreement" if disagreements else "agreement",
        "comparable_sources": sorted(comparable),
        "component_disagreements": disagreements,
        "adjudication": None,
        "agreement_is_not_official_verification": True,
    }


def _source_event_status(source, source_result, evidence):
    if evidence["status"] in ("error", "partial"):
        source_result["status"] = "blocked"
        source_result["blockers"] = sorted(set(source_result.get("blockers", []) + ["source_invalid_or_incomplete"]))
    elif evidence["status"] == "missing":
        source_result = {
            "status": "missing", "observations": [], "candidate_components": [],
            "candidate_total": None, "blockers": ["source_missing"],
        }
    return source_result


def _risk_codes(source_results, evidences, comparison, qfq):
    risks = {"candidate_not_adjudicated", "official_not_verified", "lineage_not_verified"}
    for source, evidence in evidences.items():
        if evidence["status"] == "missing":
            risks.add(source + "_source_missing")
        elif evidence["status"] in ("error", "partial"):
            risks.add(source + "_source_invalid_or_incomplete")
    if source_results["tdx"].get("candidate_total"):
        risks.add("tdx_statistically_inferred_slots")
    if any(any(obs.get("observation_status") == "not_effective" for obs in result.get("observations", []))
           for result in source_results.values()):
        risks.add("not_effective_observation_excluded")
    if any((result.get("candidate_total") or {}).get("distinct_scheme_aggregation") for result in source_results.values()):
        risks.add("within_source_distinct_scheme_candidate_aggregation")
    if comparison["status"] == "disagreement":
        risks.add("component_disagreement_not_adjudicated")
    if comparison["status"] == "blocked":
        risks.add("comparison_blocked")
    if qfq["status"] != "available":
        risks.add("qfq_diagnostic_" + qfq["status"])
    elif qfq["factor_change_direction"] == "unchanged":
        risks.add("unchanged_factor_does_not_certify_completeness")
    else:
        risks.add("factor_change_does_not_adjudicate_corporate_action")
    return sorted(risks)


def _bounded_failure(base, code, message):
    return {
        **base,
        "events": [],
        "pagination": {**base["pagination"], "returned": 0, "next_offset": None},
        "errors": base["errors"] + [_error("output", code, message)],
        "incomplete": True,
        "data_changed": False,
    }


def inspect_corporate_action_sources(data_root, symbol, start, end, offset=0, limit=20) -> dict:
    """Inspect one bounded symbol/date range without writing or adjudicating evidence."""
    root, first, last = _validate_inputs(data_root, symbol, start, end, offset, limit)
    file_name = _source_file(symbol)
    errors = []
    budget = _ReadBudget()

    tdx_observations, tdx_evidence, tdx_errors = _read_tdx(root, symbol, first, last)
    errors.extend(tdx_errors)

    observations_by_source = {"tdx": tdx_observations}
    unassigned = {}
    evidences = {"tdx": tdx_evidence}
    for source in ("eastmoney", "ths"):
        relative = _PATHS[source].format(file=file_name)
        frame, evidence, source_errors = _read_parquet(root, relative, source, budget)
        source_observations = defaultdict(list)
        source_unassigned = []
        if frame is not None:
            source_observations, source_unassigned, row_errors = _parquet_observations(
                frame, source, relative, symbol, first, last
            )
            source_errors.extend(row_errors)
            if row_errors:
                evidence["status"] = "partial"
        observations_by_source[source] = source_observations
        unassigned[source] = source_unassigned
        evidences[source] = evidence
        errors.extend(source_errors)

    qfq_relative = _PATHS["qfq"].format(file=file_name)
    qfq_frame, qfq_evidence, qfq_errors = _read_parquet(root, qfq_relative, "qfq", budget)
    qfq_index = _qfq_index(qfq_frame, qfq_evidence, qfq_errors, symbol)
    evidences["qfq"] = qfq_evidence
    errors.extend(qfq_errors)
    # Sources are read sequentially. Recheck earlier bytes after all reads so a
    # change during a later source read cannot silently create a mixed revision.
    for source, evidence in evidences.items():
        if source == 'tdx':
            if evidence.get('status') == 'available':
                try:
                    path = _fixed_path(root, evidence['path'])
                    if list(_stat_identity(path.stat())) != evidence['catalog_file_identity']:
                        raise ValueError('catalog changed during cross-source review')
                except Exception as exc:
                    evidence['status'] = 'error'
                    errors.append(_error(source, 'SOURCE_CHANGED', str(exc)))
            continue
        if not evidence.get('source_bytes_verified'):
            continue
        try:
            path = _fixed_path(root, evidence['path'])
            with path.open('rb') as stream:
                payload = stream.read(MAX_PARQUET_BYTES + 1)
            if len(payload) != evidence['bytes'] or hashlib.sha256(payload).hexdigest() != evidence['sha256']:
                raise ValueError('source changed during cross-source review')
        except Exception as exc:
            evidence['status'] = 'error'
            evidence['source_bytes_verified'] = False
            errors.append(_error(source, 'SOURCE_CHANGED', str(exc)))

    event_dates = sorted(set().union(*(set(rows) for rows in observations_by_source.values())))
    total_events = len(event_dates)
    selected_dates = event_dates[offset:offset + limit]
    events = []
    source_globally_blocked = {
        source for source in ("tdx", "eastmoney", "ths")
        if evidences[source]["status"] in ("error", "partial")
    }
    for exdate in selected_dates:
        source_results = {}
        for source in ("tdx", "eastmoney", "ths"):
            result = _aggregate_source(source, observations_by_source[source].get(exdate, []))
            source_results[source] = _source_event_status(source, result, evidences[source])
        comparison = _comparison(source_results, bool(source_globally_blocked))
        diagnostic = _qfq_diagnostic(qfq_index, qfq_evidence, exdate)
        events.append({
            "code": symbol,
            "exdate": exdate.isoformat(),
            "source_observations": source_results,
            "comparison": comparison,
            "qfq_diagnostic": diagnostic,
            "risk_codes": _risk_codes(source_results, evidences, comparison, diagnostic),
            "authority": "candidate_not_adjudicated",
            "official_verified": False,
            "lineage_verified": False,
            "reconstruction_authorized": False,
            "known_issue_list_status": "not_bound",
            "data_changed": False,
        })

    next_offset = offset + len(events) if offset + len(events) < total_events else None
    base = {
        "contract_version": CONTRACT_VERSION,
        "query": {"symbol": symbol, "start": start, "end": end, "offset": offset, "limit": limit},
        "events": events,
        "pagination": {"offset": offset, "limit": limit, "returned": len(events),
                       "total_events": total_events, "next_offset": next_offset},
        "sources": evidences,
        "evidence": [{'kind': 'corporate_action_source', 'source': source, **evidence}
                     for source, evidence in sorted(evidences.items())],
        "unassigned_not_effective_observations": unassigned,
        "errors": errors,
        "incomplete": bool(errors) or any(evidence["status"] in ("missing", "error", "partial")
                                          for source, evidence in evidences.items() if source != "qfq")
                      or any(event['comparison']['status'] == 'blocked' for event in events),
        "known_issue_list_status": "not_bound",
        "authority": "candidate_not_adjudicated",
        "official_verified": False,
        "lineage_verified": False,
        "reconstruction_authorized": False,
        "corrected_prices": None,
        "replacement_factor": None,
        "data_changed": False,
    }
    try:
        encoded = _canonical(base).encode("utf-8")
    except Exception as exc:
        return _bounded_failure(base, "NON_JSON_OUTPUT", type(exc).__name__ + ": " + str(exc))
    if len(encoded) > MAX_OUTPUT_BYTES:
        return _bounded_failure(base, "OUTPUT_BUDGET_EXCEEDED", "encoded response exceeds output byte budget")
    return json.loads(encoded.decode("utf-8"))


__all__ = ["get_adjustment_review_contract", "inspect_corporate_action_sources"]
