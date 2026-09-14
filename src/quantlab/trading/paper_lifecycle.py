"""Read-only lifecycle statistics for Playbook → Decision → Paper evidence."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import math

from quantlab.experiments.campaign_state import read_checked
from .playbook_decision_bridge import PlaybookDecisionBridge
from .playbook_paper_plan import PlaybookPaperPlanService
from .playbook_store import PlaybookStore
from .paper_review import PaperReviewService
from .paper_rebalance import PaperRebalancePlanService


class PaperLifecycleAnalytics:
    def __init__(self,output):
        self.output=Path(output).resolve()
        if not self.output.is_dir():raise ValueError('workspace 不存在。')

    @staticmethod
    def _receipts(root,limit=5000):
        if not root.exists() or root.is_symlink():return []
        rows=[]
        for path in sorted(root.glob('*.json')):
            if path.is_symlink():continue
            try:rows.append(read_checked(path))
            except (OSError,ValueError):continue
            if len(rows)>=limit:break
        return rows

    def build(self):
        store=PlaybookStore(self.output)
        predictions=store.list_selections(kind='SYSTEM_PREDICTION',limit=2000)['records']
        bridge=PlaybookDecisionBridge(self.output).list(limit=2000)
        plans=PlaybookPaperPlanService(self.output).list(limit=2000)
        fill_receipts=self._receipts(self.output/'_trading'/'paper_fill_intent')
        reviews=PaperReviewService(self.output).list(limit=5000)
        rebalances=PaperRebalancePlanService(self.output).list(limit=2000)
        rebalance_outcomes=self._receipts(self.output/'_trading'/'paper_rebalance_outcomes')
        plan_status=Counter(row.get('status','UNKNOWN') for row in plans);rejections=Counter();costs=Counter()
        executed=0;with_fill=0;no_fill=0;fills=0;plan_executed=0;rebalance_executed=0
        execution_records=[('paper_plan',row) for row in plans]+[('rebalance',row) for row in rebalances]
        for kind,plan in execution_records:
            execution=plan.get('execution') or {}
            if execution.get('status')!='EXECUTED':continue
            executed+=1;plan_executed+=int(kind=='paper_plan');rebalance_executed+=int(kind=='rebalance')
            new_fills=execution.get('new_fills') or [];fills+=len(new_fills)
            with_fill+=int(bool(new_fills));no_fill+=int(not new_fills)
            for fill in new_fills:
                for key in ('commission','tax','transfer_fee','slippage_cost'):
                    value=fill.get(key,0.0)
                    if type(value) in (int,float) and math.isfinite(value):costs[key]+=value
            for order in execution.get('new_orders') or []:
                if order.get('status')=='remainder_rejected':rejections[str(order.get('reason') or 'unknown')]+=1
        dynamic=[];dynamic_root=self.output/'paper_dynamic'
        if dynamic_root.exists() and not dynamic_root.is_symlink():
            for path in sorted(dynamic_root.glob('*.json')):
                if path.is_symlink():continue
                try:value=read_checked(path)
                except (OSError,ValueError):continue
                if value.get('format')!='dynamic-paper-v1':continue
                dynamic.append({'account':path.stem,'revision':value.get('revision'),
                    'universe_size':len(value.get('universe_symbols') or []),'net_return':(value.get('summary') or {}).get('net_return'),
                    'fills':len(value.get('fills') or []),'rejections':len(value.get('rejections') or []),
                    'ending_positions':(value.get('summary') or {}).get('ending_positions',{})})
        review_counts=Counter(row.get('review_frame','UNKNOWN') for row in reviews)
        open_recorded=sum(row.get('open_recorded',0) for row in fill_receipts);fill_no_trade=sum(row.get('no_fill',0) for row in fill_receipts)
        return {'system_predictions':len(predictions),'no_trade_predictions':sum(not row.get('selected_symbols') for row in predictions),
            'selected_predictions':sum(bool(row.get('selected_symbols')) for row in predictions),
            'selected_symbol_events':sum(len(row.get('selected_symbols') or []) for row in predictions),
            'decision_bridge_receipts':len(bridge),'paper_plans':len(plans),'paper_plan_status':dict(plan_status),
            'paper_executions':executed,'paper_plan_executions':plan_executed,'paper_rebalance_executions':rebalance_executed,
            'paper_executions_with_fill':with_fill,'paper_executions_no_fill':no_fill,
            'paper_fill_count':fills,'paper_costs':dict(costs),'paper_rejection_reasons':dict(rejections),
            'fill_intent_receipts':len(fill_receipts),'open_intents_from_fill':open_recorded,'no_fill_intent_outcomes':fill_no_trade,
            'paper_reviews':len(reviews),'paper_reviews_by_frame':dict(review_counts),'paper_rebalances':len(rebalances),
            'paper_rebalance_status':dict(Counter(row.get('status','UNKNOWN') for row in rebalances)),
            'paper_rebalance_outcomes':len(rebalance_outcomes),'dynamic_accounts':dynamic,
            'dynamic_account_count':len(dynamic),'automatic_real_trade':False,
            'scope':'Read-only observed lifecycle counts. Selection, execution access, Paper fill and account return remain separate.'}


__all__=['PaperLifecycleAnalytics']
