"""Point-in-time D1/D2/D3+ reviews for executed Playbook PaperPlans.

Reviews are outcome evidence, not Strategy Intent transitions.  Every metric is
filtered to the review day's completed-data cutoff so later account deliveries
cannot improve an earlier review retrospectively.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import math

from quantlab.execution.paper import PaperAccount
from quantlab.experiments.campaign_state import read_checked, write_checked
from quantlab.storage.codec import digest
from .playbook_paper_plan import PlaybookPaperPlanError,PlaybookPaperPlanService

FORMAT='paper-outcome-review-v1'


class PaperReviewError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _moment(value):return datetime.fromisoformat(value)


def _day(value):
    try:return date.fromisoformat(value).isoformat()
    except (TypeError,ValueError):raise PaperReviewError('INVALID_ARGUMENT','review_day 必须为 YYYY-MM-DD。') from None


def _review_frame(index):return 'D1' if index==0 else ('D2' if index==1 else 'D3_PLUS')


class PaperReviewService:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise PaperReviewError('INVALID_WORKSPACE','工作空间不存在。')
        self.root=self.output/'_trading'/'paper_reviews';self.plans=PlaybookPaperPlanService(self.output)

    def _load_account(self,plan):
        execution=plan.get('execution') or {}
        if execution.get('status')!='EXECUTED':raise PaperReviewError('EXECUTION_REQUIRED','PaperPlan 必须先完成模拟执行。')
        path=Path(execution.get('account_path','')).resolve()
        if not path.is_file() or path.is_symlink():raise PaperReviewError('ACCOUNT_NOT_FOUND','Paper account 不存在或路径异常。')
        if execution.get('mode')=='dynamic_v1':
            try:return read_checked(path),'dynamic_v1',path
            except (OSError,ValueError) as exc:raise PaperReviewError('CORRUPT_ACCOUNT',str(exc)) from None
        try:return PaperAccount(path).read(),'fixed_v1',path
        except (OSError,ValueError,KeyError) as exc:raise PaperReviewError('CORRUPT_ACCOUNT',str(exc)) from None

    def _path(self,plan_id,day,frame):
        folder=self.root/plan_id;return folder/(day+'_'+frame+'.json')

    @staticmethod
    def _close_by_symbol(state,review_day):
        latest={}
        for row in state.get('bars',[]):
            moment=_moment(row['datetime'])
            if moment.date().isoformat()!=review_day:continue
            old=latest.get(row['symbol'])
            if old is None or _moment(old['datetime'])<moment:latest[row['symbol']]=row
        return {symbol:row['close'] for symbol,row in latest.items()}

    @staticmethod
    def _cutoff(state,review_day):
        times=[_moment(row['available_at']) for row in state.get('bars',[]) if _moment(row['available_at']).date().isoformat()==review_day]
        if not times:raise PaperReviewError('NO_REVIEW_DATA','账户没有该复盘日的完成 bar。')
        return max(times)

    @staticmethod
    def _account_position_from_fills(state,symbol,cutoff):
        quantity=0
        for fill in state.get('fills',[]):
            if fill.get('symbol')!=symbol or _moment(fill['filled_at'])>cutoff:continue
            quantity += fill['quantity'] if fill.get('side')=='buy' else -fill['quantity']
        return quantity

    def build(self,plan_id,review_day):
        review_day=_day(review_day)
        try:plan=self.plans.get(plan_id)
        except PlaybookPaperPlanError as exc:raise PaperReviewError(exc.code,str(exc)) from None
        state,mode,account_path=self._load_account(plan);source_day=plan['spec']['trading_day']
        observed=sorted({str(_moment(row['datetime']).date()) for row in state.get('bars',[]) if str(_moment(row['datetime']).date())>source_day})
        if review_day not in observed:raise PaperReviewError('NO_REVIEW_DATA','review_day 不是该账户在来源日后的已观察交易日。')
        index=observed.index(review_day);frame=_review_frame(index);cutoff=self._cutoff(state,review_day);closes=self._close_by_symbol(state,review_day)
        execution=plan['execution'];symbol_rows=[]
        for symbol in plan['spec']['universe_symbols']:
            entry=[fill for fill in execution.get('new_fills',[]) if fill.get('symbol')==symbol and fill.get('side')=='buy' and _moment(fill['filled_at'])<=cutoff]
            qty=sum(fill['quantity'] for fill in entry);notional=sum(fill['quantity']*fill['price'] for fill in entry)
            average=notional/qty if qty else None;close=closes.get(symbol)
            ret=(close/average-1) if average and close is not None else None
            symbol_rows.append({'symbol':symbol,'plan_fill_quantity':qty,'plan_average_fill_price':average,
                'review_close':close,'price_return_from_plan_fill':ret,
                'fill_ledger_quantity':self._account_position_from_fills(state,symbol,cutoff),
                'status':'MARKED' if close is not None and qty else ('NO_FILL' if not qty else 'MISSING_CLOSE')})
        nav=[row for row in state.get('nav',[]) if _moment(row['datetime'])<=cutoff]
        last_nav=nav[-1] if nav else None;initial=float(state['identity']['config']['initial_cash'])
        account_return=(last_nav['equity']/initial-1) if last_nav else None
        relevant_fills=[fill for fill in execution.get('new_fills',[]) if _moment(fill['filled_at'])<=cutoff]
        plan_costs={'commission':math.fsum(fill.get('commission',0.0) for fill in relevant_fills),
            'tax':math.fsum(fill.get('tax',0.0) for fill in relevant_fills),
            'transfer_fee':math.fsum(fill.get('transfer_fee',0.0) for fill in relevant_fills),
            'slippage_cost':math.fsum(fill.get('slippage_cost',0.0) for fill in relevant_fills)}
        rejections=[]
        for order in execution.get('new_orders',[]):
            if order.get('status')!='remainder_rejected':continue
            at=order.get('at') or order.get('filled_at')
            if at and _moment(at)<=cutoff:rejections.append({'symbol':order.get('symbol'),'side':order.get('side'),
                'reason':order.get('reason'),'requested':order.get('requested'),'filled':order.get('filled')})
        core={'format':FORMAT,'plan_id':plan_id,'selection_id':plan['spec']['selection_id'],'account_mode':mode,
            'account_name':plan['spec']['account_name'],'source_trading_day':source_day,'review_day':review_day,'review_frame':frame,
            'review_cutoff_at':cutoff.astimezone(timezone.utc).isoformat(),'symbols':symbol_rows,'plan_costs_to_review':plan_costs,
            'rejections_to_review':rejections,'account_equity':last_nav['equity'] if last_nav else None,
            'account_net_return_to_review':account_return,'future_data_used':False,
            'scope_note':'Outcome evidence only; does not auto-create HOLD/REDUCE/EXIT Strategy Intent. fill_ledger_quantity ignores non-fill corporate-action share changes.'}
        review_hash=digest(core);path=self._path(plan_id,review_day,frame)
        if path.exists():
            try:old=read_checked(path)
            except (OSError,ValueError) as exc:raise PaperReviewError('CORRUPT_REVIEW',str(exc)) from None
            if old.get('review_hash')!=review_hash:raise PaperReviewError('REVIEW_CONFLICT','后来数据改变了已冻结复盘内容。')
            return old
        stamp=self.now_fn()
        if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise PaperReviewError('INVALID_CLOCK','时钟必须带时区。')
        value={**core,'review_hash':review_hash,'account_path':str(account_path),'created_at':stamp.astimezone(timezone.utc).isoformat()}
        path.parent.mkdir(parents=True,exist_ok=True);write_checked(path,value);return value

    def auto(self,plan_id,limit_days=20):
        if type(limit_days) is not int or not 1<=limit_days<=1000:raise PaperReviewError('INVALID_ARGUMENT','limit_days 必须为1–1000。')
        try:plan=self.plans.get(plan_id)
        except PlaybookPaperPlanError as exc:raise PaperReviewError(exc.code,str(exc)) from None
        state,_,_=self._load_account(plan);source_day=plan['spec']['trading_day']
        days=sorted({str(_moment(row['datetime']).date()) for row in state.get('bars',[]) if str(_moment(row['datetime']).date())>source_day})[:limit_days]
        return [self.build(plan_id,day) for day in days]

    def auto_all(self,limit_plans=500,limit_days=20):
        if type(limit_plans) is not int or not 1<=limit_plans<=2000:raise PaperReviewError('INVALID_ARGUMENT','limit_plans 必须为1–2000。')
        plans=self.plans.list(limit=limit_plans);records=[];errors=[]
        for plan in plans:
            if (plan.get('execution') or {}).get('status')!='EXECUTED':continue
            try:records.extend(self.auto(plan['plan_id'],limit_days))
            except (PaperReviewError,OSError,ValueError,KeyError,TypeError) as exc:
                errors.append({'plan_id':plan['plan_id'],'code':getattr(exc,'code',type(exc).__name__),'message':str(exc)[:300]})
        return {'plans_checked':len(plans),'reviews':records,'errors':errors,'strategy_intent_mutated':False}


    def list(self,plan_id='',limit=1000):
        if type(limit) is not int or not 1<=limit<=5000:raise PaperReviewError('INVALID_ARGUMENT','limit 必须为1–5000。')
        roots=[self.root/plan_id] if plan_id else ([p for p in self.root.iterdir() if p.is_dir()] if self.root.exists() else [])
        rows=[]
        for folder in roots:
            if folder.is_symlink():continue
            for path in sorted(folder.glob('*.json')):
                try:rows.append(read_checked(path))
                except (OSError,ValueError):continue
                if len(rows)>=limit:return rows
        return rows


__all__=['FORMAT','PaperReviewError','PaperReviewService']
