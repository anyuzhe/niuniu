"""Read-only audit adapter for external Research Skill packages.

A Research Skill is evidence and hypothesis packaging, not executable trading logic.
This module never runs bundled scripts, writes Playbook records, certifies Strict PIT,
or emits a trade signal.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import re

from quantlab.storage.codec import digest
from quantlab.trading.playbook import STRATEGY_SOURCE_KINDS, normalize_strategy_source

FORMAT = 'niuniu-research-skill-v1'
AUDIT_FORMAT = 'niuniu-research-skill-audit-v1'
MANIFEST = 'skill.yml'
MAX_MANIFEST_BYTES = 1_000_000
MAX_RESOURCE_BYTES = 8_000_000
MAX_PACKAGE_BYTES = 32_000_000
MAX_RESOURCES = 200
SLUG = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
HASH = re.compile(r'^[0-9a-f]{64}$')
VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')

STATUSES = ('TEMPLATE', 'SOURCE_REQUIRED', 'DRAFT', 'REVIEWED', 'RETIRED')
RESOURCE_ROLES = (
    'BEHAVIOR_CONTRACT', 'PRIMARY_STATEMENT', 'DISCLOSED_ACTION', 'REALIZED_OUTCOME',
    'METHOD', 'SCORECARD', 'SCRIPT', 'SCRIPT_POLICY', 'DOCUMENTATION',
)
EVIDENCE_ROLES = {'PRIMARY_STATEMENT', 'DISCLOSED_ACTION', 'REALIZED_OUTCOME'}
TIMING_CLASSES = ('NOT_APPLICABLE', 'RETROSPECTIVE_REFERENCE', 'PUBLICATION_VERIFIED')
CLAIM_KINDS = ('DIRECT_QUOTE', 'METHOD_INFERENCE', 'FACT_TO_VERIFY')
ALIGNMENT_ASSESSMENTS = ('CONSISTENT', 'INCONSISTENT', 'MIXED', 'UNKNOWN')
TARGET_HORIZONS = ('INTRADAY', 'SWING', 'MEDIUM_TERM', 'LONG_TERM', 'MULTI_HORIZON')
PIPELINE = [
    'RESEARCH_SKILL', 'STRATEGY_SOURCE', 'PLAYBOOK_DRAFT', 'QUANT_VALIDATION',
    'DAILY_DECISION', 'OUTCOME_REVIEW',
]
REQUIRED_POLICY = {
    'network_default': 'DENY',
    'model_write_allowed': False,
    'direct_trade_eligible': False,
    'daily_scanner_eligible': False,
    'quarterly_data_intraday_eligible': False,
    'strict_pit_eligible': False,
    'alpha_claimed': False,
    'institutional_data_role': 'THEME_DOSSIER_AUXILIARY_ONLY',
    'score_semantics': 'SOURCE_STYLE_SIMILARITY_ONLY',
    'intended_pipeline': PIPELINE,
}
TOP_FIELDS = {
    'format', 'skill_key', 'title', 'version', 'status', 'strategy_source_kind',
    'summary', 'keywords', 'resources', 'claims', 'alignments', 'hypotheses', 'policy',
}
RESOURCE_FIELDS = {
    'resource_id', 'path', 'role', 'sha256', 'bytes', 'locator', 'published_at',
    'available_at', 'timing_class',
}
CLAIM_FIELDS = {'claim_id', 'kind', 'text', 'resource_ids'}
ALIGNMENT_FIELDS = {
    'alignment_id', 'statement_claim_id', 'action_resource_ids',
    'outcome_resource_ids', 'assessment', 'notes',
}
HYPOTHESIS_FIELDS = {
    'hypothesis_key', 'title', 'status', 'claim_ids', 'feature_candidates',
    'required_data', 'target_horizon', 'playbook_key', 'score_semantics',
}


class ResearchSkillError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _fail(code, message):
    raise ResearchSkillError(code, message)


def _object(value, fields, name):
    if not isinstance(value, dict) or set(value) != set(fields):
        _fail('SCHEMA_INVALID', name + ' 字段必须与合同完全一致。')
    return value


def _text(value, name, maximum, required=True):
    if not isinstance(value, str):
        _fail('SCHEMA_INVALID', name + ' 必须是文本。')
    value = value.strip()
    if required and not value:
        _fail('SCHEMA_INVALID', name + ' 不能为空。')
    if len(value) > maximum:
        _fail('BUDGET_EXCEEDED', name + f' 不能超过 {maximum} 字。')
    return value


def _slug(value, name):
    value = _text(value, name, 64).lower()
    if not SLUG.fullmatch(value):
        _fail('SCHEMA_INVALID', name + ' 只能使用小写字母、数字、下划线或连字符。')
    return value


def _enum(value, name, options):
    value = _text(value, name, 80).upper()
    if value not in options:
        _fail('SCHEMA_INVALID', name + ' 取值无效。')
    return value


def _moment(value, name, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        _fail('TIMING_INVALID', name + ' 必须是带时区 ISO 8601 时间。')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        _fail('TIMING_INVALID', name + ' 必须是带时区 ISO 8601 时间。')
    if parsed.tzinfo is None:
        _fail('TIMING_INVALID', name + ' 必须包含时区。')
    return parsed.isoformat()


def _ids(value, name, maximum=200, required=False):
    if not isinstance(value, list) or len(value) > maximum:
        _fail('SCHEMA_INVALID', name + f' 必须是不超过 {maximum} 项的数组。')
    result = [_slug(item, name) for item in value]
    if required and not result:
        _fail('SCHEMA_INVALID', name + ' 至少需要一项。')
    if len(set(result)) != len(result):
        _fail('SCHEMA_INVALID', name + ' 不能重复。')
    return result


def _texts(value, name, maximum=100, item_maximum=300, required=False):
    if not isinstance(value, list) or len(value) > maximum:
        _fail('SCHEMA_INVALID', name + f' 必须是不超过 {maximum} 项的文本数组。')
    result = [_text(item, name, item_maximum) for item in value]
    if required and not result:
        _fail('SCHEMA_INVALID', name + ' 至少需要一项。')
    if len(set(result)) != len(result):
        _fail('SCHEMA_INVALID', name + ' 不能重复。')
    return result


def _pairs_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _fail('MANIFEST_INVALID', 'skill.yml 不能包含重复 JSON key：' + key)
        value[key] = item
    return value


def _load_manifest(root):
    path = root / MANIFEST
    if path.is_symlink() or not path.is_file():
        _fail('MANIFEST_INVALID', 'Research Skill 必须包含非符号链接 skill.yml。')
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_MANIFEST_BYTES:
        _fail('BUDGET_EXCEEDED', 'skill.yml 为空或超过 1MB。')
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_pairs_object)
    except ResearchSkillError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail('MANIFEST_INVALID', 'skill.yml 必须使用确定性的 JSON-compatible YAML。')


def _relative_path(value):
    value = _text(value, 'resource.path', 500)
    pure = PurePosixPath(value)
    if pure.is_absolute() or '..' in pure.parts or '.' in pure.parts or pure.as_posix() != value or value == MANIFEST:
        _fail('PATH_INVALID', 'resource.path 必须是包内规范相对路径，且不能指向 skill.yml。')
    return pure


def _read_resource(root, item):
    _object(item, RESOURCE_FIELDS, 'resource')
    resource_id = _slug(item['resource_id'], 'resource_id')
    relative = _relative_path(item['path'])
    role = _enum(item['role'], 'resource.role', RESOURCE_ROLES)
    expected_hash = _text(item['sha256'], 'resource.sha256', 64).lower()
    expected_bytes = item['bytes']
    if not HASH.fullmatch(expected_hash):
        _fail('SCHEMA_INVALID', 'resource.sha256 必须是 64 位小写 SHA256。')
    if type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_RESOURCE_BYTES:
        _fail('BUDGET_EXCEEDED', 'resource.bytes 必须是 1～8,000,000。')
    target = root.joinpath(*relative.parts)
    if target.is_symlink() or not target.is_file():
        _fail('RESOURCE_MISSING', '资源缺失或为符号链接：' + relative.as_posix())
    resolved = target.resolve()
    if not resolved.is_relative_to(root):
        _fail('PATH_INVALID', '资源路径越过 Research Skill 根目录。')
    actual_bytes = target.stat().st_size
    if actual_bytes <= 0 or actual_bytes > MAX_RESOURCE_BYTES:
        _fail('BUDGET_EXCEEDED', '实际资源为空或超过 8MB：' + relative.as_posix())
    payload = target.read_bytes()
    actual_hash = sha256(payload).hexdigest()
    if actual_bytes != expected_bytes or len(payload) != actual_bytes or actual_hash != expected_hash:
        _fail('RESOURCE_HASH_MISMATCH', '资源字节或 SHA256 不匹配：' + relative.as_posix())

    locator = _text(item['locator'], 'resource.locator', 2000, required=False)
    published = _moment(item['published_at'], 'resource.published_at')
    available = _moment(item['available_at'], 'resource.available_at')
    timing = _enum(item['timing_class'], 'resource.timing_class', TIMING_CLASSES)
    if published and available and datetime.fromisoformat(available) < datetime.fromisoformat(published):
        _fail('TIMING_INVALID', 'resource.available_at 不能早于 published_at。')
    if role in EVIDENCE_ROLES:
        if not locator or not available or timing == 'NOT_APPLICABLE':
            _fail('EVIDENCE_INVALID', '原始观点/行为/结果资源必须有 locator、available_at 和证据时点分类。')
        if timing == 'PUBLICATION_VERIFIED' and not published:
            _fail('TIMING_INVALID', 'PUBLICATION_VERIFIED 资源必须保存 published_at。')
        if relative.parts[0] != 'references':
            _fail('PATH_INVALID', '原始观点/行为/结果资源必须位于 references/。')
    elif timing != 'NOT_APPLICABLE' or published is not None or available is not None:
        _fail('TIMING_INVALID', '方法、评分、脚本和说明文件不能伪装成 publication evidence。')
    if role == 'BEHAVIOR_CONTRACT' and relative.as_posix() != 'SKILL.md':
        _fail('LAYOUT_INVALID', 'BEHAVIOR_CONTRACT 必须是 SKILL.md。')
    if role == 'METHOD' and relative.as_posix() != 'method.md':
        _fail('LAYOUT_INVALID', 'METHOD 必须是 method.md。')
    if role == 'SCORECARD' and relative.as_posix() != 'scorecard.md':
        _fail('LAYOUT_INVALID', 'SCORECARD 必须是 scorecard.md。')
    if role in {'SCRIPT', 'SCRIPT_POLICY'} and relative.parts[0] != 'scripts':
        _fail('LAYOUT_INVALID', '脚本及脚本政策必须位于 scripts/。')
    return {
        'resource_id': resource_id, 'path': relative.as_posix(), 'role': role,
        'sha256': expected_hash, 'bytes': expected_bytes, 'locator': locator,
        'published_at': published, 'available_at': available, 'timing_class': timing,
    }


def _scan_files(root):
    files = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            _fail('PATH_INVALID', 'Research Skill 不能包含符号链接：' + str(path.relative_to(root)))
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
            if len(files) > MAX_RESOURCES + 1:
                _fail('BUDGET_EXCEEDED', 'Research Skill 实际文件数量超过预算。')
        elif not path.is_dir():
            _fail('PATH_INVALID', 'Research Skill 不能包含特殊文件：' + str(path.relative_to(root)))
    return files


def _normalize_claim(item, resources):
    _object(item, CLAIM_FIELDS, 'claim')
    claim_id = _slug(item['claim_id'], 'claim_id')
    kind = _enum(item['kind'], 'claim.kind', CLAIM_KINDS)
    resource_ids = _ids(item['resource_ids'], 'claim.resource_ids', required=True)
    if any(resource_id not in resources for resource_id in resource_ids):
        _fail('REFERENCE_INVALID', 'claim 引用了不存在的 resource_id。')
    roles = {resources[resource_id]['role'] for resource_id in resource_ids}
    if kind == 'DIRECT_QUOTE' and roles != {'PRIMARY_STATEMENT'}:
        _fail('CLAIM_SOURCE_INVALID', 'DIRECT_QUOTE 只能引用 PRIMARY_STATEMENT。')
    if kind == 'METHOD_INFERENCE' and 'PRIMARY_STATEMENT' not in roles:
        _fail('CLAIM_SOURCE_INVALID', 'METHOD_INFERENCE 必须回链至少一个 PRIMARY_STATEMENT。')
    if kind == 'FACT_TO_VERIFY' and not roles.intersection(EVIDENCE_ROLES):
        _fail('CLAIM_SOURCE_INVALID', 'FACT_TO_VERIFY 必须回链原始观点、行为或结果资源。')
    return {'claim_id': claim_id, 'kind': kind, 'text': _text(item['text'], 'claim.text', 4000),
        'resource_ids': resource_ids}


def _normalize_alignment(item, claims, resources):
    _object(item, ALIGNMENT_FIELDS, 'alignment')
    alignment_id = _slug(item['alignment_id'], 'alignment_id')
    statement = _slug(item['statement_claim_id'], 'statement_claim_id')
    actions = _ids(item['action_resource_ids'], 'action_resource_ids', required=True)
    outcomes = _ids(item['outcome_resource_ids'], 'outcome_resource_ids')
    if statement not in claims:
        _fail('REFERENCE_INVALID', 'alignment 引用了不存在的 statement claim。')
    if any(resource_id not in resources for resource_id in actions + outcomes):
        _fail('REFERENCE_INVALID', 'alignment 引用了不存在的 resource。')
    if any(resources[resource_id]['role'] != 'DISCLOSED_ACTION' for resource_id in actions):
        _fail('ALIGNMENT_INVALID', 'action_resource_ids 只能引用 DISCLOSED_ACTION。')
    if any(resources[resource_id]['role'] != 'REALIZED_OUTCOME' for resource_id in outcomes):
        _fail('ALIGNMENT_INVALID', 'outcome_resource_ids 只能引用 REALIZED_OUTCOME。')
    return {'alignment_id': alignment_id, 'statement_claim_id': statement,
        'action_resource_ids': actions, 'outcome_resource_ids': outcomes,
        'assessment': _enum(item['assessment'], 'alignment.assessment', ALIGNMENT_ASSESSMENTS),
        'notes': _text(item['notes'], 'alignment.notes', 4000, required=False)}


def _normalize_hypothesis(item, claims, package_status):
    _object(item, HYPOTHESIS_FIELDS, 'hypothesis')
    key = _slug(item['hypothesis_key'], 'hypothesis_key')
    claim_ids = _ids(item['claim_ids'], 'hypothesis.claim_ids')
    if any(claim_id not in claims for claim_id in claim_ids):
        _fail('REFERENCE_INVALID', 'hypothesis 引用了不存在的 claim。')
    if package_status in {'DRAFT', 'REVIEWED'} and not claim_ids:
        _fail('HYPOTHESIS_INVALID', 'DRAFT/REVIEWED package 的假设必须回链 claim。')
    playbook_key = _text(item['playbook_key'], 'hypothesis.playbook_key', 64, required=False).lower()
    if playbook_key and not SLUG.fullmatch(playbook_key):
        _fail('HYPOTHESIS_INVALID', 'hypothesis.playbook_key 格式无效。')
    if _enum(item['status'], 'hypothesis.status', ('DRAFT',)) != 'DRAFT':
        _fail('HYPOTHESIS_INVALID', 'Research Skill 假设只能以 DRAFT 进入牛牛。')
    semantics = _text(item['score_semantics'], 'hypothesis.score_semantics', 80)
    if semantics != 'RESEARCH_HYPOTHESIS_NOT_ALPHA':
        _fail('HYPOTHESIS_INVALID', 'Research Skill hypothesis 不能声明 Alpha。')
    return {'hypothesis_key': key, 'title': _text(item['title'], 'hypothesis.title', 300),
        'status': 'DRAFT', 'claim_ids': claim_ids,
        'feature_candidates': _texts(item['feature_candidates'], 'feature_candidates', 50, 200, True),
        'required_data': _texts(item['required_data'], 'required_data', 50, 300, True),
        'target_horizon': _enum(item['target_horizon'], 'target_horizon', TARGET_HORIZONS),
        'playbook_key': playbook_key, 'score_semantics': semantics}


def _unique(items, key, name):
    values = [item[key] for item in items]
    if len(set(values)) != len(values):
        _fail('SCHEMA_INVALID', name + ' 不能包含重复标识。')


def _strategy_source_preview(root, manifest, snapshot, resources, source_ready):
    evidence = [item for item in resources.values() if item['role'] in EVIDENCE_ROLES]
    available = max((item['available_at'] for item in evidence if item['available_at']), default=None,
        key=lambda value: datetime.fromisoformat(value))
    primary = [item for item in evidence if item['role'] == 'PRIMARY_STATEMENT']
    locator = (primary[0]['locator'] if len(primary) == 1
        else f'research-skill://{manifest["skill_key"]}/{manifest["version"]}')
    content = {'source_key': manifest['skill_key'], 'source_kind': manifest['strategy_source_kind'],
        'title': manifest['title'], 'locator': locator, 'published_at': None, 'available_at': available,
        'content_hash': snapshot, 'archive_ref': str(root),
        'completeness': 'PARTIAL' if source_ready else 'PENDING',
        'notes': ('Research Skill 审计预览；仍需宿主复核并显式写入。来源不是规则，评分不是 Alpha。'
            + ' Keywords: ' + ', '.join(manifest['keywords'])),
        'evidence_ids': [f'research-skill:{snapshot}:{item["resource_id"]}' for item in evidence]}
    return normalize_strategy_source(content)


def audit_research_skill(package):
    """Audit one package without executing scripts, network access, or repository writes."""
    supplied = Path(package).expanduser()
    if supplied.is_symlink() or not supplied.is_dir():
        _fail('PACKAGE_INVALID', 'Research Skill package 不存在或为符号链接。')
    root = supplied.resolve()
    raw = _load_manifest(root)
    _object(raw, TOP_FIELDS, 'skill manifest')
    if raw['format'] != FORMAT:
        _fail('FORMAT_UNSUPPORTED', 'Research Skill format 不受支持。')
    skill_key = _slug(raw['skill_key'], 'skill_key')
    title = _text(raw['title'], 'title', 300)
    version = _text(raw['version'], 'version', 64)
    if not VERSION.fullmatch(version):
        _fail('SCHEMA_INVALID', 'version 格式无效。')
    status = _enum(raw['status'], 'status', STATUSES)
    source_kind = _enum(raw['strategy_source_kind'], 'strategy_source_kind', STRATEGY_SOURCE_KINDS)
    summary = _text(raw['summary'], 'summary', 4000)
    keywords = _texts(raw['keywords'], 'keywords', 50, 100, True)
    if raw['policy'] != REQUIRED_POLICY:
        _fail('POLICY_VIOLATION', 'Research Skill policy 必须保持无自动联网、无模型写入、无交易/Alpha/Strict PIT 资格。')

    if not isinstance(raw['resources'], list) or not 1 <= len(raw['resources']) <= MAX_RESOURCES:
        _fail('SCHEMA_INVALID', 'resources 必须包含 1～200 项。')
    resource_rows = [_read_resource(root, item) for item in raw['resources']]
    _unique(resource_rows, 'resource_id', 'resources.resource_id')
    _unique(resource_rows, 'path', 'resources.path')
    if sum(item['bytes'] for item in resource_rows) > MAX_PACKAGE_BYTES:
        _fail('BUDGET_EXCEEDED', 'Research Skill 已声明资源超过 32MB。')
    declared = {MANIFEST, *(item['path'] for item in resource_rows)}
    actual = _scan_files(root)
    if actual != declared:
        missing = sorted(declared - actual)
        undeclared = sorted(actual - declared)
        _fail('LAYOUT_INVALID', f'Research Skill 文件清单不闭合；missing={missing[:10]} undeclared={undeclared[:10]}')
    role_counts = {role: sum(item['role'] == role for item in resource_rows) for role in RESOURCE_ROLES}
    for role in ('BEHAVIOR_CONTRACT', 'METHOD', 'SCORECARD', 'SCRIPT_POLICY'):
        if role_counts[role] != 1:
            _fail('LAYOUT_INVALID', role + ' 必须且只能声明一次。')
    resources = {item['resource_id']: item for item in resource_rows}

    if not isinstance(raw['claims'], list) or len(raw['claims']) > 500:
        _fail('SCHEMA_INVALID', 'claims 必须是不超过 500 项的数组。')
    claim_rows = [_normalize_claim(item, resources) for item in raw['claims']]
    _unique(claim_rows, 'claim_id', 'claims.claim_id')
    claims = {item['claim_id']: item for item in claim_rows}
    if not isinstance(raw['alignments'], list) or len(raw['alignments']) > 500:
        _fail('SCHEMA_INVALID', 'alignments 必须是不超过 500 项的数组。')
    alignment_rows = [_normalize_alignment(item, claims, resources) for item in raw['alignments']]
    _unique(alignment_rows, 'alignment_id', 'alignments.alignment_id')
    if not isinstance(raw['hypotheses'], list) or len(raw['hypotheses']) > 100:
        _fail('SCHEMA_INVALID', 'hypotheses 必须是不超过 100 项的数组。')
    hypothesis_rows = [_normalize_hypothesis(item, claims, status) for item in raw['hypotheses']]
    _unique(hypothesis_rows, 'hypothesis_key', 'hypotheses.hypothesis_key')

    normalized = {'format': FORMAT, 'skill_key': skill_key, 'title': title, 'version': version,
        'status': status, 'strategy_source_kind': source_kind, 'summary': summary, 'keywords': keywords,
        'resources': resource_rows, 'claims': claim_rows, 'alignments': alignment_rows,
        'hypotheses': hypothesis_rows, 'policy': REQUIRED_POLICY}
    snapshot = digest(normalized)
    primary = role_counts['PRIMARY_STATEMENT']
    actions = role_counts['DISCLOSED_ACTION']
    outcomes = role_counts['REALIZED_OUTCOME']
    complete_triads = sum(bool(item['outcome_resource_ids']) for item in alignment_rows)
    publication_unverified = [item['resource_id'] for item in resource_rows
        if item['role'] in EVIDENCE_ROLES and item['timing_class'] != 'PUBLICATION_VERIFIED']
    source_claim_ids = {item['claim_id'] for item in claim_rows
        if any(resources[resource_id]['role'] == 'PRIMARY_STATEMENT' for resource_id in item['resource_ids'])}
    source_ready = primary > 0 and bool(source_claim_ids)
    method_ready = role_counts['METHOD'] == role_counts['SCORECARD'] == 1 and bool(hypothesis_rows)
    linked_hypotheses = bool(hypothesis_rows) and all(
        item['claim_ids'] and any(claim_id in source_claim_ids for claim_id in item['claim_ids'])
        for item in hypothesis_rows)
    say_do_applicable = source_kind == 'TRADER'
    say_do_ready = actions > 0 and bool(alignment_rows) if say_do_applicable else None
    outcome_linked = complete_triads > 0 if say_do_applicable else None
    blockers = []
    if not primary: blockers.append('primary_statement_missing')
    if not claim_rows: blockers.append('claim_layer_missing')
    elif not source_claim_ids: blockers.append('source_grounded_claim_missing')
    if not hypothesis_rows: blockers.append('playbook_hypothesis_missing')
    if say_do_applicable and not actions: blockers.append('disclosed_action_missing')
    if say_do_applicable and not alignment_rows: blockers.append('say_do_alignment_missing')
    if say_do_applicable and not outcomes: blockers.append('realized_outcome_missing')
    if say_do_applicable and not complete_triads: blockers.append('say_do_outcome_triad_missing')
    if publication_unverified: blockers.append('publication_time_unverified_resources')
    preview = _strategy_source_preview(root, normalized, snapshot, resources, source_ready)
    return {'format': AUDIT_FORMAT, 'valid': True, 'package_path': str(root),
        'package_snapshot': snapshot, 'skill_key': skill_key, 'title': title, 'version': version,
        'status': status, 'strategy_source_kind': source_kind, 'keywords': keywords,
        'counts': {'resources': len(resource_rows), 'primary_statements': primary,
            'disclosed_actions': actions, 'realized_outcomes': outcomes, 'claims': len(claim_rows),
            'source_grounded_claims': len(source_claim_ids), 'alignments': len(alignment_rows),
            'complete_say_do_outcome_triads': complete_triads,
            'hypotheses': len(hypothesis_rows), 'scripts': role_counts['SCRIPT']},
        'readiness': {'source_layer_ready': source_ready, 'method_layer_ready': method_ready,
            'hypotheses_linked_to_claims': linked_hypotheses,
            'say_do_applicable': say_do_applicable, 'say_do_ready': say_do_ready,
            'outcome_linked': outcome_linked,
            'playbook_draft_candidate_ready': source_ready and method_ready and linked_hypotheses,
            'quant_validation_completed': False},
        'blockers': blockers, 'publication_unverified_resource_ids': publication_unverified,
        'boundaries': {'automatic_store_write': False, 'automatic_playbook_creation': False,
            'scripts_executed': False, 'network_used': False, 'direct_trade_eligible': False,
            'daily_scanner_eligible': False, 'strict_pit_eligible': False, 'alpha_claimed': False,
            'quarterly_data_intraday_eligible': False,
            'institutional_data_role': 'THEME_DOSSIER_AUXILIARY_ONLY'},
        'strategy_source_preview': preview, 'hypothesis_candidates': hypothesis_rows,
        'scope': ('Read-only external knowledge adapter. Host review and existing StrategySource/'
            'Playbook/Qualification gates remain authoritative.')}


__all__ = ['FORMAT', 'AUDIT_FORMAT', 'REQUIRED_POLICY', 'ResearchSkillError', 'audit_research_skill']
