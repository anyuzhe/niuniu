"""Strict simulated-fill outcomes for Dynamic Paper rebalance plans."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from uuid import NAMESPACE_URL,uuid5
import fcntl

from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest
from .decision_store import DecisionError,DecisionStore
from .paper_fill_intent import _frame_for
from .paper_rebalance import PaperRebalanceError,PaperRebalancePlanService
from .strategy_intent import StrategyIntentService

FORMAT='paper-rebalance-outcome-v1'


class PaperRebalanceOutcomeError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


class PaperRebalanceOutcomeBridge:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise PaperRebalanceOutcomeError('INVALID_WORKSPACE','工作空间不存在。')
        self.root=self.output/'_trading'/'paper_rebalance_outcomes';self.plans=PaperRebalancePlanService(self.output)
        self.decisions=DecisionStore(self.output,now_fn=self.now_fn);self.intent=StrategyIntentService(self.output,now_fn=self.now_fn)

    def _path(self,plan_id):return self.root/(plan_id+'.json')
    @contextmanager
    def _locked(self,plan_id):
        if self.root.is_symlink():raise PaperRebalanceOutcomeError('INVALID_WORKSPACE','rebalance outcome 目录不能是符号链接。')
        self.root.mkdir(parents=True,exist_ok=True);lock=self.root/(plan_id+'.lock')
        if lock.is_symlink():raise PaperRebalanceOutcomeError('INVALID_WORKSPACE','rebalance outcome lock 不能是符号链接。')
        with lock.open('a+b') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise PaperRebalanceOutcomeError('BUSY','Rebalance outcome 正在处理。') from None
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def get(self,plan_id):
        path=self._path(plan_id)
        if not path.exists():raise PaperRebalanceOutcomeError('NOT_FOUND','Rebalance outcome receipt 不存在。')
        try:value=read_checked(path)
        except (OSError,ValueError) as exc:raise PaperRebalanceOutcomeError('CORRUPT_RECEIPT',str(exc)) from None
        return value

    @staticmethod
    def _existing(store,symbol,day,frame,request_id):
        rows=store.list(symbol=symbol,trading_day=day,frame=frame,include_superseded=True,limit=200)['records']
        return next((row for row in rows if row.get('request_id')==request_id),None)

    def apply(self,plan_id,*,confirmed=False):
        if confirmed is not True:raise PaperRebalanceOutcomeError('CONFIRMATION_REQUIRED','Rebalance fill→Intent 需要宿主显式确认。')
        try:plan=self.plans.get(plan_id)
        except PaperRebalanceError as exc:raise PaperRebalanceOutcomeError(exc.code,str(exc)) from None
        execution=plan.get('execution') or {}
        if execution.get('status')!='EXECUTED':raise PaperRebalanceOutcomeError('EXECUTION_REQUIRED','RebalancePlan 尚未完成模拟执行。')
        stamp=self.now_fn()
        if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise PaperRebalanceOutcomeError('INVALID_CLOCK','时钟必须带时区。')
        with self._locked(plan_id):
            path=self._path(plan_id)
            if path.exists():return self.get(plan_id)
            ending=execution.get('summary',{}).get('ending_positions',{});fills=execution.get('new_fills') or [];results=[]
            for change in plan['spec']['changes']:
                symbol=change['symbol'];side='buy' if change['kind']=='ADD' else 'sell'
                matching=[f for f in fills if f.get('symbol')==symbol and f.get('side')==side and f.get('quantity',0)>0]
                if not matching:
                    results.append({'symbol':symbol,'kind':change['kind'],'status':'NO_FILL','decision_id':None});continue
                fill=min(matching,key=lambda row:row['filled_at'])
                if change['kind']=='EXIT':
                    status='EXIT_POSITION_CONFIRMED' if not ending.get(symbol) else 'PARTIAL_EXIT'
                    results.append({'symbol':symbol,'kind':'EXIT','status':status,'decision_id':None,'fill':fill,
                        'ending_quantity':ending.get(symbol,0)});continue
                try:source=self.decisions.get(change['decision_id'])
                except DecisionError as exc:
                    results.append({'symbol':symbol,'kind':change['kind'],'status':'SOURCE_DECISION_MISSING','error_code':exc.code,'decision_id':None});continue
                target=_frame_for(datetime.fromisoformat(fill['filled_at']),source['frame'],source['trading_day'])
                if target is None:
                    results.append({'symbol':symbol,'kind':change['kind'],'status':'NO_LATER_FRAME','decision_id':None});continue
                day,frame=target;request_id=str(uuid5(NAMESPACE_URL,'niuniu-rebalance-outcome:'+digest({'plan_id':plan_id,'change':change,'fill':fill,'day':day,'frame':frame})))
                existing=self._existing(self.decisions,symbol,day,frame,request_id)
                if existing:
                    results.append({'symbol':symbol,'kind':change['kind'],'status':'HOLD_RECORDED','decision_id':existing['decision_id'],'fill':fill});continue
                current=self.intent.current(symbol)
                if not current or current['decision_id']!=change['decision_id'] or current['action']!=change['action']:
                    results.append({'symbol':symbol,'kind':change['kind'],'status':'STATE_MOVED','decision_id':None,
                        'current_decision_id':current['decision_id'] if current else None});continue
                if change['kind']=='REDUCE' and not ending.get(symbol):
                    results.append({'symbol':symbol,'kind':'REDUCE','status':'POSITION_EMPTY_AFTER_REDUCE','decision_id':None,'fill':fill});continue
                payload={'symbol':symbol,'trading_day':day,'frame':frame,'action':'HOLD','role_id':'system',
                    'ai_thesis':'Paper 模拟成交确认 '+change['kind']+' 已执行；继续持有状态只表示 Strategy Intent 生命周期，不是实盘持仓。',
                    'hold_reason':'动态 PaperAccount 在目标调整成交后仍有计划持仓。','transition_reason':change['kind']+' 模拟成交后回到 HOLD。',
                    'research_evidence_ids':['paper_rebalance:'+plan_id],'source':'paper_rebalance_outcome','effective_at':fill['filled_at']}
                try:decision=self.intent.transition(request_id,payload)
                except DecisionError as exc:
                    results.append({'symbol':symbol,'kind':change['kind'],'status':'TRANSITION_BLOCKED','error_code':exc.code,'error':str(exc)[:300],'decision_id':None});continue
                results.append({'symbol':symbol,'kind':change['kind'],'status':'HOLD_RECORDED','decision_id':decision['decision_id'],'fill':fill})
            receipt={'format':FORMAT,'plan_id':plan_id,'execution_hash':digest(execution),'created_at':stamp.astimezone(timezone.utc).isoformat(),
                'results':results,'automatic_real_trade':False};write_checked(path,receipt);return receipt


__all__=['FORMAT','PaperRebalanceOutcomeError','PaperRebalanceOutcomeBridge']
