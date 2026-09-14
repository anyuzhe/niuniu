"""Validated immutable decision payloads for the A-share trading desk."""
from __future__ import annotations

from datetime import date, datetime
import re

FRAMES = ('PREP','AUCTION','R1','R2','R3','D1','D2','D3_PLUS')
FRAME_ORDER={name:index for index,name in enumerate(FRAMES)}
ACTIONS = (
    'DISCOVERED','WATCH','READY','PLAN_OPEN','OPEN','ADD','HOLD','REDUCE','EXIT',
    'INVALIDATED','REJECTED','EXPIRED',
)
ROLES = ('human','system','chief_researcher','market_scanner','skeptic','quant_researcher','developer')
SYMBOL = re.compile(r'^(?:sh|sz|bj)\.\d{6}$')
TEXT_FIELDS = (
    'theme','theme_role','machine_state','ai_thesis','buy_zone','confirm_trigger',
    'invalidation','hold_reason','add_condition','reduce_condition','exit_condition',
)


def _text(value, name, maximum=4000):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError(f'{name} 必须是文本。')
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f'{name} 不能超过 {maximum} 字。')
    return value


def _iso_day(value):
    if not isinstance(value, str):
        raise ValueError('trading_day 必须为 YYYY-MM-DD。')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError('trading_day 必须为 YYYY-MM-DD。') from None
    return parsed.isoformat()


def _optional_iso_datetime(value, name):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise ValueError(f'{name} 必须为 ISO 8601 时间。')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'{name} 必须为 ISO 8601 时间。') from None
    if parsed.tzinfo is None:
        raise ValueError(f'{name} 必须包含时区。')
    return parsed.isoformat()


def business_order_key(value):
    return (value.get('trading_day',''),FRAME_ORDER.get(value.get('frame'),-1),value.get('submitted_at',''))


def _string_list(value, name, maximum=100):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f'{name} 必须是不超过 {maximum} 项的文本数组。')
    result = []
    for item in value:
        text = _text(item, name, 200)
        if not text:
            raise ValueError(f'{name} 不能包含空值。')
        if text not in result:
            result.append(text)
    return result


def normalize_decision(content):
    """Return a bounded canonical payload; timestamps/IDs are added by the store."""
    if not isinstance(content, dict):
        raise ValueError('Decision 内容必须是对象。')
    symbol = _text(content.get('symbol'), 'symbol', 16).lower()
    if not SYMBOL.fullmatch(symbol):
        raise ValueError('symbol 必须是 sh/sz/bj.XXXXXX。')
    frame = _text(content.get('frame'), 'frame', 20).upper()
    action = _text(content.get('action'), 'action', 30).upper()
    if frame not in FRAMES:
        raise ValueError('未知 Decision Frame。')
    if action not in ACTIONS:
        raise ValueError('未知策略动作。')
    role_id = _text(content.get('role_id', 'human'), 'role_id', 40).lower()
    if role_id not in ROLES:
        raise ValueError('未知 role_id。')
    result = {
        'symbol': symbol,
        'trading_day': _iso_day(content.get('trading_day')),
        'frame': frame,
        'action': action,
        'role_id': role_id,
        'agent_id': _text(content.get('agent_id'), 'agent_id', 100),
        'model_provider': _text(content.get('model_provider'), 'model_provider', 100),
        'model_id': _text(content.get('model_id'), 'model_id', 120),
        'prompt_version': _text(content.get('prompt_version'), 'prompt_version', 120),
        'market_snapshot_id': _text(content.get('market_snapshot_id'), 'market_snapshot_id', 200),
        'rule_snapshot_id': _text(content.get('rule_snapshot_id'), 'rule_snapshot_id', 200),
        'research_evidence_ids': _string_list(content.get('research_evidence_ids'), 'research_evidence_ids'),
        'risk_flags': _string_list(content.get('risk_flags'), 'risk_flags', 50),
        'revision_of': _text(content.get('revision_of'), 'revision_of', 64) or None,
        'reference_decision_id': _text(content.get('reference_decision_id'), 'reference_decision_id', 64) or None,
        'transition_reason': _text(content.get('transition_reason'), 'transition_reason', 2000),
        'intent_previous_decision_id': _text(content.get('intent_previous_decision_id'), 'intent_previous_decision_id', 64) or None,
        'intent_previous_action': _text(content.get('intent_previous_action'), 'intent_previous_action', 30).upper() or None,
        'intent_transition_version': _text(content.get('intent_transition_version'), 'intent_transition_version', 120),
        'intent_transition_kind': _text(content.get('intent_transition_kind'), 'intent_transition_kind', 80),
        'position_scope': _text(content.get('position_scope'), 'position_scope', 80),
        'outcome': _text(content.get('outcome'), 'outcome', 4000),
        'source': _text(content.get('source', 'manual'), 'source', 80) or 'manual',
        'effective_at': _optional_iso_datetime(content.get('effective_at'), 'effective_at'),
    }
    for name in TEXT_FIELDS:
        result[name] = _text(content.get(name), name)
    if result['intent_previous_action'] is not None and result['intent_previous_action'] not in ACTIONS:
        raise ValueError('未知 intent_previous_action。')
    if action in ('PLAN_OPEN','OPEN','ADD') and not (result['confirm_trigger'] or result['buy_zone']):
        raise ValueError('计划开仓/开仓/加仓至少需要 buy_zone 或 confirm_trigger。')
    if action in ('OPEN','ADD','HOLD') and not (result['hold_reason'] or result['ai_thesis'] or result['machine_state']):
        raise ValueError('开仓/加仓/持有必须保留持有依据。')
    if action in ('REDUCE','EXIT','INVALIDATED') and not (result['exit_condition'] or result['invalidation'] or result['ai_thesis']):
        raise ValueError('减仓/退出/失效必须保留原因或条件。')
    return result
