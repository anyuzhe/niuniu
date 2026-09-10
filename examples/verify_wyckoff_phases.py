"""Frozen historical phase-state and research workflow acceptance."""
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
from quantlab.experiments.ablation import _LoadedData
from quantlab.factors.wyckoff_phases import WyckoffPhaseComponent
from quantlab.theory.templates import resolve_template
from quantlab.sequence.replay import replay_page
from quantlab.storage.codec import encode
from quantlab.causal import assert_prefix_invariant

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('/Volumes/Lexar/MQC-DATA'));args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    symbols=('sh.600000','sh.600036','sh.600276','sh.600309','sh.600519','sh.600887','sh.601166','sh.601288','sh.601318','sh.601328',
        'sh.601398','sh.601857','sz.000001','sz.000002','sz.000333','sz.000651','sz.000858','sz.002415','sz.002594','sz.300750')
    request=DataRequest(symbols,Timeframe.MIN5,date(2026,8,3),date(2026,9,4))
    plan={'split':{'train_end':'2026-08-14','valid_end':'2026-08-21'},
        'schedule':{'train_days':12,'valid_days':7,'test_days':14},'input':'continuation','grid':{'follow_bars':[30,60]}}
    (args.output/'fixed-plan.json').write_text(encode({'request':request,'plan':plan,'parameters':'registered defaults',
        'scope':'OHLC stage-state proxy, not institutional activity inference or statistical-power acceptance'}))
    runner=build_runner(args.data_root,args.output/'runs',symbols);batch=runner.data.load(request);market=batch.bars
    runner.data=_LoadedData(batch,request);market.write_parquet(args.output/'bars.parquet')
    factor=WyckoffPhaseComponent('code');values,states,events=factor.trace(market,{})
    clocks=sorted(set(market['available_at']));checks=[clocks[len(clocks)*i//4] for i in (1,2,3)]
    assert_prefix_invariant(factor,market,{},checks)
    for cutoff in checks:
        _,before_states,before_events=factor.trace(market.filter(pl.col('available_at')<=cutoff),{})
        if before_states!=[s for s in states if s.available_at<=cutoff] or before_events!=[e for e in events if e.available_at<=cutoff]:raise ValueError('Phase history changed')
    last_status={s.match_id:s.status for s in states}
    counts=dict(Counter(e.factor_id for e in events));print(encode(counts),flush=True)
    (args.output/'phase-events.json').write_text(encode(events));(args.output/'transitions.json').write_text(encode(states))
    values.write_parquet(args.output/'phase-code.parquet')
    params,origin=resolve_template('RESEARCH.WYCKOFF_PHASE_E_MOMENTUM',runner.registry)
    config=ExperimentConfig('Wyckoff 阶段代理全流程验收',request,'COMB.CONDITION',parameters=params,horizons=(1,5,20),theory_origin=origin,replay=True,sequence_audit=True)
    result=TheoryStudyRunner(runner).run(config,TheoryStudyPlan.parse(plan))
    record=json.loads((result.artifact_path/'experiment.json').read_text());replay_checks=0
    for child in record['children']:
        path=Path(child['artifact_path']);r=json.loads((path/'experiment.json').read_text())
        if not r.get('sequence_audit'):continue
        bars=pl.read_parquet(path/'bars.parquet');n=bars.filter(pl.col('symbol')==symbols[0]).height
        for cursor in (0,n//2,n-1):
            page=replay_page(bars,r,symbols[0],cursor)
            if any(e['available_at']>page['as_of'].isoformat() for e in page['events']):raise ValueError('Replay exposed future phase')
            replay_checks+=1
    summary={'status':record['status'],'artifact_path':result.artifact_path,'rows':market.height,'symbols':len(symbols),'data_snapshot':batch.snapshot,
        'counts':counts,'episode_end_states':dict(Counter(last_status.values())),'prefix_checks':3,'replay_cursor_checks':replay_checks,'children':len(record['children'])}
    (args.output/'result.json').write_text(encode(summary));print(encode({k:v for k,v in summary.items() if k!='data_snapshot'}))
