"""F21 generic observation/revision/event version ledger.

The ledger is deliberately source-neutral.  It describes *what was observed when*
without deciding which provider is true, merging providers, or authorizing a data
rebuild.  Host code pins the ledger by exact file bytes and full SHA-256 values.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import hashlib
import json
import math
import os
import re

from quantlab.storage.codec import digest

LEDGER_FORMAT = "niuniu-observation-version-ledger-v1"
SELECTION_CONTRACT = "niuniu-version-selection-preview-v1"
POLICIES = ("explicit_revision_v1", "latest_observed_revision_as_of_v1")
MAX_JSONL_BYTES = 4 * 1024 * 1024
MAX_SUMMARY_BYTES = 64 * 1024
MAX_ROWS = 5000
MAX_LINE_BYTES = 128 * 1024
MAX_STRING = 20000
MAX_ARRAY = 512
MAX_OBJECT = 256
MAX_DEPTH = 10
HASH = re.compile(r"^[a-f0-9]{64}$")
ROW_FIELDS = {
    "domain", "event_type", "event_key", "event_id", "source_id",
    "source_revision_key", "revision_id", "observation_id", "content_hash",
    "observed_at", "published_at", "effective_at", "supersedes_revision_id", "payload",
}
SUMMARY_FIELDS = {
    "format", "source_of_truth", "summarises_jsonl_sha256", "records",
    "events", "revisions", "sources", "deterministic", "selection_policies",
    "limitations",
}
LIMITATIONS = [
    "版本账本只描述事件、来源修订、内容和观察时点，不认证任何来源为官方真值。",
    "跨来源默认完全独立；本合同不合并、不求和、不投票，也不选择更有利的数据。",
    "latest_observed_revision_as_of_v1 是显式的观察时点选择策略，不等于历史发布时点/PIT已认证。",
    "ready_for_review 只表示所选来源的版本在该合同内唯一，不授权重建、发布、交易或覆盖正式数据。",
]


class VersionLedgerError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _fail(message: str, code: str = "INVALID_VERSION_LEDGER"):
    raise VersionLedgerError(code, message)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_event_id(domain: str, event_type: str, event_key: dict) -> str:
    if type(domain) is not str or not domain or len(domain) > 80:
        _fail("domain must be a non-empty bounded string")
    if type(event_type) is not str or not event_type or len(event_type) > 80:
        _fail("event_type must be a non-empty bounded string")
    if type(event_key) is not dict or not event_key:
        _fail("event_key must be a non-empty object")
    _safe_json(event_key)
    return digest({"domain": domain, "event_type": event_type, "event_key": event_key})


def canonical_revision_id(event_id: str, source_id: str, source_revision_key: str) -> str:
    if not isinstance(event_id, str) or HASH.fullmatch(event_id) is None:
        _fail("event_id must be a full lowercase digest")
    if type(source_id) is not str or not source_id or len(source_id) > 200:
        _fail("source_id must be a non-empty bounded string")
    if type(source_revision_key) is not str or not source_revision_key or len(source_revision_key) > 500:
        _fail("source_revision_key must be a non-empty bounded string")
    return digest({"event_id": event_id, "source_id": source_id, "source_revision_key": source_revision_key})


def canonical_content_hash(payload) -> str:
    _safe_json(payload)
    return digest(payload)


def canonical_observation_id(revision_id: str, observed_at: str, content_hash: str) -> str:
    if not isinstance(revision_id, str) or HASH.fullmatch(revision_id) is None:
        _fail("revision_id must be a full lowercase digest")
    observed_at = _aware_iso(observed_at, "observed_at")
    if not isinstance(content_hash, str) or HASH.fullmatch(content_hash) is None:
        _fail("content_hash must be a full lowercase digest")
    return digest({"revision_id": revision_id, "observed_at": observed_at, "content_hash": content_hash})


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _fail("duplicate JSON key")
        result[key] = value
    return result


def _safe_json(value, depth=0):
    if depth > MAX_DEPTH:
        _fail("JSON nesting exceeds budget")
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        if len(value) > MAX_STRING or "\x00" in value:
            _fail("JSON string exceeds budget or contains NUL")
        return
    if type(value) is int:
        if abs(value) > 10**30:
            _fail("JSON integer exceeds budget")
        return
    if type(value) is float:
        if not math.isfinite(value) or abs(value) > 1e30:
            _fail("JSON number is non-finite or exceeds budget")
        return
    if type(value) is list:
        if len(value) > MAX_ARRAY:
            _fail("JSON array exceeds budget")
        for item in value:
            _safe_json(item, depth + 1)
        return
    if type(value) is dict:
        if len(value) > MAX_OBJECT:
            _fail("JSON object exceeds budget")
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 300:
                _fail("JSON object key is invalid")
            _safe_json(item, depth + 1)
        return
    _fail("unsupported JSON value type")


def _aware_iso(value: str, label: str) -> str:
    if type(value) is not str or not value:
        _fail(label + " must be a canonical timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise VersionLedgerError("INVALID_VERSION_LEDGER", label + " is not ISO8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.isoformat() != value:
        _fail(label + " must be canonical and timezone-aware")
    return value


def _effective(value: str) -> str:
    if type(value) is not str or not value:
        _fail("effective_at must be a canonical date or aware timestamp")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            if date.fromisoformat(value).isoformat() != value:
                _fail("effective_at date is not canonical")
        except ValueError as exc:
            raise VersionLedgerError("INVALID_VERSION_LEDGER", "effective_at date is invalid") from exc
        return value
    return _aware_iso(value, "effective_at")


def _path_no_symlink(path: Path) -> Path:
    p = Path(path).expanduser().absolute()
    allowed_system_aliases = {Path("/tmp"), Path("/var")}
    current = Path(p.anchor)
    for part in p.parts[1:]:
        current = current / part
        try:
            if current.is_symlink() and current not in allowed_system_aliases:
                _fail("ledger path contains a symlink", "PATH_REJECTED")
        except OSError as exc:
            raise VersionLedgerError("READ_FAILED", "cannot inspect ledger path") from exc
    return p


def _read_pinned(path: Path, expected_sha: str, max_bytes: int) -> bytes:
    if type(expected_sha) is not str or HASH.fullmatch(expected_sha) is None:
        _fail("host must provide full lowercase SHA-256", "INVALID_VERSION_BINDING")
    path = _path_no_symlink(path)
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise VersionLedgerError("NOT_FOUND", "version ledger file not found") from exc
    if not path.is_file() or stat.st_size > max_bytes:
        _fail("version ledger file type/size is invalid")
    payload = path.read_bytes()
    if len(payload) != stat.st_size or _sha(payload) != expected_sha:
        _fail("version ledger file SHA-256 mismatch", "VERSION_LEDGER_HASH_MISMATCH")
    return payload


@dataclass(frozen=True)
class VersionLedgerBinding:
    jsonl_path: Path
    summary_path: Path
    jsonl_sha256: str
    summary_sha256: str

    def __post_init__(self):
        for name in ("jsonl_sha256", "summary_sha256"):
            if type(getattr(self, name)) is not str or HASH.fullmatch(getattr(self, name)) is None:
                _fail("host must bind full lowercase hashes", "INVALID_VERSION_BINDING")
        object.__setattr__(self, "jsonl_path", Path(self.jsonl_path))
        object.__setattr__(self, "summary_path", Path(self.summary_path))
        if self.jsonl_path == self.summary_path:
            _fail("ledger JSONL and summary must differ", "INVALID_VERSION_BINDING")

    @property
    def bundle_id(self) -> str:
        return digest({"format": LEDGER_FORMAT, "jsonl_sha256": self.jsonl_sha256,
                       "summary_sha256": self.summary_sha256})


def add_version_ledger_binding_arguments(parser, *, required=False):
    parser.add_argument("--version-ledger-jsonl", required=required)
    parser.add_argument("--version-ledger-summary", required=required)
    parser.add_argument("--version-ledger-jsonl-sha256", required=required)
    parser.add_argument("--version-ledger-summary-sha256", required=required)


def version_ledger_binding_from_arguments(args):
    names = ("version_ledger_jsonl", "version_ledger_summary",
             "version_ledger_jsonl_sha256", "version_ledger_summary_sha256")
    values = [getattr(args, name, None) for name in names]
    if not any(v is not None for v in values):
        return None
    if not all(v is not None for v in values):
        _fail("all four version-ledger host binding options are required together",
              "INVALID_VERSION_BINDING")
    return VersionLedgerBinding(*values)


def _parse_json(payload: bytes):
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: _fail("non-finite JSON constant"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise VersionLedgerError("INVALID_VERSION_LEDGER", "malformed ledger JSON") from exc
    _safe_json(value)
    return value


def _row_identity(row: dict):
    if type(row) is not dict or set(row) != ROW_FIELDS:
        _fail("observation row field contract mismatch")
    for key in ("domain", "event_type", "source_id", "source_revision_key"):
        if type(row[key]) is not str or not row[key]:
            _fail(key + " must be non-empty")
    observed = _aware_iso(row["observed_at"], "observed_at")
    published = row["published_at"]
    if published is not None:
        published = _aware_iso(published, "published_at")
        if datetime.fromisoformat(published) > datetime.fromisoformat(observed):
            _fail("published_at cannot be after observed_at")
    _effective(row["effective_at"])
    expected_event = canonical_event_id(row["domain"], row["event_type"], row["event_key"])
    if row["event_id"] != expected_event:
        _fail("event_id does not match domain/event_type/event_key")
    expected_revision = canonical_revision_id(expected_event, row["source_id"], row["source_revision_key"])
    if row["revision_id"] != expected_revision:
        _fail("revision_id does not match event/source/revision key")
    expected_content = canonical_content_hash(row["payload"])
    if row["content_hash"] != expected_content:
        _fail("content_hash does not match payload")
    expected_observation = canonical_observation_id(expected_revision, observed, expected_content)
    if row["observation_id"] != expected_observation:
        _fail("observation_id does not match revision/observed_at/content")
    supersedes = row["supersedes_revision_id"]
    if supersedes is not None and (type(supersedes) is not str or HASH.fullmatch(supersedes) is None):
        _fail("supersedes_revision_id must be null or a full lowercase digest")
    return row


def _parse_jsonl(payload: bytes):
    rows = []
    if not payload:
        _fail("ledger JSONL is empty")
    for line_no, raw in enumerate(payload.splitlines(keepends=True), 1):
        if len(rows) >= MAX_ROWS:
            _fail("ledger row count exceeds budget")
        if not raw.strip() or len(raw) > MAX_LINE_BYTES:
            _fail("ledger JSONL contains blank/oversized line")
        row = _row_identity(_parse_json(raw))
        rows.append({"line": line_no, "row": row})
    return rows


def build_version_ledger_summary(rows: list[dict], jsonl_sha256: str) -> dict:
    """Deterministic helper for data-side/tests; validates rows before summarising."""
    validated = [_row_identity(dict(row)) for row in rows]
    return {
        "format": LEDGER_FORMAT,
        "source_of_truth": "observations.jsonl",
        "summarises_jsonl_sha256": jsonl_sha256,
        "records": len(validated),
        "events": len({row["event_id"] for row in validated}),
        "revisions": len({row["revision_id"] for row in validated}),
        "sources": len({row["source_id"] for row in validated}),
        "deterministic": True,
        "selection_policies": list(POLICIES),
        "limitations": list(LIMITATIONS),
    }


def _revision_graph(records):
    by_revision = {}
    observations = defaultdict(list)
    for item in records:
        row = item["row"]
        revision = row["revision_id"]
        observations[revision].append(item)
        current = by_revision.get(revision)
        descriptor = {
            "revision_id": revision, "event_id": row["event_id"], "source_id": row["source_id"],
            "source_revision_key": row["source_revision_key"], "content_hash": row["content_hash"],
            "published_at": row["published_at"],
            "supersedes_revision_id": row["supersedes_revision_id"], "effective_at": row["effective_at"],
            "payload": row["payload"],
        }
        if current is None:
            by_revision[revision] = descriptor
        elif any(current[key] != descriptor[key] for key in descriptor):
            _fail("same revision_id has conflicting content or metadata")
    seen_observations = set()
    for item in records:
        oid = item["row"]["observation_id"]
        if oid in seen_observations:
            _fail("duplicate observation_id")
        seen_observations.add(oid)
    for revision, items in observations.items():
        items.sort(key=lambda item: datetime.fromisoformat(item["row"]["observed_at"]))
        by_revision[revision]["first_observed_at"] = items[0]["row"]["observed_at"]
        by_revision[revision]["last_observed_at"] = items[-1]["row"]["observed_at"]
        by_revision[revision]["observation_count"] = len(items)

    successors = defaultdict(list)
    for revision, info in by_revision.items():
        parent = info["supersedes_revision_id"]
        if parent is None:
            continue
        if parent == revision or parent not in by_revision:
            _fail("supersedes_revision_id is self/missing")
        prior = by_revision[parent]
        if prior["event_id"] != info["event_id"] or prior["source_id"] != info["source_id"]:
            _fail("supersedes_revision_id crosses event/source boundary")
        if datetime.fromisoformat(prior["first_observed_at"]) > datetime.fromisoformat(info["first_observed_at"]):
            _fail("revision first observation precedes superseded revision")
        successors[parent].append(revision)
        if len(successors[parent]) > 1:
            _fail("revision graph branches; explicit adjudication is required")

    # Cycle check even though first-observed monotonicity catches most malformed chains.
    for revision in by_revision:
        trail = set()
        current = revision
        while current is not None:
            if current in trail:
                _fail("revision graph contains a cycle")
            trail.add(current)
            current = by_revision[current]["supersedes_revision_id"]
    return by_revision, observations, successors


def _load(binding: VersionLedgerBinding | None):
    if binding is None:
        _fail("version ledger is not configured", "VERSION_LEDGER_NOT_CONFIGURED")
    if not isinstance(binding, VersionLedgerBinding):
        _fail("invalid version ledger binding", "INVALID_VERSION_BINDING")
    jsonl = _read_pinned(binding.jsonl_path, binding.jsonl_sha256, MAX_JSONL_BYTES)
    summary_bytes = _read_pinned(binding.summary_path, binding.summary_sha256, MAX_SUMMARY_BYTES)
    records = _parse_jsonl(jsonl)
    summary = _parse_json(summary_bytes)
    if type(summary) is not dict or set(summary) != SUMMARY_FIELDS:
        _fail("version ledger summary field contract mismatch")
    for name in ("records", "events", "revisions", "sources"):
        if type(summary[name]) is not int or type(summary[name]) is bool or summary[name] < 0:
            _fail("summary counter invalid: " + name)
    if summary["format"] != LEDGER_FORMAT or summary["deterministic"] is not True:
        _fail("summary format/deterministic contract mismatch")
    if summary["source_of_truth"] != "observations.jsonl":
        _fail("summary source_of_truth mismatch")
    if summary["summarises_jsonl_sha256"] != binding.jsonl_sha256:
        _fail("summary does not bind selected JSONL")
    if summary["selection_policies"] != list(POLICIES) or summary["limitations"] != list(LIMITATIONS):
        _fail("summary policy/limitations mismatch")
    expected = build_version_ledger_summary([item["row"] for item in records], binding.jsonl_sha256)
    if summary != expected:
        _fail("summary counts/content do not match JSONL")
    by_revision, observations, successors = _revision_graph(records)

    # Re-read to reject concurrent mutation.
    if _read_pinned(binding.jsonl_path, binding.jsonl_sha256, MAX_JSONL_BYTES) != jsonl or (
            _read_pinned(binding.summary_path, binding.summary_sha256, MAX_SUMMARY_BYTES) != summary_bytes):
        _fail("version ledger changed during validation", "VERSION_LEDGER_CHANGED")

    groups = defaultdict(list)
    for revision, info in by_revision.items():
        groups[(info["event_id"], info["source_id"])].append(revision)
    ambiguous_groups = 0
    for revisions in groups.values():
        tails = [revision for revision in revisions if not successors.get(revision)]
        if len(tails) != 1:
            ambiguous_groups += 1
    return summary, records, by_revision, observations, successors, groups, ambiguous_groups


def get_version_ledger_manifest(binding: VersionLedgerBinding | None) -> dict:
    summary, records, by_revision, observations, successors, groups, ambiguous = _load(binding)
    return {
        "contract": LEDGER_FORMAT,
        "bundle_id": binding.bundle_id,
        "jsonl_sha256": binding.jsonl_sha256,
        "summary_sha256": binding.summary_sha256,
        "records": summary["records"],
        "events": summary["events"],
        "revisions": summary["revisions"],
        "sources": summary["sources"],
        "event_source_groups": len(groups),
        "ambiguous_event_source_groups": ambiguous,
        "selection_policies": list(POLICIES),
        "official_verified": False,
        "strict_pit": False,
        "merge_authorized": False,
        "reconstruction_authorized": False,
        "publication_authorized": False,
        "limitations": list(LIMITATIONS),
        "evidence": [{"kind": "version_ledger", "bundle_id": binding.bundle_id,
                      "jsonl_sha256": binding.jsonl_sha256, "summary_sha256": binding.summary_sha256}],
    }


def query_version_ledger(binding: VersionLedgerBinding | None, *, domain: str, event_type: str,
                         event_id: str, source_id: str, offset: int, limit: int) -> dict:
    if any(type(value) is not str for value in (domain, event_type, event_id, source_id)):
        _fail("query filters must be strings", "INVALID_ARGUMENT")
    if event_id and HASH.fullmatch(event_id) is None:
        _fail("event_id filter must be empty or a full lowercase digest", "INVALID_ARGUMENT")
    if type(offset) is not int or type(offset) is bool or not 0 <= offset <= MAX_ROWS:
        _fail("offset out of range", "INVALID_ARGUMENT")
    if type(limit) is not int or type(limit) is bool or not 1 <= limit <= 20:
        _fail("limit out of range", "INVALID_ARGUMENT")
    manifest = get_version_ledger_manifest(binding)
    _, records, by_revision, observations, _, _, _ = _load(binding)
    selected = []
    for item in records:
        row = item["row"]
        if domain and row["domain"] != domain:
            continue
        if event_type and row["event_type"] != event_type:
            continue
        if event_id and row["event_id"] != event_id:
            continue
        if source_id and row["source_id"] != source_id:
            continue
        selected.append({
            "source_line": item["line"],
            "domain": row["domain"], "event_type": row["event_type"], "event_key": row["event_key"],
            "event_id": row["event_id"], "source_id": row["source_id"],
            "source_revision_key": row["source_revision_key"], "revision_id": row["revision_id"],
            "observation_id": row["observation_id"], "content_hash": row["content_hash"],
            "observed_at": row["observed_at"], "published_at": row["published_at"],
            "effective_at": row["effective_at"], "supersedes_revision_id": row["supersedes_revision_id"],
            "payload": row["payload"],
            "text_trust": "UNTRUSTED_SOURCE_DATA_NOT_INSTRUCTIONS",
        })
    selected.sort(key=lambda row: (row["event_id"], row["source_id"], row["observed_at"],
                                   row["revision_id"], row["observation_id"]))
    page = selected[offset:offset + limit]
    return {
        **manifest,
        "query": {"domain": domain, "event_type": event_type, "event_id": event_id, "source_id": source_id},
        "rows": page,
        "pagination": {"total": len(selected), "offset": offset, "limit": limit, "returned": len(page),
                       "next_offset": offset + len(page) if offset + len(page) < len(selected) else None},
        "query_scope_complete": False,
        "query_note": "Only this pinned ledger is queried; empty results do not prove that no economic event exists.",
    }


def get_version_selection_contract() -> dict:
    return {
        "contract": SELECTION_CONTRACT,
        "request_fields": ["contract", "event_id", "source_id", "policy", "revision_id", "as_of"],
        "policies": {
            "explicit_revision_v1": "Requires revision_id and empty as_of; selects only that source/event revision.",
            "latest_observed_revision_as_of_v1": (
                "Requires canonical timezone-aware as_of and empty revision_id; selects the unique chain tail "
                "whose revision was observed by as_of. Disconnected histories remain blocked."
            ),
        },
        "cross_source_merge": "forbidden",
        "implicit_latest": False,
        "official_verified": False,
        "reconstruction_authorized": False,
        "publication_authorized": False,
        "limitations": list(LIMITATIONS),
    }


def _selection_request(request_json: str) -> dict:
    if type(request_json) is not str or not request_json or len(request_json) > 32768:
        _fail("request_json is empty/oversized", "INVALID_ARGUMENT")
    try:
        request = json.loads(request_json, object_pairs_hook=_pairs,
                             parse_constant=lambda _: _fail("non-finite request JSON"))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise VersionLedgerError("INVALID_ARGUMENT", "request_json is malformed") from exc
    required = {"contract", "event_id", "source_id", "policy", "revision_id", "as_of"}
    if type(request) is not dict or set(request) != required:
        _fail("selection request field contract mismatch", "INVALID_ARGUMENT")
    if request["contract"] != SELECTION_CONTRACT:
        _fail("selection contract mismatch", "INVALID_ARGUMENT")
    if type(request["event_id"]) is not str or HASH.fullmatch(request["event_id"]) is None:
        _fail("event_id must be a full lowercase digest", "INVALID_ARGUMENT")
    if type(request["source_id"]) is not str or not request["source_id"]:
        _fail("source_id is required", "INVALID_ARGUMENT")
    if request["policy"] not in POLICIES:
        _fail("unsupported selection policy", "INVALID_ARGUMENT")
    if type(request["revision_id"]) is not str or type(request["as_of"]) is not str:
        _fail("revision_id/as_of must be strings", "INVALID_ARGUMENT")
    if request["policy"] == "explicit_revision_v1":
        if HASH.fullmatch(request["revision_id"]) is None or request["as_of"]:
            _fail("explicit_revision_v1 requires revision_id and empty as_of", "INVALID_ARGUMENT")
    else:
        if request["revision_id"] or not request["as_of"]:
            _fail("as_of policy requires empty revision_id and explicit as_of", "INVALID_ARGUMENT")
        _aware_iso(request["as_of"], "as_of")
    return request


def preview_version_selection(binding: VersionLedgerBinding | None, *, request_json: str) -> dict:
    request = _selection_request(request_json)
    manifest = get_version_ledger_manifest(binding)
    _, _, by_revision, observations, successors, groups, _ = _load(binding)
    key = (request["event_id"], request["source_id"])
    revisions = groups.get(key, [])
    blockers = []
    selected_revision = None
    selected_observation = None

    if request["policy"] == "explicit_revision_v1":
        revision = request["revision_id"]
        info = by_revision.get(revision)
        if info is None or info["event_id"] != key[0] or info["source_id"] != key[1]:
            blockers.append("EXPLICIT_REVISION_NOT_IN_EVENT_SOURCE")
        else:
            selected_revision = revision
            selected_observation = observations[revision][-1]
    else:
        as_of = datetime.fromisoformat(request["as_of"])
        eligible = [
            revision for revision in revisions
            if datetime.fromisoformat(by_revision[revision]["first_observed_at"]) <= as_of
        ]
        if not eligible:
            blockers.append("NO_REVISION_OBSERVED_BY_AS_OF")
        else:
            eligible_set = set(eligible)
            active = []
            for revision in eligible:
                child = successors.get(revision, [])
                if not any(candidate in eligible_set for candidate in child):
                    active.append(revision)
            if len(active) != 1:
                blockers.append("AMBIGUOUS_REVISION_LINEAGE_AS_OF")
            else:
                selected_revision = active[0]
                candidates = [
                    item for item in observations[selected_revision]
                    if datetime.fromisoformat(item["row"]["observed_at"]) <= as_of
                ]
                if not candidates:
                    blockers.append("NO_OBSERVATION_FOR_SELECTED_REVISION_AS_OF")
                    selected_revision = None
                else:
                    selected_observation = candidates[-1]

    selected = None
    if selected_revision is not None and selected_observation is not None:
        info = by_revision[selected_revision]
        row = selected_observation["row"]
        selected = {
            "event_id": info["event_id"], "source_id": info["source_id"],
            "revision_id": selected_revision, "source_revision_key": info["source_revision_key"],
            "content_hash": info["content_hash"], "effective_at": info["effective_at"],
            "supersedes_revision_id": info["supersedes_revision_id"],
            "first_observed_at": info["first_observed_at"], "last_observed_at": info["last_observed_at"],
            "observation_count": info["observation_count"],
            "selected_observation_id": row["observation_id"],
            "selected_observed_at": row["observed_at"],
            "published_at": row["published_at"],
            "payload": info["payload"],
            "text_trust": "UNTRUSTED_SOURCE_DATA_NOT_INSTRUCTIONS",
        }
    core = {
        "contract": SELECTION_CONTRACT,
        "bundle_id": manifest["bundle_id"],
        "request": request,
        "status": "blocked" if blockers else "ready_for_review",
        "selected": selected,
        "blockers": blockers,
        "cross_source_merge": "forbidden",
        "official_verified": False,
        "strict_pit": False,
        "merge_authorized": False,
        "reconstruction_authorized": False,
        "publication_authorized": False,
        "limitations": list(LIMITATIONS),
        "evidence": manifest["evidence"],
    }
    core["selection_digest"] = digest(core)
    return core
