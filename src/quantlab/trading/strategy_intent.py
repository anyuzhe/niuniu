"""Validated Strategy Intent transitions driven by immutable Decisions."""
from __future__ import annotations

from uuid import UUID

from .decision import ACTIONS,business_order_key,normalize_decision
from .decision_store import DecisionError,DecisionStore

TRANSITION_VERSION='strategy-intent-v1'
INITIAL_ACTIONS=('DISCOVERED','WATCH')
ALLOWED={
    'DISCOVERED':{'DISCOVERED','WATCH','REJECTED','EXPIRED','INVALIDATED'},
    'WATCH':{'WATCH','READY','REJECTED','EXPIRED','INVALIDATED'},
    'READY':{'READY','WATCH','PLAN_OPEN','REJECTED','EXPIRED','INVALIDATED'},
    'PLAN_OPEN':{'PLAN_OPEN','READY','OPEN','REJECTED','EXPIRED','INVALIDATED'},
    'OPEN':{'OPEN','ADD','HOLD','REDUCE','EXIT','INVALIDATED'},
    'ADD':{'ADD','HOLD','REDUCE','EXIT','INVALIDATED'},
    'HOLD':{'HOLD','ADD','REDUCE','EXIT','INVALIDATED'},
    'REDUCE':{'REDUCE','HOLD','EXIT','INVALIDATED'},
    'EXIT':{'EXIT','DISCOVERED','WATCH'},
    'INVALIDATED':{'INVALIDATED','DISCOVERED','WATCH'},
    'REJECTED':{'REJECTED','DISCOVERED','WATCH'},
    'EXPIRED':{'EXPIRED','DISCOVERED','WATCH'},
}


def allowed_next(action=None):
    if action is None:return list(INITIAL_ACTIONS)
    if action not in ACTIONS:raise ValueError('未知策略动作。')
    return [value for value in ACTIONS if value in ALLOWED[action]]


def _reason(content):
    return (content.get('transition_reason') or content.get('ai_thesis') or content.get('machine_state') or content.get('theme_role') or '').strip()


class StrategyIntentService:
    def __init__(self,output,*,now_fn=None):
        self.store=DecisionStore(output,now_fn=now_fn)

    def timeline(self,symbol):
        return self.store.current_timeline(symbol)

    def current(self,symbol):
        rows=self.timeline(symbol)
        return rows[-1] if rows else None

    def state(self,symbol):
        current=self.current(symbol)
        return {
            'symbol':symbol.lower(),
            'current_decision':current,
            'current_action':current['action'] if current else None,
            'allowed_next':allowed_next(current['action'] if current else None),
            'transition_version':TRANSITION_VERSION,
            'position_scope':'strategy_intent',
        }

    @staticmethod
    def _check_transition(previous_action,next_action):
        if previous_action is None:
            return next_action in INITIAL_ACTIONS
        return next_action in ALLOWED[previous_action]

    @staticmethod
    def _uuid(value,name):
        try:
            if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise DecisionError('INVALID_ARGUMENT',name+' 需要规范 UUID。') from None
        return value

    def transition(self,request_id,content):
        try:normalized=normalize_decision(content)
        except ValueError as exc:raise DecisionError('INVALID_ARGUMENT',str(exc)) from None
        symbol=normalized['symbol'];rows=self.timeline(symbol);reason=_reason(normalized)
        revision_id=normalized.get('revision_of')
        if revision_id:
            self._uuid(revision_id,'revision_of')
            target=self.store.get(revision_id)
            if target.get('superseded_by'):
                raise DecisionError('STALE_REVISION','该 Decision 已有后续修订。')
            target_key=business_order_key(target)
            later=[row for row in rows if business_order_key(row)>target_key]
            before=[row for row in rows if business_order_key(row)<target_key]
            previous=before[-1] if before else None
            if normalized['action']!=target['action'] and later:
                raise DecisionError('HISTORICAL_STATE_REWRITE','后面已有 Decision 时，旧 Decision 的 revision 不能改变策略动作。')
            revision_kind='REVISION_SAME_STATE'
            if normalized['action']!=target['action']:
                if previous is None:
                    if normalized['action'] not in INITIAL_ACTIONS and not reason:
                        raise DecisionError('MISSING_BOOTSTRAP_REASON','首条 Decision 的动作修订为非发现/观察状态时必须保留原因。')
                    revision_kind='REVISION_BOOTSTRAP'
                else:
                    if not self._check_transition(previous['action'],normalized['action']):
                        raise DecisionError('INVALID_TRANSITION','修订后的动作不符合前序策略状态。')
                    revision_kind='REVISION_STATE_CHANGE'
                if not reason:raise DecisionError('MISSING_TRANSITION_REASON','改变策略动作必须保留转移理由。')
            enriched={**normalized,
                'transition_reason':reason or target.get('transition_reason',''),
                'intent_previous_decision_id':previous['decision_id'] if previous else None,
                'intent_previous_action':previous['action'] if previous else None,
                'intent_transition_version':TRANSITION_VERSION,
                'intent_transition_kind':revision_kind,
                'position_scope':'strategy_intent'}
            return self.store.create(request_id,enriched)

        new_key=business_order_key(normalized)
        same_slot=[row for row in rows if row['trading_day']==normalized['trading_day'] and row['frame']==normalized['frame']]
        if same_slot:
            raise DecisionError('FRAME_ALREADY_HAS_CURRENT_DECISION','同一证券/交易日/Frame 已有当前 Decision；请创建 revision。')
        earlier=[row for row in rows if business_order_key(row)<new_key]
        later=[row for row in rows if business_order_key(row)>new_key]
        if later:
            raise DecisionError('HISTORICAL_INSERT_BLOCKED','已有更晚业务时间的 Decision；不能事后插入新的历史状态，请修订旧 Decision 或在当前 Frame 新建纠正判断。')
        previous=earlier[-1] if earlier else None
        previous_action=previous['action'] if previous else None
        if previous is None and normalized['action'] not in INITIAL_ACTIONS:
            if not reason:raise DecisionError('MISSING_BOOTSTRAP_REASON','直接初始化为非发现/观察状态必须保留原因。')
            kind='BOOTSTRAP'
        else:
            if not self._check_transition(previous_action,normalized['action']):
                raise DecisionError('INVALID_TRANSITION',f'不允许从 {previous_action or "EMPTY"} 转移到 {normalized["action"]}。')
            kind='INITIAL' if previous is None else ('UNCHANGED' if previous_action==normalized['action'] else 'ADVANCE')
            if previous is not None and previous_action!=normalized['action'] and not reason:
                raise DecisionError('MISSING_TRANSITION_REASON','改变策略动作必须保留转移理由。')
        enriched={**normalized,
            'transition_reason':reason,
            'intent_previous_decision_id':previous['decision_id'] if previous else None,
            'intent_previous_action':previous_action,
            'intent_transition_version':TRANSITION_VERSION,
            'intent_transition_kind':kind,
            'position_scope':'strategy_intent'}
        return self.store.create(request_id,enriched)
