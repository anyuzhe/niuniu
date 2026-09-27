"""Small read-only evidence summaries shared by everyday candidates and AI tools.

This module adapts existing candidate-rule validation dictionaries and immutable
research archives into one bounded structure.  It does not rewrite legacy caches
or mark a factor definition as a valid Alpha.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from uuid import UUID

from quantlab.storage.codec import encode
from quantlab.storage.experiments import load_record_fields

VERSION = 'niuniu-research-evidence-v1'
MAX_LIMITATIONS = 12
SCAN_BUDGET = 200
MAX_HEADER_BYTES = 8 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 100000
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def _finite(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    return value


def sanitize(value):
    """Return JSON/allow_nan=False safe data without inventing replacements."""
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize(v) for v in value]
    return _finite(value)


def _uuid_or_none(value):
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except (ValueError, TypeError):
        return None


def _valid_uuid_name(name: str) -> bool:
    return isinstance(name, str) and _UUID_RE.fullmatch(name) is not None and _uuid_or_none(name) == name


def rule_identity(rule: dict) -> dict:
    return sanitize({
        'key': rule.get('key'),
        'name': rule.get('name'),
        'description': rule.get('description'),
        'order': rule.get('order'),
        'descending': rule.get('descending'),
        'method': rule.get('method') or 'market_overview_candidate_rule',
        'method_version': rule.get('method_version') or 'legacy_or_unspecified',
        'identity_note': '候选规则按完整规则字段识别；仅名称相同不能认定为同一规则。',
    })


def _limitations(caveats):
    mandatory = [
        '快速历史参考沿用页面固定算法；research_only，不是Alpha认证或交易建议。',
        '因子/规则定义与某次历史结果分开保存；本摘要不把规则永久标为有效Alpha。',
    ]
    values = list(caveats or []) + mandatory
    result = {'items': values, 'count': len(values), 'max_display_without_error': MAX_LIMITATIONS,
              'incomplete': False, 'error': None}
    if len(values) > MAX_LIMITATIONS:
        result['incomplete'] = True
        result['error'] = 'LIMITATIONS_EXCEED_DISPLAY_BUDGET; returning all warning text in items, callers must not silently truncate.'
    return result


def candidate_rule_evidence(rule: dict, *, trading_day: str | None = None, sources: dict | None = None,
                            caveats: list[str] | None = None) -> dict:
    validation = rule.get('validation') if isinstance(rule.get('validation'), dict) else {}
    valid_but_unverified = _uuid_or_none(validation.get('run_id'))
    lim = _limitations(caveats)
    return sanitize({
        'version': VERSION,
        'type': 'candidate_rule_quick_history',
        'status': 'research_only_reference',
        'incomplete': lim['incomplete'],
        'error': lim['error'],
        'rule_identity': rule_identity(rule),
        'source': {
            'asof': trading_day,
            'kind': 'market_overview_candidate_validation',
            'sources': sources or {},
            # Quick history is not an immutable research run. A valid UUID in old metadata is not clickable evidence.
            'run_id': None,
            'unverified_run_id': valid_but_unverified,
            'metadata_only': True,
        },
        'range': {'first_day': validation.get('first_day'), 'last_day': validation.get('last_day')},
        'sample': {
            'non_overlapping_days': validation.get('samples'),
            'avg_selected': validation.get('avg_selected'),
            'min_required_days': validation.get('min_samples'),
            'min_selected_per_day': validation.get('min_selected'),
        },
        'method': {
            'method_id': validation.get('method_id') or rule.get('method') or 'market_overview_candidate_validation',
            'method_version': validation.get('method_version') or rule.get('method_version') or 'legacy_or_unspecified',
            'hold_sessions': validation.get('hold_sessions'),
            'benchmark': validation.get('benchmark'),
            'entry_exit': validation.get('entry_exit'),
            'research_only': True,
        },
        'statistics': {
            'verdict': validation.get('verdict'),
            'mean_excess': validation.get('mean_excess'),
            'net_excess': validation.get('net_excess'),
            'hit_rate': validation.get('hit_rate'),
            't_stat': validation.get('t_stat'),
            'legacy_text': validation.get('text'),
            'legacy_text_note': '旧版本叙述仅说明当时快速历史参考，不是当前认证。',
        },
        'costs': {'round_trip_cost': validation.get('cost'), 'assumption': 'flat rounded estimate' if validation.get('cost') is not None else None},
        'limitations': lim['items'],
        'limitations_meta': {k: v for k, v in lim.items() if k != 'items'},
    })


def candidate_prompt_payload(overview: dict, rule: dict, caveats: list[str] | None = None, shown_limit: int = 30) -> dict:
    shown = list(rule.get('stocks', [])[:shown_limit])
    return sanitize({
        'trading_day': overview.get('trading_day'),
        'market_summary': overview.get('summary', []),
        'rule': {'identity': rule_identity(rule), 'count': rule.get('count')},
        'current_scope': {
            'listed_count': rule.get('count'),
            'shown_stocks': shown,
            'shown_is_complete': None if rule.get('count') is None else rule.get('count') <= len(shown),
            'display_note': None if rule.get('count') is None or rule.get('count') <= len(shown) else 'shown_stocks is a bounded subset, not all current candidates',
        },
        'evidence': candidate_rule_evidence(rule, trading_day=overview.get('trading_day'),
                                            sources=overview.get('sources'), caveats=caveats),
        'instruction': '只讨论进一步研究优先级和风险；不要给出确定买卖指令，不要自动映射相似因子或自动批准研究。',
    })


def bounded_json(value, max_bytes: int) -> str:
    payload = sanitize(value)
    text = encode(payload)
    if len(text.encode('utf-8')) <= max_bytes:
        return text
    raise ValueError('structured payload exceeds byte budget')


def _fingerprint(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError('Symlink archive header refused')
    stat = path.stat()
    if stat.st_size > MAX_HEADER_BYTES:
        raise ValueError('Archive header exceeds the 8 MiB read budget')
    with path.open('rb') as stream:
        raw = stream.read(MAX_HEADER_BYTES + 1)
    after = path.stat()
    if len(raw) > MAX_HEADER_BYTES or (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Archive header changed during bounded read')
    return {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
            'sha256': hashlib.sha256(raw).hexdigest()}


def _cfg_identity(cfg: dict) -> dict:
    return {'factor_id': cfg.get('factor_id'), 'factor_version': cfg.get('factor_version'),
            'parameters': cfg.get('parameters') or {}, 'resolved_parameters': cfg.get('resolved_parameters')}


def archive_research_reference(output, run_id: str) -> dict:
    """Read a bounded original header; this is not full artifact or numerical verification."""
    from quantlab.workbench.server import ArtifactCatalog
    if not _valid_uuid_name(run_id) or Path(output).is_symlink():
        raise ValueError('Canonical run_id and non-symlink workspace required')
    rid = run_id
    catalog = ArtifactCatalog(output)
    path = catalog.file(rid, 'experiment.json')
    before = _fingerprint(path)
    record = load_record_fields(path, {'run_id', 'experiment_id', 'created_at', 'status', 'kind', 'manifest',
                                       'parameters', 'execution', 'limitations', 'sources'})
    if record.get('run_id') != rid:
        raise ValueError('run_id identity mismatch')
    manifest = record.get('manifest') if isinstance(record.get('manifest'), dict) else {}
    cfg = manifest.get('config') if isinstance(manifest.get('config'), dict) else {}
    data = cfg.get('data') if isinstance(cfg.get('data'), dict) else {}
    limitations = record.get('limitations') if isinstance(record.get('limitations'), list) else []
    if _fingerprint(path) != before:
        raise ValueError('Archive header changed during inspection')
    execution = manifest.get('execution')
    resolved = manifest.get('parameters')
    return sanitize({
        'version': VERSION,
        'type': 'archive_research_reference',
        'status': record.get('status'),
        'metadata_only': True,
        'verification': 'original_header_sha256_only',
        'deep_verified': False,
        'rule_identity': {**_cfg_identity(cfg),
            'resolved_parameters': resolved,
            'parameter_filter_basis': 'manifest.parameters' if isinstance(resolved, dict) else 'config.parameters',
            'legacy_config_parameters': cfg.get('parameters') or {},
            'identity_note': 'factor_id/version/parameters共同识别；仅名称相同不能认定为同一规则。'},
        'source': {'run_id': rid, 'experiment_id': record.get('experiment_id'), 'created_at': record.get('created_at'),
                   'fingerprint': before},
        'range': {'start': data.get('start'), 'end': data.get('end'), 'timeframe': data.get('timeframe'),
                  'symbols': data.get('symbols')},
        'sample': {'symbols': len(data.get('symbols') or []) if isinstance(data.get('symbols'), list) else None},
        'parameters': record.get('parameters'),
        'manifest_parameters': manifest.get('parameters'),
        'manifest_execution': manifest.get('execution'),
        'execution': record.get('execution'),
        'sources': record.get('sources'),
        'costs': {'source': 'manifest.execution' if isinstance(execution, dict) else None,
                  'configuration': execution if isinstance(execution, dict) else None,
                  'assumption': 'archived execution configuration; not re-priced' if isinstance(execution, dict) else None},
        'limitations': limitations,
        'limitations_meta': {'count': len(limitations), 'incomplete': False},
    })


def _candidate_run_dirs(output: Path) -> list[Path]:
    if not output.is_dir():
        raise ValueError('Artifact directory does not exist')
    result = []
    for index, child in enumerate(output.iterdir()):
        if index >= MAX_DIRECTORY_ENTRIES:
            raise ValueError('Workspace listing exceeds bounded discovery budget')
        if _valid_uuid_name(child.name):
            # Keep malformed/symlinked UUID entries in the page so errors stay visible.
            result.append(child)
    return sorted(result, key=lambda p: p.name)


def find_factor_evidence(output, *, factor_id: str, factor_version: str | None = None,
                         parameters: dict | None = None, offset: int = 0, limit: int = 20,
                         scan_budget: int = SCAN_BUDGET) -> dict:
    """Bounded read-only discovery over actual UUID archive dirs."""
    if not isinstance(factor_id, str) or not factor_id.strip():
        raise ValueError('factor_id required')
    if isinstance(offset, bool) or isinstance(limit, bool) or isinstance(scan_budget, bool):
        raise ValueError('pagination values must be integers, not bool')
    if not isinstance(offset, int) or not isinstance(limit, int) or not isinstance(scan_budget, int):
        raise ValueError('pagination values must be integers')
    if offset < 0 or not 1 <= limit <= 50 or not 1 <= scan_budget <= 500:
        raise ValueError('invalid pagination')
    if parameters is not None and not isinstance(parameters, dict):
        raise ValueError('parameters must be an object when supplied; omit to match any parameter set')
    if Path(output).is_symlink():
        raise ValueError('Symlink workspace refused')
    dirs = _candidate_run_dirs(Path(output).resolve())
    window = dirs[offset:offset + scan_budget]
    matches, mismatches, errors = [], [], []
    scanned = 0
    for folder in window:
        # Stop before consuming an entry we cannot return; the cursor never skips evidence.
        if len(matches) + len(mismatches) + len(errors) >= limit:
            break
        rid = folder.name
        scanned += 1
        try:
            reference = archive_research_reference(output, rid)
            identity = reference['rule_identity']
            if identity['factor_id'] != factor_id:
                continue
            reasons = []
            if factor_version is not None and identity['factor_version'] != factor_version:
                reasons.append('factor_version_mismatch')
            effective = identity.get('resolved_parameters')
            if not isinstance(effective, dict):
                effective = identity['parameters']
            if parameters is not None and effective != parameters:
                reasons.append('parameters_mismatch')
            if reasons:
                mismatches.append({'run_id': rid, 'identity': identity, 'reasons': reasons, 'metadata_only': True})
            else:
                matches.append(reference)
        except Exception as exc:
            errors.append({'run_id': rid, 'error': type(exc).__name__ + ': ' + str(exc)[:240]})
    matches.sort(key=lambda r: (r.get('source') or {}).get('created_at') or '', reverse=True)
    next_offset = offset + scanned if offset + scanned < len(dirs) else None
    incomplete = next_offset is not None
    return sanitize({'version': VERSION, 'type': 'factor_evidence_discovery', 'factor_id': factor_id,
                     'factor_version': factor_version, 'parameters': parameters,
                     'parameter_filter_note': 'Omitted parameters matches any set; exact filter uses archived manifest.parameters when present, otherwise raw config.parameters. {} is exact empty, not current defaults.',
                     'matches': matches, 'returned_matches': len(matches),
                     'total_matches': len(matches) if offset == 0 and next_offset is None else None,
                     'matched_in_window': len(matches),
                     'mismatches': mismatches, 'errors': errors,
                     'scanned': scanned, 'scan_budget': scan_budget, 'offset': offset,
                     'next_offset': next_offset, 'has_more': next_offset is not None,
                     'incomplete': incomplete,
                     'identity_note': 'metadata discovery only narrows candidates; archive references are read from experiment.json and still must be opened with fingerprint checks.'})


__all__ = ['VERSION', 'sanitize', 'rule_identity', 'candidate_rule_evidence', 'candidate_prompt_payload',
           'archive_research_reference', 'find_factor_evidence', 'bounded_json']
