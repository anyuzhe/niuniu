"""Validated A-share theme snapshots; facts, machine state and AI judgment stay separate."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID
import math

from .decision import FRAMES

THEME_STATES = ('UNKNOWN','PREHEAT','START','MAIN_RISE','DIVERGENCE','REPAIR','ACCELERATION','OVERHEAT','DECLINE')
FACT_FIELDS = {
    'constituents': int,
    'active_constituents': int,
    'limit_up_count': int,
    'limit_down_count': int,
    'twenty_cm_limit_up_count': int,
    'breadth_up': int,
    'breadth_down': int,
    'amount_billion': float,
    'leader_return': float,
    'leader_symbol': str,
    'note': str,
}


def _text(value,name,maximum=4000):
    if value is None:return ''
    if not isinstance(value,str):raise ValueError(f'{name} 必须是文本。')
    value=value.strip()
    if len(value)>maximum:raise ValueError(f'{name} 不能超过 {maximum} 字。')
    return value


def _day(value):
    if not isinstance(value,str):raise ValueError('trading_day 必须为 YYYY-MM-DD。')
    try:return date.fromisoformat(value).isoformat()
    except ValueError:raise ValueError('trading_day 必须为 YYYY-MM-DD。') from None


def _aware_time(value,name):
    if value in (None,''):return None
    if not isinstance(value,str):raise ValueError(f'{name} 必须为 ISO 8601 时间。')
    try:parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError(f'{name} 必须为 ISO 8601 时间。') from None
    if parsed.tzinfo is None:raise ValueError(f'{name} 必须包含时区。')
    return parsed.isoformat()


def _ids(value,name,maximum=100):
    if value is None:return []
    if not isinstance(value,list) or len(value)>maximum:raise ValueError(f'{name} 必须是不超过 {maximum} 项的 UUID 数组。')
    result=[]
    for item in value:
        try:
            if not isinstance(item,str) or str(UUID(item))!=item:raise ValueError()
        except (ValueError,TypeError,AttributeError):raise ValueError(f'{name} 必须只包含规范 UUID。') from None
        if item not in result:result.append(item)
    return result


def _facts(value):
    if value is None:return {}
    if not isinstance(value,dict) or set(value)-set(FACT_FIELDS):raise ValueError('facts 含未知字段。')
    result={}
    for key,item in value.items():
        if item is None:continue
        expected=FACT_FIELDS[key]
        if expected is int:
            if type(item) is not int or item<0:raise ValueError(key+' 必须是非负整数。')
        elif expected is float:
            if type(item) not in (int,float) or not math.isfinite(item):raise ValueError(key+' 必须是有限数值。')
            item=float(item)
        else:
            item=_text(item,key,400 if key=='note' else 40)
            if not item:continue
        result[key]=item
    return result


def normalize_theme_snapshot(content):
    if not isinstance(content,dict):raise ValueError('Theme Snapshot 内容必须是对象。')
    theme=_text(content.get('theme'),'theme',100)
    if not theme:raise ValueError('theme 不能为空。')
    frame=_text(content.get('frame'),'frame',20).upper()
    if frame not in FRAMES:raise ValueError('未知 Decision Frame。')
    machine_state=_text(content.get('machine_state','UNKNOWN'),'machine_state',30).upper() or 'UNKNOWN'
    ai_state=_text(content.get('ai_state','UNKNOWN'),'ai_state',30).upper() or 'UNKNOWN'
    if machine_state not in THEME_STATES or ai_state not in THEME_STATES:raise ValueError('未知主题状态。')
    facts=_facts(content.get('facts'))
    facts_source=_text(content.get('facts_source'),'facts_source',300)
    facts_as_of=_aware_time(content.get('facts_as_of'),'facts_as_of')
    if facts and (not facts_source or facts_as_of is None):
        raise ValueError('存在 market facts 时必须同时保存 facts_source 与带时区 facts_as_of。')
    return {
        'theme':theme,'trading_day':_day(content.get('trading_day')),'frame':frame,
        'machine_state':machine_state,'ai_state':ai_state,'facts':facts,
        'facts_source':facts_source,'facts_as_of':facts_as_of,
        'machine_rule':_text(content.get('machine_rule'),'machine_rule',500),
        'machine_rule_version':_text(content.get('machine_rule_version'),'machine_rule_version',120),
        'quant_evidence_ids':_ids(content.get('quant_evidence_ids'),'quant_evidence_ids'),
        'decision_ids':_ids(content.get('decision_ids'),'decision_ids'),
        'ai_thesis':_text(content.get('ai_thesis'),'ai_thesis'),
        'risk_review':_text(content.get('risk_review'),'risk_review'),
        'revision_of':_text(content.get('revision_of'),'revision_of',64) or None,
        'source':_text(content.get('source','manual_host'),'source',80) or 'manual_host',
    }
