"""Explicit PaperPlan bridge from PLAN_OPEN Decisions to the existing PaperAccount.

A plan is not a fill. Execution requires completed bars and explicit dated MarketRules.
The current PaperAccount has a fixed-universe contract, so P8.8 v1 freezes the
selection's selected symbols as the account universe and rejects incompatible accounts.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from uuid import NAMESPACE_URL,UUID,uuid5
import fcntl,re

import polars as pl

from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.paper import PaperAccount
from quantlab.execution.rules import MarketRules
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest
from .decision import FRAME_ORDER
from .decision_store import DecisionError,DecisionStore
from .playbook_store import PlaybookError,PlaybookStore

FORMAT='playbook-paper-plan-v1'
ACCOUNT=re.compile(r'^[A-Za-z0-9_-]{1,80}$')


class PlaybookPaperPlanError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _uuid(value,name):
    try:
        if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise PlaybookPaperPlanError('INVALID_ARGUMENT',name+' 需要规范 UUID。') from None
    return value


def _stamp(value,name='as_of'):
    if not isinstance(value,datetime) or value.tzinfo is None:
        raise PlaybookPaperPlanError('INVALID_CLOCK',name+' 必须是带时区 datetime。')
    return value


def _frame_hash(frame):
    return digest(frame.write_json())


class PlaybookPaperPlanService:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise PlaybookPaperPlanError('INVALID_WORKSPACE','工作空间不存在。')
        self.root=self.output/'_trading'/'paper_plans';self.playbooks=PlaybookStore(self.output);self.decisions=DecisionStore(self.output)

    def _path(self,plan_id):return self.root/(_uuid(plan_id,'plan_id')+'.json')

    @contextmanager
    def _locked(self,plan_id):
        _uuid(plan_id,'plan_id')
        if self.root.is_symlink():raise PlaybookPaperPlanError('INVALID_WORKSPACE','PaperPlan 目录不能是符号链接。')
        self.root.mkdir(parents=True,exist_ok=True);lock=self.root/(plan_id+'.lock')
        if lock.is_symlink():raise PlaybookPaperPlanError('INVALID_WORKSPACE','PaperPlan lock 不能是符号链接。')
        with lock.open('a+b') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise PlaybookPaperPlanError('BUSY','PaperPlan 正在处理。') from None
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def _load(self,plan_id):
        path=self._path(plan_id)
        if not path.exists():raise PlaybookPaperPlanError('NOT_FOUND','PaperPlan 不存在。')
        try:value=read_checked(path)
        except (OSError,ValueError) as exc:raise PlaybookPaperPlanError('CORRUPT_PLAN',str(exc)) from None
        if value.get('format')!=FORMAT or value.get('plan_id')!=plan_id:
            raise PlaybookPaperPlanError('CORRUPT_PLAN','PaperPlan 身份不一致。')
        return value

    def _save(self,state):write_checked(self._path(state['plan_id']),state)

    def get(self,plan_id):
        with self._locked(_uuid(plan_id,'plan_id')):return self._load(plan_id)

    def list(self,limit=200):
        if type(limit) is not int or not 1<=limit<=2000:raise PlaybookPaperPlanError('INVALID_ARGUMENT','limit 必须为1–2000。')
        if not self.root.exists():return []
        rows=[]
        for path in sorted(self.root.glob('*.json'),reverse=True):
            try:rows.append(self._load(path.stem))
            except PlaybookPaperPlanError:continue
            if len(rows)>=limit:break
        return rows

    def _selection_bundle(self,selection_id):
        try:selection=self.playbooks.get_selection(_uuid(selection_id,'selection_id'))
        except PlaybookError as exc:raise PlaybookPaperPlanError(exc.code,str(exc)) from None
        if selection['kind']!='SYSTEM_PREDICTION':
            raise PlaybookPaperPlanError('NOT_SYSTEM_PREDICTION','PaperPlan 只能绑定真实 SYSTEM_PREDICTION。')
        if not selection['selected_symbols']:
            raise PlaybookPaperPlanError('NO_TRADE','NO_TRADE Selection 不能创建开仓 PaperPlan。')
        try:bundle=self.playbooks.case_bundle(selection['case_id'])
        except PlaybookError as exc:raise PlaybookPaperPlanError(exc.code,str(exc)) from None
        return selection,bundle

    def create(self,selection_id,decision_ids,account_name,target_weights,*,confirmed=False):
        if confirmed is not True:raise PlaybookPaperPlanError('CONFIRMATION_REQUIRED','创建 PaperPlan 需要宿主显式确认。')
        if not isinstance(account_name,str) or not ACCOUNT.fullmatch(account_name):
            raise PlaybookPaperPlanError('INVALID_ARGUMENT','account_name 限英文、数字、下划线或短横线，1–80字。')
        if not isinstance(decision_ids,list) or not decision_ids or len(decision_ids)>100:
            raise PlaybookPaperPlanError('INVALID_ARGUMENT','decision_ids 必须为非空 UUID 数组。')
        if len(set(decision_ids))!=len(decision_ids):raise PlaybookPaperPlanError('INVALID_ARGUMENT','decision_ids 不能重复。')
        selection,bundle=self._selection_bundle(selection_id);selected=selection['selected_symbols'];selected_set=set(selected)
        if not isinstance(target_weights,dict) or set(target_weights)!=selected_set:
            raise PlaybookPaperPlanError('WEIGHTS_MISMATCH','P8.8 v1 target_weights 必须精确覆盖全部 selected_symbols。')
        weights={}
        for symbol in selected:
            value=target_weights[symbol]
            if type(value) not in (int,float) or not 0<value<=1:raise PlaybookPaperPlanError('INVALID_ARGUMENT','目标权重必须在 (0,1]。')
            weights[symbol]=float(value)
        if sum(weights.values())>1+1e-12:raise PlaybookPaperPlanError('INVALID_ARGUMENT','目标权重合计不能超过1。')
        decisions=[];by_symbol={};case=bundle['case']
        for decision_id in decision_ids:
            try:decision=self.decisions.get(_uuid(decision_id,'decision_id'))
            except DecisionError as exc:raise PlaybookPaperPlanError(exc.code,str(exc)) from None
            if decision.get('superseded_by'):raise PlaybookPaperPlanError('DECISION_SUPERSEDED','PaperPlan 不能绑定已被修订的 Decision。')
            if decision['action']!='PLAN_OPEN':raise PlaybookPaperPlanError('PLAN_OPEN_REQUIRED','PaperPlan 只能绑定当前 PLAN_OPEN Decision。')
            if decision['symbol'] not in selected_set:raise PlaybookPaperPlanError('OUTSIDE_SELECTION','Decision 证券不在 SYSTEM_PREDICTION selected_symbols。')
            if decision['trading_day']!=case['trading_day'] or FRAME_ORDER[decision['frame']]<FRAME_ORDER[case['frame']]:
                raise PlaybookPaperPlanError('DECISION_TIME_MISMATCH','PLAN_OPEN 必须与 Selection 同交易日且不早于 Selection Frame。')
            if decision['symbol'] in by_symbol:raise PlaybookPaperPlanError('DUPLICATE_SYMBOL_DECISION','每个证券只能绑定一个 PLAN_OPEN Decision。')
            by_symbol[decision['symbol']]=decision;decisions.append(decision)
        if set(by_symbol)!=selected_set:
            raise PlaybookPaperPlanError('DECISION_COVERAGE','每个 selected symbol 都必须有一个当前 PLAN_OPEN Decision。')
        target_at=max(datetime.fromisoformat(d['submitted_at']) for d in decisions)
        decision_map={symbol:by_symbol[symbol]['decision_id'] for symbol in selected}
        spec={'selection_id':selection_id,'selection_hash':digest(selection),'case_id':selection['case_id'],
            'candidate_set_id':selection['candidate_set_id'],'definition_id':selection['definition_id'],
            'trading_day':case['trading_day'],'selection_frame':case['frame'],'universe_symbols':selected,
            'decision_ids':decision_map,'decision_hashes':{s:digest({k:v for k,v in by_symbol[s].items() if k!='superseded_by'}) for s in selected},
            'account_name':account_name,'target_weights':weights,'target_at':target_at.isoformat(),
            'policy':'PLAN_OPEN only; fixed universe; Paper execution is separate; fill never auto-upgrades Strategy Intent.'}
        spec_hash=digest(spec);plan_id=str(uuid5(NAMESPACE_URL,'niuniu-playbook-paper-plan:'+spec_hash));stamp=_stamp(self.now_fn())
        with self._locked(plan_id):
            path=self._path(plan_id)
            if path.exists():
                old=self._load(plan_id)
                if old['spec_hash']!=spec_hash:raise PlaybookPaperPlanError('PLAN_CONFLICT','PaperPlan 内容冲突。')
                return old
            state={'format':FORMAT,'plan_id':plan_id,'spec_hash':spec_hash,'spec':spec,'status':'PENDING_MARKET_INPUT',
                'created_at':stamp.astimezone(timezone.utc).isoformat(),'updated_at':stamp.astimezone(timezone.utc).isoformat(),
                'execution':None,'events':[{'at':stamp.isoformat(),'status':'PENDING_MARKET_INPUT','detail':'PaperPlan 已冻结；尚无模拟成交。'}]}
            self._save(state);return state

    def _revalidate_sources(self,state):
        spec=state['spec']
        try:selection=self.playbooks.get_selection(spec['selection_id'])
        except PlaybookError as exc:raise PlaybookPaperPlanError(exc.code,str(exc)) from None
        if digest(selection)!=spec['selection_hash']:raise PlaybookPaperPlanError('SOURCE_CHANGED','SYSTEM_PREDICTION 在建计划后变化。')
        for symbol,decision_id in spec['decision_ids'].items():
            try:decision=self.decisions.get(decision_id)
            except DecisionError as exc:raise PlaybookPaperPlanError(exc.code,str(exc)) from None
            if decision.get('superseded_by') or digest({k:v for k,v in decision.items() if k!='superseded_by'})!=spec['decision_hashes'][symbol]:
                raise PlaybookPaperPlanError('SOURCE_CHANGED','PLAN_OPEN Decision 在建计划后变化或被修订。')
        return selection

    @staticmethod
    def _account_universe(state):
        return sorted({row['symbol'] for row in state.get('bars',[])})

    def execute(self,plan_id,bars,rules,config=None,backend='open',*,as_of=None,confirmed=False):
        if confirmed is not True:raise PlaybookPaperPlanError('CONFIRMATION_REQUIRED','执行 PaperPlan 需要宿主显式确认。')
        if not isinstance(bars,pl.DataFrame) or bars.is_empty():raise PlaybookPaperPlanError('INVALID_MARKET_INPUT','bars 必须是非空 Polars DataFrame。')
        if not isinstance(rules,MarketRules):raise PlaybookPaperPlanError('INVALID_MARKET_INPUT','必须提供显式 MarketRules。')
        if backend not in ('open','vnpy_rules'):raise PlaybookPaperPlanError('INVALID_ARGUMENT','backend 仅支持 open/vnpy_rules。')
        config=config or ExecutionConfig();stamp=_stamp(as_of or self.now_fn())
        with self._locked(_uuid(plan_id,'plan_id')):
            state=self._load(plan_id);self._revalidate_sources(state);spec=state['spec'];universe=sorted(spec['universe_symbols'])
            if sorted(set(bars['symbol'].to_list()))!=universe:
                raise PlaybookPaperPlanError('BARS_UNIVERSE_MISMATCH','bars 证券集合必须与冻结 PaperPlan universe 完全一致。')
            if not set(universe)<=set(r['symbol'] for r in rules.records):
                raise PlaybookPaperPlanError('MARKET_RULES_INCOMPLETE','MarketRules 未覆盖全部 PaperPlan universe。')
            account=self.output/'paper'/(spec['account_name']+'.json')
            if account.is_symlink() or account.parent.is_symlink():raise PlaybookPaperPlanError('INVALID_WORKSPACE','Paper account 路径不能是符号链接。')
            previous=PaperAccount(account).read() if account.exists() else None
            if previous and self._account_universe(previous)!=universe:
                raise PlaybookPaperPlanError('ACCOUNT_UNIVERSE_MISMATCH','现有 PaperAccount universe 与本 PaperPlan 不一致；P8.8 v1 不改写历史 universe。')
            target_at=datetime.fromisoformat(spec['target_at'])
            targets=pl.DataFrame([{'symbol':s,'datetime':target_at,'available_at':target_at,'weight':spec['target_weights'][s]} for s in universe])
            execution_spec={'bars_hash':_frame_hash(bars),'rules_snapshot_id':rules.snapshot_id,
                'config':asdict(config),'backend':backend,'as_of':stamp.isoformat(),'target_hash':_frame_hash(targets)}
            request_hash=digest(execution_spec)
            existing=state.get('execution')
            if existing and existing.get('request_hash')!=request_hash:
                raise PlaybookPaperPlanError('EXECUTION_CONFLICT','同一 PaperPlan 已预留不同执行输入。')
            if existing and existing.get('status')=='EXECUTED':return state
            if existing is None:
                baseline=PaperAccount(account).read() if account.exists() else None
                state['execution']={'status':'RESERVED','request_hash':request_hash,'spec':execution_spec,'reserved_at':stamp.isoformat(),
                    'before_order_ids':sorted(o['order_id'] for o in (baseline or {}).get('orders',[])),
                    'before_fill_count':len((baseline or {}).get('fills',[])),
                    'before_account_revision':(baseline or {}).get('revision',0)}
                state['status']='EXECUTION_RESERVED';state['updated_at']=stamp.isoformat();self._save(state)
                existing=state['execution']
            before_orders=set(existing.get('before_order_ids',[]));before_fills=existing.get('before_fill_count',0)
            try:paper=PaperAccount(account).advance(bars,targets,rules,config,backend,as_of=stamp)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                state=self._load(plan_id);state['execution'].update(status='FAILED',error=type(exc).__name__+': '+str(exc)[:400])
                state['status']='EXECUTION_FAILED';state['updated_at']=stamp.isoformat();self._save(state);raise PlaybookPaperPlanError('PAPER_EXECUTION_FAILED',str(exc)) from None
            new_orders=[o for o in paper.get('orders',[]) if o['order_id'] not in before_orders]
            new_fills=paper.get('fills',[])[before_fills:]
            state=self._load(plan_id);state['execution'].update(status='EXECUTED',account_path=str(account),
                account_revision=paper['revision'],new_order_ids=[o['order_id'] for o in new_orders],new_orders=new_orders,
                new_fills=new_fills,summary=paper['summary'],executed_at=stamp.isoformat())
            state['status']='EXECUTED_WITH_FILL' if new_fills else 'EXECUTED_NO_FILL';state['updated_at']=stamp.isoformat()
            state['events'].append({'at':stamp.isoformat(),'status':state['status'],
                'detail':f"Paper revision={paper['revision']} new_orders={len(new_orders)} fills={len(new_fills)}; Strategy Intent remains PLAN_OPEN."})
            self._save(state);return state


__all__=['FORMAT','PlaybookPaperPlanError','PlaybookPaperPlanService']
