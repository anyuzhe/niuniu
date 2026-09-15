"""Read-only Broker ↔ Dynamic Paper shadow reconciliation. Never submits orders."""
from __future__ import annotations
from pathlib import Path
import math,re
from quantlab.experiments.campaign_state import read_checked
from quantlab.storage.codec import digest
from .contracts import BrokerSnapshotError
from .store import BrokerSnapshotStore

ACCOUNT=re.compile(r'^[A-Za-z0-9_.-]{1,120}$')

class BrokerShadowReconciler:
    def __init__(self,output):
        self.output=Path(output).resolve();self.store=BrokerSnapshotStore(self.output)
    def _paper(self,name):
        if not isinstance(name,str) or not ACCOUNT.fullmatch(name):
            raise BrokerSnapshotError('INVALID_ARGUMENT','paper_account 名称无效。')
        path=self.output/'paper_dynamic'/(name if name.endswith('.json') else name+'.json')
        if path.is_symlink() or not path.is_file():
            raise BrokerSnapshotError('PAPER_NOT_FOUND','Dynamic PaperAccount 不存在。')
        try:value=read_checked(path)
        except (OSError,ValueError) as exc:raise BrokerSnapshotError('PAPER_CORRUPT',str(exc)) from None
        if value.get('format')!='dynamic-paper-v1':raise BrokerSnapshotError('PAPER_CORRUPT','不是 Dynamic PaperAccount。')
        return value,path.name
    def reconcile(self,*,snapshot_id='',account_alias='',paper_account='',cash_tolerance=0.01):
        if type(cash_tolerance) not in (int,float) or not math.isfinite(cash_tolerance) or cash_tolerance<0:
            raise BrokerSnapshotError('INVALID_ARGUMENT','cash_tolerance 无效。')
        broker=self.store.get(snapshot_id) if snapshot_id else self.store.latest(account_alias)
        if broker is None:
            return {'format':'niuniu-broker-shadow-v1','status':'NOT_CONFIGURED','broker_snapshot':None,
                'paper_account':None,'real_order_submission':False,'automatic_execution':False,
                'scope':'No broker snapshot imported.'}
        if not paper_account:
            return {'format':'niuniu-broker-shadow-v1','status':'BROKER_SNAPSHOT_ONLY','broker_snapshot':broker,
                'paper_account':None,'real_order_submission':False,'automatic_execution':False,
                'scope':'Read-only broker evidence; choose a Dynamic Paper account for reconciliation.'}
        paper,paper_name=self._paper(paper_account)
        broker_pos={r['symbol']:r['quantity'] for r in broker['positions']}
        paper_pos={k:int(v) for k,v in (paper.get('summary') or {}).get('ending_positions',{}).items()}
        symbols=sorted(set(broker_pos)|set(paper_pos))
        deltas=[{'symbol':s,'broker_quantity':broker_pos.get(s,0),'paper_quantity':paper_pos.get(s,0),
            'delta':broker_pos.get(s,0)-paper_pos.get(s,0)} for s in symbols]
        position_match=all(row['delta']==0 for row in deltas)
        nav=paper.get('nav') or []
        paper_cash=float(nav[-1]['cash']) if nav else None
        paper_equity=float(nav[-1]['equity']) if nav else None
        cash_delta=None if paper_cash is None else broker['cash']-paper_cash
        cash_match=cash_delta is not None and abs(cash_delta)<=cash_tolerance
        equity_delta=None if paper_equity is None else broker['equity']-paper_equity
        core={'broker_snapshot_id':broker['snapshot_id'],'broker_snapshot_hash':broker['snapshot_hash'],
            'paper_account':paper_name,'paper_revision':paper.get('revision'),'paper_watermark':paper.get('watermark'),
            'position_deltas':deltas,'position_match':position_match,'broker_cash':broker['cash'],
            'paper_cash':paper_cash,'cash_delta':cash_delta,'cash_tolerance':float(cash_tolerance),
            'cash_match':cash_match,'broker_equity':broker['equity'],'paper_equity':paper_equity,
            'equity_delta':equity_delta}
        status='MATCH' if position_match and cash_match else 'DIFF'
        return {'format':'niuniu-broker-shadow-v1','status':status,**core,
            'reconciliation_hash':digest(core),'real_order_submission':False,'automatic_execution':False,
            'limitations':['Position/cash matching compares a broker export with deterministic Paper state only.',
                'Equity delta is descriptive because mark times/prices may differ; it is not used for MATCH.',
                'No broker authentication, live gateway, order placement, cancellation or fund transfer exists in P13-A.']}

__all__=['BrokerShadowReconciler']
