"""Strict canonical contracts for Expert Playbook Lab records."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID
import re

from quantlab.storage.codec import encode
from .decision import FRAMES, SYMBOL

SOURCE_TYPES = ('PUBLIC_POST','LIVE_RECORD','BROKER_STATEMENT','INTERVIEW','VIDEO','OTHER')
SOURCE_COMPLETENESS = ('PENDING','PARTIAL','VERIFIED')
PLAYBOOK_STATES = ('DRAFT','FROZEN','RETIRED')
CANDIDATE_COMPLETENESS = ('UNKNOWN','PARTIAL','FULL')
PIT_STATUSES = ('UNKNOWN','RETROSPECTIVE_REFERENCE','STRICT_PIT')
SELECTION_KINDS = ('OBSERVED_EXPERT','HUMAN_RECONSTRUCTION','SYSTEM_PREDICTION')
VALIDATION_METHODS = ('RECONSTRUCTION','IN_SAMPLE','HOLDOUT','WALK_FORWARD')
SLUG = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
HASH = re.compile(r'^[0-9a-f]{64}$')
VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')

def _reject_extra(value, allowed, name):
    if not isinstance(value, dict):
        raise ValueError(name+' 必须是 JSON 对象。')
    extra = set(value)-set(allowed)
    if extra:
        raise ValueError(name+' 包含未知字段：'+','.join(sorted(extra)))


def _text(value, name, maximum=4000, required=False):
    if value is None:
        value = ''
    if not isinstance(value, str):
        raise ValueError(name+' 必须是文本。')
    value = value.strip()
    if required and not value:
        raise ValueError(name+' 不能为空。')
    if len(value) > maximum:
        raise ValueError(name+f' 不能超过 {maximum} 字。')
    return value


def _enum(value, name, options):
    value = _text(value, name, 80, True).upper()
    if value not in options:
        raise ValueError(name+' 取值无效。')
    return value

def _day(value, name='trading_day'):
    if not isinstance(value, str):
        raise ValueError(name+' 必须为 YYYY-MM-DD。')
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(name+' 必须为 YYYY-MM-DD。') from None


def _moment(value, name, required=True):
    if value in (None, '') and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(name+' 必须为 ISO 8601 时间。')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(name+' 必须为 ISO 8601 时间。') from None
    if parsed.tzinfo is None:
        raise ValueError(name+' 必须包含时区。')
    return parsed.isoformat()


def _uuid(value, name):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError(name+' 必须是规范 UUID。') from None
    return value

def _text_list(value, name, maximum=200, item_max=500):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(name+f' 必须是不超过 {maximum} 项的文本数组。')
    result = []
    for item in value:
        item = _text(item, name, item_max, True)
        if item in result:
            raise ValueError(name+' 不能包含重复项。')
        result.append(item)
    return result


def _uuid_list(value, name, maximum=200, required=False):
    result = _text_list(value, name, maximum, 64)
    if required and not result:
        raise ValueError(name+' 至少需要一项。')
    return [_uuid(item, name) for item in result]


def _symbols(value, name='symbols', maximum=5000):
    result = _text_list(value, name, maximum, 16)
    for symbol in result:
        if not SYMBOL.fullmatch(symbol.lower()):
            raise ValueError(name+' 只能包含 sh/sz/bj.XXXXXX。')
    return [symbol.lower() for symbol in result]

def _object(value, name, maximum=32000):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(name+' 必须是 JSON 对象。')
    try:
        size = len(encode(value).encode('utf-8'))
    except (TypeError, ValueError):
        raise ValueError(name+' 必须是可序列化且不含非有限数的 JSON 对象。') from None
    if size > maximum:
        raise ValueError(name+f' 不能超过 {maximum} 字节。')
    return value


def normalize_expert_source(content):
    allowed = ('expert_key','title','source_type','locator','published_at','available_at',
        'content_hash','archive_ref','completeness','notes')
    _reject_extra(content, allowed, 'ExpertSource')
    expert = _text(content.get('expert_key'), 'expert_key', 64, True).lower()
    if not SLUG.fullmatch(expert):
        raise ValueError('expert_key 只能使用小写字母、数字、下划线或连字符。')
    published = _moment(content.get('published_at'), 'published_at', False)
    available = _moment(content.get('available_at'), 'available_at', False)
    if published and available:
        if datetime.fromisoformat(available) < datetime.fromisoformat(published):
            raise ValueError('available_at 不能早于 published_at。')
    completeness = _enum(content.get('completeness','PENDING'), 'completeness', SOURCE_COMPLETENESS)
    content_hash = _text(content.get('content_hash'), 'content_hash', 64).lower()
    if content_hash and not HASH.fullmatch(content_hash):
        raise ValueError('content_hash 必须是 64 位小写 SHA256。')
    if completeness == 'VERIFIED' and (not available or not content_hash):
        raise ValueError('VERIFIED 来源必须保存 available_at 与 content_hash。')
    return {
        'expert_key': expert,
        'title': _text(content.get('title'), 'title', 300, True),
        'source_type': _enum(content.get('source_type'), 'source_type', SOURCE_TYPES),
        'locator': _text(content.get('locator'), 'locator', 2000, True),
        'published_at': published,
        'available_at': available,
        'content_hash': content_hash,
        'archive_ref': _text(content.get('archive_ref'), 'archive_ref', 2000),
        'completeness': completeness,
        'notes': _text(content.get('notes'), 'notes', 6000),
    }


def normalize_playbook_definition(content):
    allowed = ('playbook_key','name','version','state','source_ids','market_context','eligibility',
        'selection','veto','entry','confirm','invalidation','hold','add','reduce','exit','notes')
    _reject_extra(content, allowed, 'PlaybookDefinition')
    key = _text(content.get('playbook_key'), 'playbook_key', 64, True).lower()
    if not SLUG.fullmatch(key):
        raise ValueError('playbook_key 只能使用小写字母、数字、下划线或连字符。')
    version = _text(content.get('version'), 'version', 64, True)
    if not VERSION.fullmatch(version):
        raise ValueError('version 格式无效。')
    state = _enum(content.get('state','DRAFT'), 'state', PLAYBOOK_STATES)
    source_ids = _uuid_list(content.get('source_ids'), 'source_ids', 100)
    result = {
        'playbook_key': key,
        'name': _text(content.get('name'), 'name', 200, True),
        'version': version,
        'state': state,
        'source_ids': source_ids,
        'market_context': _object(content.get('market_context'), 'market_context'),
        'eligibility': _object(content.get('eligibility'), 'eligibility'),
        'selection': _object(content.get('selection'), 'selection'),
        'veto': _object(content.get('veto'), 'veto'),
        'entry': _object(content.get('entry'), 'entry'),
        'confirm': _object(content.get('confirm'), 'confirm'),
        'invalidation': _object(content.get('invalidation'), 'invalidation'),
        'hold': _object(content.get('hold'), 'hold'),
        'add': _object(content.get('add'), 'add'),
        'reduce': _object(content.get('reduce'), 'reduce'),
        'exit': _object(content.get('exit'), 'exit'),
        'notes': _text(content.get('notes'), 'notes', 8000),
    }
    if state == 'FROZEN':
        if not source_ids:
            raise ValueError('FROZEN Playbook 必须绑定至少一个可核验来源。')
        if not result['eligibility'] or not result['selection']:
            raise ValueError('FROZEN Playbook 必须冻结 eligibility 与 selection 规则。')
    return result


def normalize_playbook_case(content):
    allowed = ('definition_id','trading_day','frame','as_of','source_ids','summary','notes')
    _reject_extra(content, allowed, 'PlaybookCase')
    frame = _text(content.get('frame'), 'frame', 20, True).upper()
    if frame not in FRAMES:
        raise ValueError('未知 Decision Frame。')
    return {
        'definition_id': _uuid(content.get('definition_id'), 'definition_id'),
        'trading_day': _day(content.get('trading_day')),
        'frame': frame,
        'as_of': _moment(content.get('as_of'), 'as_of'),
        'source_ids': _uuid_list(content.get('source_ids'), 'source_ids', 100, True),
        'summary': _text(content.get('summary'), 'summary', 6000, True),
        'notes': _text(content.get('notes'), 'notes', 8000),
    }


def _candidate(item):
    allowed = ('symbol','eligibility_reasons','features','evidence_ids')
    _reject_extra(item, allowed, 'candidate')
    symbol = _text(item.get('symbol'), 'symbol', 16, True).lower()
    if not SYMBOL.fullmatch(symbol):
        raise ValueError('candidate.symbol 必须是 sh/sz/bj.XXXXXX。')
    reasons = _text_list(item.get('eligibility_reasons'), 'eligibility_reasons', 50, 500)
    if not reasons:
        raise ValueError('每个候选必须保留至少一条 eligibility_reasons。')
    return {
        'symbol': symbol,
        'eligibility_reasons': reasons,
        'features': _object(item.get('features'), 'features', 16000),
        'evidence_ids': _text_list(item.get('evidence_ids'), 'evidence_ids', 100, 300),
    }


def normalize_candidate_set(content):
    allowed = ('case_id','definition_id','trading_day','frame','as_of','completeness','pit_status',
        'universe_source','generation_method','candidates','evidence_ids')
    _reject_extra(content, allowed, 'CandidateSet')
    frame = _text(content.get('frame'), 'frame', 20, True).upper()
    if frame not in FRAMES:
        raise ValueError('未知 Decision Frame。')
    raw = content.get('candidates')
    if not isinstance(raw, list) or len(raw) > 5000:
        raise ValueError('candidates 必须是不超过 5000 项的数组。')
    candidates = [_candidate(item) for item in raw]
    symbols = [item['symbol'] for item in candidates]
    if len(set(symbols)) != len(symbols):
        raise ValueError('CandidateSet 不能包含重复证券。')
    completeness = _enum(content.get('completeness','UNKNOWN'), 'completeness', CANDIDATE_COMPLETENESS)
    universe_source = _text(content.get('universe_source'), 'universe_source', 2000)
    generation = _text(content.get('generation_method'), 'generation_method', 4000)
    if completeness == 'FULL' and (not universe_source or not generation):
        raise ValueError('FULL CandidateSet 必须说明 universe_source 与 generation_method。')
    return {
        'case_id': _uuid(content.get('case_id'), 'case_id'),
        'definition_id': _uuid(content.get('definition_id'), 'definition_id'),
        'trading_day': _day(content.get('trading_day')),
        'frame': frame,
        'as_of': _moment(content.get('as_of'), 'as_of'),
        'completeness': completeness,
        'pit_status': _enum(content.get('pit_status','UNKNOWN'), 'pit_status', PIT_STATUSES),
        'universe_source': universe_source,
        'generation_method': generation,
        'candidates': candidates,
        'evidence_ids': _text_list(content.get('evidence_ids'), 'evidence_ids', 200, 300),
    }


def normalize_selection(content):
    allowed = ('candidate_set_id','kind','selected_symbols','ranked_symbols','reasons','evidence_ids','as_of','notes')
    _reject_extra(content, allowed, 'SelectionDecision')
    selected = _symbols(content.get('selected_symbols'), 'selected_symbols')
    ranked = _symbols(content.get('ranked_symbols'), 'ranked_symbols')
    if ranked and any(symbol not in ranked for symbol in selected):
        raise ValueError('ranked_symbols 存在时必须包含全部 selected_symbols。')
    reasons = content.get('reasons') or {}
    if not isinstance(reasons, dict) or len(reasons) > 5000:
        raise ValueError('reasons 必须是证券到文本数组的对象。')
    normalized_reasons = {}
    for symbol, values in reasons.items():
        normalized = _symbols([symbol], 'reasons symbol')[0]
        normalized_reasons[normalized] = _text_list(values, 'reasons', 50, 500)
    return {
        'candidate_set_id': _uuid(content.get('candidate_set_id'), 'candidate_set_id'),
        'kind': _enum(content.get('kind'), 'kind', SELECTION_KINDS),
        'selected_symbols': selected,
        'ranked_symbols': ranked,
        'reasons': normalized_reasons,
        'evidence_ids': _text_list(content.get('evidence_ids'), 'evidence_ids', 200, 300),
        'as_of': _moment(content.get('as_of'), 'as_of'),
        'notes': _text(content.get('notes'), 'notes', 8000),
    }


def normalize_validation(content):
    allowed = ('definition_id','method','pairs','execution_evidence_ids','execution_summary','notes')
    _reject_extra(content, allowed, 'PlaybookValidation')
    raw_pairs = content.get('pairs')
    if not isinstance(raw_pairs, list) or not 1 <= len(raw_pairs) <= 1000:
        raise ValueError('pairs 必须包含 1–1000 个验证配对。')
    pairs = []
    for item in raw_pairs:
        _reject_extra(item, ('case_id','target_selection_id','model_selection_id'), 'validation pair')
        pair = {
            'case_id': _uuid(item.get('case_id'), 'case_id'),
            'target_selection_id': _uuid(item.get('target_selection_id'), 'target_selection_id'),
            'model_selection_id': _uuid(item.get('model_selection_id'), 'model_selection_id'),
        }
        if pair in pairs:
            raise ValueError('pairs 不能重复。')
        pairs.append(pair)
    return {
        'definition_id': _uuid(content.get('definition_id'), 'definition_id'),
        'method': _enum(content.get('method'), 'method', VALIDATION_METHODS),
        'pairs': pairs,
        'execution_evidence_ids': _text_list(content.get('execution_evidence_ids'), 'execution_evidence_ids', 200, 300),
        'execution_summary': _object(content.get('execution_summary'), 'execution_summary', 32000),
        'notes': _text(content.get('notes'), 'notes', 8000),
    }


__all__ = [
    'SOURCE_TYPES','SOURCE_COMPLETENESS','PLAYBOOK_STATES','CANDIDATE_COMPLETENESS',
    'PIT_STATUSES','SELECTION_KINDS','VALIDATION_METHODS','normalize_expert_source',
    'normalize_playbook_definition','normalize_playbook_case','normalize_candidate_set',
    'normalize_selection','normalize_validation',
]
