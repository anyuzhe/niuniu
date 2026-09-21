"""Bounded, read-only discovery and inspection of archived strategy runs."""
from __future__ import annotations

from copy import deepcopy

from pathlib import Path
from uuid import UUID
import os
import stat

from quantlab.storage.artifact_integrity import file_hash
from quantlab.storage.codec import digest
from quantlab.storage.experiments import load_record_fields
from quantlab.trading.strategy_comparison import compare_strategy_runs
from quantlab.trading.strategy_package import validate_strategy_envelope_spec


_MAX_CANDIDATES = 100_000
_MAX_SCANNED = 100
_MAX_JSON_BYTES = 8 * 1024 * 1024
_FIELDS = {"run_id", "experiment_id", "created_at", "status", "kind", "manifest"}


class _CandidateError(ValueError):
    pass


def _canonical_uuid(value, label="run_id"):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"{label} must be a canonical UUID") from None
    return value


def _root(output):
    path = Path(output)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Strategy artifact root must be an existing non-symlink directory")
    return path.resolve()


def _candidate_names(root):
    names = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                try:
                    _canonical_uuid(entry.name)
                except ValueError:
                    continue
                names.append(entry.name)
                if len(names) > _MAX_CANDIDATES:
                    raise ValueError("Strategy run candidate count exceeds 100000")
    except ValueError:
        raise
    except OSError as error:
        raise ValueError("Unable to enumerate strategy artifact root") from error
    return sorted(names)


def _record_path(root, run_id):
    folder = root / run_id
    try:
        mode = folder.lstat().st_mode
    except OSError as error:
        raise _CandidateError("candidate_unavailable") from error
    if stat.S_ISLNK(mode):
        raise _CandidateError("symlink_candidate")
    if not stat.S_ISDIR(mode):
        raise _CandidateError("candidate_not_directory")
    try:
        if folder.resolve().parent != root:
            raise _CandidateError("candidate_path_escape")
    except OSError as error:
        raise _CandidateError("candidate_unavailable") from error
    path = folder / "experiment.json"
    try:
        info = path.lstat()
    except OSError as error:
        raise _CandidateError("missing_experiment_json") from error
    if stat.S_ISLNK(info.st_mode):
        raise _CandidateError("symlink_experiment_json")
    if not stat.S_ISREG(info.st_mode):
        raise _CandidateError("special_experiment_json")
    if info.st_size > _MAX_JSON_BYTES:
        raise _CandidateError("experiment_json_too_large")
    try:
        if path.resolve().parent != folder:
            raise _CandidateError("experiment_path_escape")
    except OSError as error:
        raise _CandidateError("candidate_unavailable") from error
    return path, info


def _load_metadata(root, run_id):
    path, before = _record_path(root, run_id)
    try:
        record = load_record_fields(path, _FIELDS)
        after = path.lstat()
    except Exception as error:
        raise _CandidateError("unreadable_experiment_json") from error
    stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if path.is_symlink() or not stat.S_ISREG(after.st_mode) or any(
        getattr(before, field) != getattr(after, field) for field in stable
    ):
        raise _CandidateError("experiment_json_changed")
    manifest = record.get("manifest")
    try:
        identity_ok = (
            type(manifest) is dict
            and record.get("run_id") == run_id
            and record.get("experiment_id") == digest(manifest)
        )
    except Exception as error:
        raise _CandidateError("archive_identity_mismatch") from error
    if not identity_ok:
        raise _CandidateError("archive_identity_mismatch")
    if record.get("kind") != "execution" or "strategy_package" not in manifest:
        return None
    envelope = manifest["strategy_package"]
    try:
        if type(envelope) is not dict or type(envelope.get("package")) is not dict:
            raise ValueError
        package = envelope["package"]
        spec = package.get("spec")
        if type(spec) is not dict:
            raise ValueError
        checked = validate_strategy_envelope_spec({**spec, "strategy_package": envelope})
        if checked["package_hash"] != digest(checked["package"]):
            raise ValueError
        created_at = record.get("created_at")
        status = record.get("status")
        question = checked["package"]["spec"].get("question")
        if not all(type(value) is str for value in (created_at, status, question)):
            raise ValueError
    except Exception as error:
        raise _CandidateError("invalid_strategy_package") from error
    package = checked["package"]
    return {
        "run_id": run_id,
        "strategy_key": package["strategy_key"],
        "name": package["name"],
        "version": package["version"],
        "question": question,
        "created_at": created_at,
        "status": status,
        "package_hash": checked["package_hash"],
        "verification": "metadata_only",
    }


def _validate_page(query, offset, limit):
    if type(query) is not str or len(query) > 200:
        raise ValueError("query must be a string of at most 200 characters")
    if type(offset) is not int or not 0 <= offset <= 100_000:
        raise ValueError("offset must be an integer from 0 to 100000")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("limit must be an integer from 1 to 20")


