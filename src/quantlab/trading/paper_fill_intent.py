"""Strict bridge from simulated PaperPlan fills to Strategy Intent lifecycle state.

Only a host-confirmed simulated buy fill may advance the exact still-current
PLAN_OPEN Decision to OPEN.  Missing fills, stale states and human decisions are
preserved as non-transition outcomes.  This module never touches a broker.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import fcntl

from quantlab.experiments.campaign_state import read_checked, write_checked
from quantlab.storage.codec import digest
from .decision import FRAME_ORDER
from .decision_store import DecisionError, DecisionStore
from .playbook_paper_plan import PlaybookPaperPlanError, PlaybookPaperPlanService
from .strategy_intent import StrategyIntentService

FORMAT='paper-fill-intent-v1'


class PaperFillIntentError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _frame_for(moment,source_frame,source_day):
    day=moment.date().isoformat();clock=moment.timetz().replace(tzinfo=None)
    if clock<=time(10,30):frame='R1'
    elif clock<=time(13,30):frame='R2'
    else:frame='R3'
    if day==source_day and FRAME_ORDER[frame]<=FRAME_ORDER[source_frame]:
        later=[name for name in ('R1','R2','R3') if FRAME_ORDER[name]>FRAME_ORDER[source_frame]]
        if not later:return None
        frame=later[0]
    return day,frame


class PaperFillIntentBridge:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise PaperFillIntentError('INVALID_WORKSPACE','工作空间不存在。')
        self.root=self.output/'_trading'/'paper_fill_intent';self.plans=PlaybookPaperPlanService(self.output)
        self.decisions=DecisionStore(self.output,now_fn=self.now_fn);self.intent=StrategyIntentService(self.output,now_fn=self.now_fn)

    def _path(self,plan_id):return self.root/(plan_id+'.json')

    @contextmanager
    def _locked(self,plan_id):
        if self.root.is_symlink():raise PaperFillIntentError('INVALID_WORKSPACE','fill-intent 目录不能是符号链接。')
        self.root.mkdir(parents=True,exist_ok=True);lock=self.root/(plan_id+'.lock')
        if lock.is_symlink():raise PaperFillIntentError('INVALID_WORKSPACE','fill-intent lock 不能是符号链接。')
        with lock.open('a+b') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise PaperFillIntentError('BUSY','该 PaperPlan fill-intent 正在处理。') from None
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def get(self,plan_id):
        path=self._path(plan_id)
        if not path.exists():raise PaperFillIntentError('NOT_FOUND','fill-intent receipt 不存在。')
        try:value=read_checked(path)
        except (OSError,ValueError) as exc:raise PaperFillIntentError('CORRUPT_RECEIPT',str(exc)) from None
        if value.get('format')!=FORMAT or value.get('plan_id')!=plan_id:raise PaperFillIntentError('CORRUPT_RECEIPT','receipt 身份不一致。')
        return value

    @staticmethod
    def _existing_request(store,symbol,trading_day,frame,request_id):
        rows=store.list(symbol=symbol,trading_day=trading_day,frame=frame,include_superseded=True,limit=200)['records']
        return next((row for row in rows if row.get('request_id')==request_id),None)

    def apply(self,plan_id,*,confirmed=False):
        if confirmed is not True:raise PaperFillIntentError('CONFIRMATION_REQUIRED','fill→Intent 状态推进需要宿主显式确认。')
        try:plan=self.plans.get(plan_id)
        except PlaybookPaperPlanError as exc:raise PaperFillIntentError(exc.code,str(exc)) from None
        execution=plan.get('execution') or {}
        if execution.get('status')!='EXECUTED':raise PaperFillIntentError('EXECUTION_REQUIRED','PaperPlan 必须先完成模拟执行。')
        stamp=self.now_fn()
        if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise PaperFillIntentError('INVALID_CLOCK','时钟必须带时区。')
        with self._locked(plan_id):
            path=self._path(plan_id)
            if path.exists():return self.get(plan_id)
            fills=execution.get('new_fills') or [];spec=plan['spec'];rows=[]
            for symbol,source_decision_id in spec['decision_ids'].items():
                buys=[row for row in fills if row.get('symbol')==symbol and row.get('side')=='buy' and row.get('quantity',0)>0]
                if not buys:
                    rows.append({'symbol':symbol,'status':'NO_FILL','source_decision_id':source_decision_id,'decision_id':None})
                    continue
                fill=min(buys,key=lambda row:row['filled_at']);moment=datetime.fromisoformat(fill['filled_at'])
                try:source_decision=self.decisions.get(source_decision_id)
                except DecisionError as exc:
                    rows.append({'symbol':symbol,'status':'SOURCE_DECISION_MISSING','source_decision_id':source_decision_id,
                        'error_code':exc.code,'decision_id':None});continue
                target=_frame_for(moment,source_decision['frame'],source_decision['trading_day'])
                if target is None:
                    rows.append({'symbol':symbol,'status':'NO_LATER_FRAME','source_decision_id':source_decision_id,'decision_id':None})
                    continue
                trading_day,frame=target
                request_id=str(uuid5(NAMESPACE_URL,'niuniu-paper-fill-intent:'+digest({'plan_id':plan_id,'symbol':symbol,
                    'source_decision_id':source_decision_id,'fill':fill,'trading_day':trading_day,'frame':frame})))
                existing=self._existing_request(self.decisions,symbol,trading_day,frame,request_id)
                if existing:
                    rows.append({'symbol':symbol,'status':'OPEN_RECORDED','source_decision_id':source_decision_id,
                        'decision_id':existing['decision_id'],'request_id':request_id,'fill':fill});continue
                current=self.intent.current(symbol)
                if not current or current['decision_id']!=source_decision_id or current['action']!='PLAN_OPEN':
                    rows.append({'symbol':symbol,'status':'STATE_MOVED','source_decision_id':source_decision_id,
                        'current_decision_id':current['decision_id'] if current else None,'decision_id':None})
                    continue
                same_slot=self.decisions.list(symbol=symbol,trading_day=trading_day,frame=frame,include_superseded=False,limit=20)['records']
                if same_slot:
                    rows.append({'symbol':symbol,'status':'FRAME_OCCUPIED','source_decision_id':source_decision_id,
                        'current_frame_decision_id':same_slot[0]['decision_id'],'decision_id':None,'fill':fill});continue
                rejected=any(o.get('status')=='remainder_rejected' and o.get('symbol')==symbol for o in execution.get('new_orders',[]))
                payload={'symbol':symbol,'trading_day':trading_day,'frame':frame,'action':'OPEN','role_id':'system',
                    'ai_thesis':'Paper 模拟成交回执确认 PLAN_OPEN 已产生买入成交；这不是实盘券商持仓。',
                    'confirm_trigger':'paper_fill:'+str(fill.get('filled_at')),'hold_reason':'Paper position 已由模拟成交引擎建立。',
                    'transition_reason':'Paper 模拟 buy fill 驱动策略生命周期从 PLAN_OPEN → OPEN。',
                    'research_evidence_ids':['paper_plan:'+plan_id,'paper_order:'+str(next((o.get('order_id') for o in execution.get('new_orders',[]) if o.get('status')=='filled' and o.get('symbol')==symbol and o.get('filled_at')==fill.get('filled_at')), 'unknown'))[:120]],
                    'risk_flags':['paper_partial_fill'] if rejected else [],'source':'paper_fill_intent_bridge','effective_at':fill['filled_at']}
                try:decision=self.intent.transition(request_id,payload)
                except DecisionError as exc:
                    rows.append({'symbol':symbol,'status':'TRANSITION_BLOCKED','source_decision_id':source_decision_id,
                        'error_code':exc.code,'error':str(exc)[:300],'decision_id':None,'fill':fill});continue
                rows.append({'symbol':symbol,'status':'OPEN_RECORDED','source_decision_id':source_decision_id,
                    'decision_id':decision['decision_id'],'request_id':request_id,'fill':fill})
            receipt={'format':FORMAT,'plan_id':plan_id,'paper_execution_hash':digest(execution),'created_at':stamp.astimezone(timezone.utc).isoformat(),
                'results':rows,'open_recorded':sum(row['status']=='OPEN_RECORDED' for row in rows),
                'no_fill':sum(row['status']=='NO_FILL' for row in rows),'automatic_real_trade':False}
            write_checked(path,receipt);return receipt


__all__=['FORMAT','PaperFillIntentError','PaperFillIntentBridge']
