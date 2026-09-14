"""Host-confirmed rebalance plans for an existing DynamicPaperAccount.

New entries are intentionally excluded: a symbol with zero prior target must first
enter through a Playbook PaperPlan.  This service covers ADD / REDUCE / EXIT /
INVALIDATED intent changes for symbols already known by the long paper account.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from uuid import NAMESPACE_URL,UUID,uuid5
import fcntl,math,re

import polars as pl

from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.dynamic_paper import DynamicPaperAccount,DynamicPaperError
from quantlab.execution.rules import MarketRules
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest
from .decision_store import DecisionError,DecisionStore
from .strategy_intent import StrategyIntentService

FORMAT='paper-rebalance-plan-v1'
ACCOUNT=re.compile(r'^[A-Za-z0-9_-]{1,80}$')
SYMBOL=re.compile(r'^(?:sh|sz|bj)\.\d{6}$')


class PaperRebalanceError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _uuid(value,name):
    try:
        if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise PaperRebalanceError('INVALID_ARGUMENT',name+' 需要规范 UUID。') from None
    return value


def _weights(value):
    if not isinstance(value,dict) or len(value)>5000:raise PaperRebalanceError('INVALID_TARGET','target_weights 必须是对象。')
    result={}
    for key,raw in value.items():
        symbol=key.lower() if isinstance(key,str) else ''
        if not SYMBOL.fullmatch(symbol) or type(raw) not in (int,float) or not math.isfinite(raw) or not 0<=raw<=1:
            raise PaperRebalanceError('INVALID_TARGET','目标证券或权重无效。')
        if raw>0:result[symbol]=float(raw)
    if sum(result.values())>1+1e-12:raise PaperRebalanceError('INVALID_TARGET','目标权重合计不能超过1。')
    return result


class PaperRebalancePlanService:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise PaperRebalanceError('INVALID_WORKSPACE','工作空间不存在。')
        self.root=self.output/'_trading'/'paper_rebalances';self.decisions=DecisionStore(self.output,now_fn=self.now_fn)
        self.intent=StrategyIntentService(self.output,now_fn=self.now_fn)

    def _account_path(self,name):return self.output/'paper_dynamic'/(name+'.json')
    def _path(self,plan_id):return self.root/(_uuid(plan_id,'plan_id')+'.json')

    @contextmanager
    def _locked(self,plan_id):
        if self.root.is_symlink():raise PaperRebalanceError('INVALID_WORKSPACE','rebalance 目录不能是符号链接。')
        self.root.mkdir(parents=True,exist_ok=True);lock=self.root/(plan_id+'.lock')
        if lock.is_symlink():raise PaperRebalanceError('INVALID_WORKSPACE','rebalance lock 不能是符号链接。')
        with lock.open('a+b') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise PaperRebalanceError('BUSY','RebalancePlan 正在处理。') from None
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def _load(self,plan_id):
        path=self._path(plan_id)
        if not path.exists():raise PaperRebalanceError('NOT_FOUND','RebalancePlan 不存在。')
        try:value=read_checked(path)
        except (OSError,ValueError) as exc:raise PaperRebalanceError('CORRUPT_PLAN',str(exc)) from None
        if value.get('format')!=FORMAT or value.get('plan_id')!=plan_id:raise PaperRebalanceError('CORRUPT_PLAN','RebalancePlan 身份不一致。')
        return value

    def get(self,plan_id):
        with self._locked(_uuid(plan_id,'plan_id')):return self._load(plan_id)

    def list(self,limit=1000):
        if type(limit) is not int or not 1<=limit<=5000:raise PaperRebalanceError('INVALID_ARGUMENT','limit 必须为1–5000。')
        if not self.root.exists():return []
        rows=[]
        for path in sorted(self.root.glob('*.json')):
            try:rows.append(self._load(path.stem))
            except PaperRebalanceError:continue
            if len(rows)>=limit:break
        return rows

    def create(self,account_name,decision_ids,target_weights,*,confirmed=False):
        if confirmed is not True:raise PaperRebalanceError('CONFIRMATION_REQUIRED','创建 RebalancePlan 需要宿主显式确认。')
        if not isinstance(account_name,str) or not ACCOUNT.fullmatch(account_name):raise PaperRebalanceError('INVALID_ARGUMENT','account_name 无效。')
        if not isinstance(decision_ids,list) or not decision_ids or len(decision_ids)>500 or len(set(decision_ids))!=len(decision_ids):
            raise PaperRebalanceError('INVALID_ARGUMENT','decision_ids 必须是非空不重复 UUID 数组。')
        target=_weights(target_weights);account_path=self._account_path(account_name)
        if not account_path.exists():raise PaperRebalanceError('ACCOUNT_NOT_FOUND','长期动态 PaperAccount 不存在。')
        try:account=DynamicPaperAccount(account_path).read()
        except DynamicPaperError as exc:raise PaperRebalanceError(exc.code,str(exc)) from None
        current=dict(account.get('target_events',[])[-1]['weights']) if account.get('target_events') else {}
        if set(target)-set(account.get('universe_symbols',[])):raise PaperRebalanceError('NEW_ENTRY_REQUIRES_PLAYBOOK_PLAN','RebalancePlan 不能引入新证券。')
        changed={symbol:(current.get(symbol,0.0),target.get(symbol,0.0)) for symbol in sorted(set(current)|set(target))
            if abs(current.get(symbol,0.0)-target.get(symbol,0.0))>1e-12}
        if not changed:raise PaperRebalanceError('NO_CHANGE','目标组合与当前目标一致。')
        decisions={}
        for decision_id in decision_ids:
            try:decision=self.decisions.get(_uuid(decision_id,'decision_id'))
            except DecisionError as exc:raise PaperRebalanceError(exc.code,str(exc)) from None
            current_decision=self.intent.current(decision['symbol'])
            if decision.get('superseded_by') or not current_decision or current_decision['decision_id']!=decision['decision_id']:
                raise PaperRebalanceError('DECISION_NOT_CURRENT','RebalancePlan 只能绑定当前 Strategy Intent Decision。')
            if decision['symbol'] in decisions:raise PaperRebalanceError('DUPLICATE_SYMBOL_DECISION','每个证券只能绑定一个 Decision。')
            decisions[decision['symbol']]=decision
        if set(decisions)!=set(changed):raise PaperRebalanceError('DECISION_COVERAGE','每个权重变化证券都必须且只能绑定一个当前 Decision。')
        change_rows=[]
        for symbol,(old,new) in changed.items():
            action=decisions[symbol]['action']
            if old<=0<new:raise PaperRebalanceError('NEW_ENTRY_REQUIRES_PLAYBOOK_PLAN','新开仓必须走 Playbook PaperPlan。')
            if new>old:required={'ADD'};kind='ADD'
            elif new==0:required={'EXIT','INVALIDATED'};kind='EXIT'
            else:required={'REDUCE'};kind='REDUCE'
            if action not in required:raise PaperRebalanceError('ACTION_MISMATCH',f'{symbol} {old}->{new} 需要 {sorted(required)} Decision。')
            change_rows.append({'symbol':symbol,'from_weight':old,'to_weight':new,'kind':kind,'decision_id':decisions[symbol]['decision_id'],
                'decision_hash':digest({k:v for k,v in decisions[symbol].items() if k!='superseded_by'}),'action':action})
        target_at=max(datetime.fromisoformat(row['submitted_at']) for row in decisions.values())
        spec={'account_name':account_name,'account_identity_hash':digest(account['identity']),'account_target_hash':digest(current),
            'current_target':current,'target_weights':target,'target_at':target_at.isoformat(),'changes':change_rows,
            'policy':'Full desired portfolio; existing symbols only; ADD/REDUCE/EXIT validated against current Strategy Intent.'}
        spec_hash=digest(spec);plan_id=str(uuid5(NAMESPACE_URL,'niuniu-paper-rebalance:'+spec_hash));stamp=self.now_fn()
        if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise PaperRebalanceError('INVALID_CLOCK','时钟必须带时区。')
        with self._locked(plan_id):
            path=self._path(plan_id)
            if path.exists():return self._load(plan_id)
            state={'format':FORMAT,'plan_id':plan_id,'spec_hash':spec_hash,'spec':spec,'status':'PENDING_MARKET_INPUT',
                'created_at':stamp.astimezone(timezone.utc).isoformat(),'updated_at':stamp.astimezone(timezone.utc).isoformat(),'execution':None}
            write_checked(path,state);return state

    def _revalidate(self,state,allow_committed_target=False):
        spec=state['spec'];account=DynamicPaperAccount(self._account_path(spec['account_name'])).read()
        current=dict(account.get('target_events',[])[-1]['weights']) if account.get('target_events') else {}
        valid_targets={spec['account_target_hash']}
        if allow_committed_target:valid_targets.add(digest(spec['target_weights']))
        if digest(account['identity'])!=spec['account_identity_hash'] or digest(current) not in valid_targets:
            raise PaperRebalanceError('ACCOUNT_MOVED','创建计划后动态账户身份或目标出现非本计划变化。')
        for change in spec['changes']:
            try:decision=self.decisions.get(change['decision_id'])
            except DecisionError as exc:raise PaperRebalanceError(exc.code,str(exc)) from None
            current_decision=self.intent.current(change['symbol'])
            if decision.get('superseded_by') or not current_decision or current_decision['decision_id']!=decision['decision_id'] or \
                    digest({k:v for k,v in decision.items() if k!='superseded_by'})!=change['decision_hash']:
                raise PaperRebalanceError('SOURCE_CHANGED','Rebalance Decision 已变化或不再是当前状态。')
        return account

    def execute(self,plan_id,bars,rules,config=None,backend='open',*,as_of=None,confirmed=False):
        if confirmed is not True:raise PaperRebalanceError('CONFIRMATION_REQUIRED','执行 RebalancePlan 需要宿主显式确认。')
        if not isinstance(bars,pl.DataFrame) or bars.is_empty() or not isinstance(rules,MarketRules):
            raise PaperRebalanceError('INVALID_MARKET_INPUT','需要非空 bars 与 MarketRules。')
        stamp=as_of or self.now_fn()
        if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise PaperRebalanceError('INVALID_CLOCK','时钟必须带时区。')
        with self._locked(_uuid(plan_id,'plan_id')):
            state=self._load(plan_id);spec=state['spec'];account_path=self._account_path(spec['account_name']);existing=state.get('execution')
            if existing and existing.get('status')=='EXECUTED':return state
            before=self._revalidate(state,allow_committed_target=bool(existing))
            cfg=config or ExecutionConfig(**before['identity']['config']);mode=before['identity']['backend']
            if backend!=mode:raise PaperRebalanceError('ACCOUNT_IDENTITY_CHANGED','backend 必须与长期账户一致。')
            execution_spec={'bars_hash':digest(bars.write_json()),'rules_snapshot_id':rules.snapshot_id,'config':asdict(cfg),
                'backend':backend,'as_of':stamp.isoformat(),'target_weights':spec['target_weights']};request_hash=digest(execution_spec)
            if existing and existing.get('request_hash')!=request_hash:raise PaperRebalanceError('EXECUTION_CONFLICT','RebalancePlan 已预留不同执行输入。')
            if existing is None:
                state['execution']={'status':'RESERVED','request_hash':request_hash,'spec':execution_spec,'reserved_at':stamp.isoformat(),
                    'before_order_ids':sorted(o['order_id'] for o in before.get('orders',[])),'before_fill_count':len(before.get('fills',[])),
                    'before_account_revision':before.get('revision',0)};state['status']='EXECUTION_RESERVED';state['updated_at']=stamp.isoformat();write_checked(self._path(plan_id),state);existing=state['execution']
            dynamic=DynamicPaperAccount(account_path)
            try:paper=dynamic.advance(bars,rules,cfg,backend,as_of=stamp,target_at=datetime.fromisoformat(spec['target_at']),
                target_weights=spec['target_weights'],target_source_ref='rebalance_plan:'+plan_id)
            except (DynamicPaperError,OSError,ValueError,KeyError,TypeError) as exc:
                state=self._load(plan_id);state['execution'].update(status='FAILED',error=type(exc).__name__+': '+str(exc)[:400]);state['status']='EXECUTION_FAILED';
                state['updated_at']=stamp.isoformat();write_checked(self._path(plan_id),state);raise PaperRebalanceError('PAPER_EXECUTION_FAILED',str(exc)) from None
            before_orders=set(existing.get('before_order_ids',[]));before_fills=existing.get('before_fill_count',0)
            new_orders=[o for o in paper.get('orders',[]) if o['order_id'] not in before_orders];new_fills=paper.get('fills',[])[before_fills:]
            state=self._load(plan_id);state['execution'].update(status='EXECUTED',account_path=str(account_path),account_revision=paper['revision'],
                new_order_ids=[o['order_id'] for o in new_orders],new_orders=new_orders,new_fills=new_fills,summary=paper['summary'],executed_at=stamp.isoformat())
            state['status']='EXECUTED_WITH_FILL' if new_fills else 'EXECUTED_NO_FILL';state['updated_at']=stamp.isoformat();write_checked(self._path(plan_id),state);return state


__all__=['FORMAT','PaperRebalanceError','PaperRebalancePlanService']
