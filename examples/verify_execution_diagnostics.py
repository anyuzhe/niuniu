"""Frozen historical bars, explicit synthetic rules, capacity and Paper accounting."""
import argparse
import json
from dataclasses import replace
from datetime import date,timedelta
from pathlib import Path
import polars as pl
from quantlab.app import build_runner
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.execution import ExecutionStudy
from quantlab.execution.backtest import ExecutionConfig,OpenExecutionBacktester
from quantlab.execution.rules import MarketRules
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account
from quantlab.storage.codec import encode

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--snapshot-manifest',type=Path,required=True)
    p.add_argument('--data-root',type=Path,default=Path('/Volumes/Lexar/niuniu-data'))
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads(args.snapshot_manifest.read_text());symbols=tuple(manifest['symbols'])
    start=date.fromisoformat(manifest['start'][:10]);end=date.fromisoformat(manifest['end'][:10])
    runner=build_runner(args.data_root,args.output/'runs',symbols,'raw',snapshot_manifest=args.snapshot_manifest)
    request=DataRequest(symbols,Timeframe(manifest['timeframe']),start,end)
    market=runner.data.load(request).bars;first=market['datetime'].min().replace(hour=0,minute=0);last=market['datetime'].max()+timedelta(days=1)
    rules=MarketRules([{'symbol':s,'effective_at':first,'available_at':first,'expires_at':last,'suspended':False,'st':False,
        'limit_up':None,'limit_down':None,'commission_bps':3,'minimum_commission':5,'sell_tax_bps':0,'transfer_bps':0,
        'source':'SYNTHETIC_ACCOUNTING_ONLY: assumed tradable, unbounded prices, configured fees; not official historical rules'} for s in symbols])
    (args.output/'rules.json').write_text(encode(rules.records))
    config=ExperimentConfig('实际成交诊断与滞后量容量验收；合成交易规则，不是收益有效性证明',request,'BASE.MOMENTUM',parameters={'lookback':5},horizons=(1,5),replay=True)
    cfg=ExecutionConfig(exposure=.8,max_actual_position=.25,max_volume_participation=.01)
    study=ExecutionStudy(runner)
    baseline=study.run(config,replace(cfg,max_volume_participation=None),market_rules=rules)
    candidate=study.run(config,cfg,backend='vnpy_rules',market_rules=rules)
    record=json.loads((candidate.artifact_path/'experiment.json').read_text())
    if record['backend_comparison']['status']!='matched':raise ValueError('Native matching mismatch')
    bars=pl.read_parquet(candidate.artifact_path/'bars.parquet');targets=pl.read_parquet(candidate.artifact_path/'targets.parquet')
    account=PaperAccount(args.output/'paper.json');boundary=sorted(set(bars['datetime'].dt.date()))[len(set(bars['datetime'].dt.date()))//2-1]
    first_state=account.advance(bars.filter(pl.col('datetime').dt.date()<=boundary),targets.filter(pl.col('datetime').dt.date()<=boundary),rules,cfg)
    state=PaperAccount(account.path).advance(bars,targets,rules,cfg)
    for field in ('bars','attempts'):
        if state['execution_audit'][field][:len(first_state['execution_audit'][field])]!=first_state['execution_audit'][field]:raise ValueError('Diagnostic prefix changed')
    before=account.path.read_bytes();PaperAccount(account.path).advance(bars,targets,rules,cfg)
    if before!=account.path.read_bytes():raise ValueError('Duplicate delivery changed account')
    reconciliation=reconcile_account(account.path)
    if reconciliation['status']!='matched':raise ValueError('Paper reconciliation mismatch')
    if state['summary']!=json.loads(encode(candidate.summary)):raise ValueError('Paper summary differs from native backtest')
    result={'baseline':baseline,'candidate':candidate,'backend_comparison_status':record['backend_comparison']['status'],
        'paper_revision':state['revision'],'paper_reconciliation':reconciliation['status'],'diagnostic_prefix_stable':True,'duplicate_unchanged':True,
        'scope':'20-stock short historical sample; synthetic rules, lagged-volume proxy, not official-rule or actual-market-capacity acceptance'}
    (args.output/'result.json').write_text(encode(result))
    print(encode({'baseline_fills':baseline.summary['fills'],'candidate_fills':candidate.summary['fills'],'diagnostics':candidate.summary['execution_diagnostics'],
        'backend':result['backend_comparison_status'],'paper':result['paper_reconciliation']}))