def list_strategy_runs(output, query="", offset=0, limit=20) -> dict:
    """Discover packaged execution archives from direct UUID children only."""
    _validate_page(query, offset, limit)
    root = _root(output)
    candidates = _candidate_names(root)
    runs = []
    errors = []
    non_strategy = 0
    scanned = 0
    index = min(offset, len(candidates))
    needle = query.casefold()
    while index < len(candidates) and scanned < _MAX_SCANNED and len(runs) < limit:
        run_id = candidates[index]
        index += 1
        scanned += 1
        try:
            row = _load_metadata(root, run_id)
        except _CandidateError as error:
            errors.append({"run_id": run_id, "reason": str(error)})
            continue
        if row is None:
            non_strategy += 1
            continue
        searchable = (row[key] for key in (
            "run_id", "strategy_key", "name", "version", "question", "created_at", "status", "package_hash"
        ))
        if not needle or any(needle in value.casefold() for value in searchable):
            runs.append(row)
    next_offset = index if index < len(candidates) else None
    return {
        "runs": runs,
        "query": query,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "total_candidates": len(candidates),
        "scanned": scanned,
        "has_more": next_offset is not None,
        "non_strategy": non_strategy,
        "errors": errors,
        "incomplete": bool(errors),
    }


def get_strategy_run(output, run_id) -> dict:
    """Deeply verify one historical packaged execution without reproducing it."""
    root = _root(output)
    identifier = _canonical_uuid(run_id)
    # Enforce the metadata bound before the deep archive comparison reads it.
    path, _ = _record_path(root, identifier)
    comparison = compare_strategy_runs(root, identifier, identifier)
    try:
        left = comparison["left"]
        expected = left["evidence_fingerprint"]["experiment_json"]
        if (left["run_id"] != identifier or comparison["right"]["run_id"] != identifier
                or comparison["scope"] != "DESCRIPTIVE_ONLY" or not comparison["comparable"]):
            raise ValueError
        before = file_hash(path)
        if before != expected:
            raise ValueError
        record = load_record_fields(path, {"manifest"})
        after = file_hash(path)
        if after != before or after != expected:
            raise ValueError
        envelope = record["manifest"]["strategy_package"]
        package = envelope["package"]
        if envelope["package_hash"] != left["package"]["package_hash"] or digest(package) != envelope["package_hash"]:
            raise ValueError
    except Exception as error:
        raise ValueError("Execution evidence changed after archive verification") from error
    warnings = list(comparison["warnings"])
    boundary = "仅核对历史归档内部一致性；未重新编译策略、回测或读取源 data_root。"
    if boundary not in warnings:
        warnings.append(boundary)
    return {
        "run_id": identifier,
        "package_identity": left["package"],
        "package": package,
        "execution_metrics": left["execution_metrics"],
        "evidence_fingerprint": left["evidence_fingerprint"],
        "verification": "archive_internal_consistency",
        "scope": "DESCRIPTIVE_ONLY",
        "warnings": warnings,
    }


def prepare_strategy_revision(output, run_id, *, expected_package_hash):
    """Verify a selected archive, then separately compile an editable copy today.

    The source identity is historical evidence, not a new grant, proposal or
    reproducibility claim.  No source bytes or persistent state are written.
    """
    if (type(expected_package_hash) is not str or len(expected_package_hash) != 64
            or any(c not in '0123456789abcdef' for c in expected_package_hash)):
        raise ValueError('必须传入所选归档的精确 package_hash，请重新查找归档。')
    detail = get_strategy_run(output, run_id)
    if detail['package_identity']['package_hash'] != expected_package_hash:
        raise ValueError('所选归档配置已变化，请重新查找并核验；原草稿保留。')
    from quantlab.trading.strategy_package import compile_strategy
    compiled = compile_strategy(deepcopy(detail['package']))
    source = {
        'run_id': detail['run_id'],
        'package_identity': deepcopy(detail['package_identity']),
        'evidence_fingerprint': deepcopy(detail['evidence_fingerprint']),
        'verification': detail['verification'],
    }
    matches = compiled['compiled_spec_hash'] == source['package_identity']['compiled_spec_hash']
    warnings = ['历史归档已核验；当前编译只是新草稿解释，不是复算、批准或旧结果可重现的证明。']
    if not matches:
        warnings.append('当前编译与历史指纹不同；原配置/信号解析已变化，同一策略须指定新版本。')
    return {
        'source': source,
        'historical_package': deepcopy(detail['package']),
        'compiled': compiled,
        'current_matches_history': matches,
        'warnings': warnings,
        'execution_authorized': False,
    }


__all__ = ["list_strategy_runs", "get_strategy_run", "prepare_strategy_revision"]
