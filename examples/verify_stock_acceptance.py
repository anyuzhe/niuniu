"""Fixed historical raw-bar accounting acceptance; no official-rule/live claim."""
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
import json
import polars as pl
from quantlab.app import build_runner
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.execution import ExecutionStudy
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.rules import MarketRules
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account
from quantlab.storage.codec import encode

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('artifacts/stock-acceptance'))
    out=parser.parse_args().output;source=json.loads((out/'corporate-actions.json').read_text())
    plan={'created_at':datetime.now(timezone.utc),'cases':[{'symbol':'sh.600000','start':'2017-05-02','end':'2017-06-09'},
        {'symbol':'sz.300750','start':'2023-04-03','end':'2023-05-12'}],
        'signal':{'factor':'BASE.MOMENTUM','lookback':2,'threshold':-1,'exposure':.5},
        'scope':'Raw historical stock-distribution accounting only. Retrospective actions, fixed tax 0, default execution costs. Not a frozen official-rule research sample.'}
    with (out/'fixed-accounting-plan.json').open('x') as handle:handle.write(encode(plan))
    results=[]
    for case in plan['cases']:
        symbol=case['symbol'];start=date.fromisoformat(case['start']);end=date.fromisoformat(case['end'])
        actions=[r for r in source['corporate_actions'] if r['symbol']==symbol and case['start']<=r['record_at'][:10]<=case['end']]
        if len(actions)!=1 or 'stock_per_share' not in actions[0]:raise ValueError('Expected a single documented stock distribution')
        cfg=ExecutionConfig(initial_cash=1000000,top_n=1,threshold=-1,exposure=.5,corporate_actions=actions,corporate_action_mode='retrospective')
        runner=build_runner(Path('/Volumes/Lexar/MQC-DATA'),Path('artifacts'),(symbol,),'raw')
        config=ExperimentConfig('真实送转记录与原始行情账务验收；不代表真实交易规则',DataRequest((symbol,),Timeframe.DAILY,start,end),
            'BASE.MOMENTUM',parameters={'lookback':2},horizons=(1,5),replay=True)
        result=ExecutionStudy(runner).run(config,cfg,backend='vnpy_rules')
        bars=pl.read_parquet(result.artifact_path/'bars.parquet');targets=pl.read_parquet(result.artifact_path/'targets.parquet')
        rules=MarketRules([{'symbol':symbol,'effective_at':bars['datetime'].min().replace(hour=0),'available_at':bars['datetime'].min().replace(hour=0),
            'expires_at':bars['datetime'].max()+timedelta(days=1),'suspended':False,'st':False,'limit_up':None,'limit_down':None,
            'commission_bps':cfg.commission_bps,'minimum_commission':cfg.minimum_commission,'sell_tax_bps':cfg.sell_tax_bps,'transfer_bps':cfg.transfer_bps,
            'source':'SYNTHETIC_ACCOUNTING_ONLY; assumed tradable/unbounded. Not official historical rules.'}])
        (out/(symbol+'-execution.json')).write_text(encode(cfg))
        (out/(symbol+'-rules.json')).write_text(encode(rules.records))
        account=PaperAccount(out/(symbol+'-paper.json'))
        if account.path.exists():raise FileExistsError(account.path)
        # Stop at ex-date, then recreate the account wrapper and deliver the remainder.
        boundary=date.fromisoformat(actions[0]['ex_at'][:10])
        first=account.advance(bars.filter(pl.col('datetime').dt.date()<=boundary),targets.filter(pl.col('datetime').dt.date()<=boundary),rules,cfg,'vnpy_rules')
        final=PaperAccount(account.path).advance(bars,targets,rules,cfg,'vnpy_rules')
        duplicate=PaperAccount(account.path).advance(bars,targets,rules,cfg,'vnpy_rules')
        if final!=duplicate:raise ValueError('Duplicate paper delivery changed state')
        rec=reconcile_account(account.path)
        if rec['status']!='matched':raise ValueError('Paper reconciliation failed')
        (out/(symbol+'-reconciliation.json')).write_text(encode(rec))
        results.append({'case':case,'execution':result,'paper_account':account.path,'first_revision':first['revision'],'final_revision':final['revision'],
            'first_pending':first['summary'].get('pending_stock_positions'),'reconciliation':rec['status'],'duplicate_unchanged':True})
        (out/'accounting-results.json').write_text(encode(results))
    print(encode([{'symbol':r['case']['symbol'],'fills':r['execution'].summary['fills'],'pending_at_ex':r['first_pending'],'reconciliation':r['reconciliation']} for r in results]))
