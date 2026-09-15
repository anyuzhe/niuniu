"""Longer frozen MQC sample for explicit Chan progression workflow acceptance."""
import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
import polars as pl
from quantlab.app import build_runner
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.theory_study import TheoryStudyPlan,TheoryStudyRunner
from quantlab.factors.chan_progression import ChanProgressionComponent
from quantlab.theory.templates import resolve_template
from quantlab.sequence.replay import replay_page
from quantlab.storage.codec import encode
from quantlab.causal import assert_prefix_invariant

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--data-root',type=Path,default=Path('/Volumes/Lexar/niuniu-data'))
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    symbols=('sh.600000','sh.600036','sh.600276','sh.600309','sh.600519','sh.600887','sh.601166','sh.601288','sh.601318','sh.601328',
        'sh.601398','sh.601857','sz.000001','sz.000002','sz.000333','sz.000651','sz.000858','sz.002415','sz.002594','sz.300750')
    request=DataRequest(symbols,Timeframe.MIN5,date(2026,8,3),date(2026,9,4))
    plan_spec={'split':{'train_end':'2026-08-14','valid_end':'2026-08-21'},
        'schedule':{'train_days':12,'valid_days':7,'test_days':14},'input':'buy','grid':{'divergence_ratio':[.6,.8]}}
    (args.output/'fixed-plan.json').write_text(encode({'request':request,'theory_plan':plan_spec,'parameters':'registered defaults',
        'scope':'Explicit OHLC rule and research workflow, not canonical Chan completeness or alpha certification'}))
    runner=build_runner(args.data_root,args.output/'runs',symbols)
    batch=runner.data.load(request);market=batch.bars
    # Freeze the exact bars before all checks/studies; use existing loaded provider.
    from quantlab.experiments.ablation import _LoadedData
    runner.data=_LoadedData(batch,request);market.write_parquet(args.output/'bars.parquet')
    factor=ChanProgressionComponent('buy2');_,_,events=factor.trace(market,{})
    cutoffs=sorted(set(market['available_at']));checks=[cutoffs[len(cutoffs)*i//4] for i in (1,2,3)]
    assert_prefix_invariant(factor,market,{},checks)
    for cutoff in checks:
        if factor.trace(market.filter(pl.col('available_at')<=cutoff),{})[2]!=[e for e in events if e.available_at<=cutoff]:raise ValueError('Historical progression events changed')
    (args.output/'events.json').write_text(encode(events))
    counts=dict(Counter(e.factor_id for e in events));print(encode(counts),flush=True)
    params,origin=resolve_template('RESEARCH.CHAN_RULE_BUY2_MOMENTUM',runner.registry)
    config=ExperimentConfig('Chan 确认推进规则验收',request,'COMB.CONDITION',parameters=params,horizons=(1,5,20),theory_origin=origin,replay=True,sequence_audit=True)
    result=TheoryStudyRunner(runner).run(config,TheoryStudyPlan.parse(plan_spec))
    record=json.loads((result.artifact_path/'experiment.json').read_text());replay_checks=0
    for child in record['children']:
        path=Path(child['artifact_path']);r=json.loads((path/'experiment.json').read_text())
        if not r.get('sequence_audit'):continue
        bars=pl.read_parquet(path/'bars.parquet');n=bars.filter(pl.col('symbol')==symbols[0]).height
        for cursor in (0,n//2,n-1):
            page=replay_page(bars,r,symbols[0],cursor)
            if any(e['available_at']>page['as_of'].isoformat() for e in page['events']):raise ValueError('Replay exposed future evidence')
            replay_checks+=1
    summary={'rows':market.height,'symbols':len(symbols),'data_snapshot':batch.snapshot,'counts':counts,'prefix_checks':3,
        'replay_cursor_checks':replay_checks,'children':len(record['children']),'artifact_path':result.artifact_path,'status':record['status']}
    (args.output/'result.json').write_text(encode(summary));print(encode({k:v for k,v in summary.items() if k!='data_snapshot'}))
