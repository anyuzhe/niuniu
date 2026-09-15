"""Frozen-sample theory workflow and replay verification, not alpha certification."""
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
from quantlab.theory.templates import resolve_template
from quantlab.factors.order_block import OrderBlockComponent
from quantlab.factors.chan_inclusion import ChanInclusionComponent
from quantlab.sequence.replay import replay_page
from quantlab.storage.codec import encode
from quantlab.causal import assert_prefix_invariant

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--snapshot-manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--data-root',type=Path,default=Path('/Volumes/Lexar/niuniu-data'))
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads(args.snapshot_manifest.read_text());symbols=tuple(manifest['symbols'])
    request=DataRequest(symbols,Timeframe(manifest['timeframe']),date(2026,9,1),date(2026,9,8))
    runner=build_runner(args.data_root,args.output/'runs',symbols,snapshot_manifest=args.snapshot_manifest)
    bars=runner.data.load(request).bars
    plans=[('RESEARCH.CHAN_INCLUSION_CENTER_MOMENTUM','center',{'min_separation':[3,4]}),
        ('RESEARCH.ICT_OB_TOUCH_MOMENTUM','touch',{'max_age_bars':[50,100]})]
    (args.output/'fixed-plan.json').write_text(encode({'snapshot':manifest['version_id'],'request':request,'plans':plans,
        'split':{'train_end':'2026-09-02','valid_end':'2026-09-04'},'scope':'Short workflow acceptance; defaults and two predefined variants, not a stability or predictive-power claim'}))
    traces=[]
    for factor in [ChanInclusionComponent('center'),OrderBlockComponent('created',1),OrderBlockComponent('created',-1)]:
        _,_,events=factor.trace(bars,{})
        cutoffs=sorted(set(bars['available_at']))
        assert_prefix_invariant(factor,bars,{},[cutoffs[i] for i in (50,150,250)])
        for cutoff in [cutoffs[50],cutoffs[150],cutoffs[250]]:
            prefix=factor.trace(bars.filter(pl.col('available_at')<=cutoff),{})[2]
            if prefix!=[e for e in events if e.available_at<=cutoff]:raise ValueError('Event history changed under prefix')
        traces.append({'factor_id':factor.definition.factor_id,'counts':dict(Counter(e.factor_id for e in events)),'real_prefix_checks':3})
    (args.output/'event-counts.json').write_text(encode(traces))
    results=[]
    for template,alias,grid in plans:
        params,origin=resolve_template(template,runner.registry)
        config=ExperimentConfig(template,request,'COMB.CONDITION',parameters=params,horizons=(1,5),theory_origin=origin,replay=True,sequence_audit=True)
        plan=TheoryStudyPlan.parse({'split':{'train_end':'2026-09-02','valid_end':'2026-09-04'},
            'schedule':{'train_days':2,'valid_days':2,'test_days':4},'input':alias,'grid':grid})
        result=TheoryStudyRunner(runner).run(config,plan)
        record=json.loads((result.artifact_path/'experiment.json').read_text())
        replay_checks=0
        for child in record['children']:
            path=Path(child['artifact_path']);r=json.loads((path/'experiment.json').read_text())
            if not r.get('sequence_audit'):continue
            market=pl.read_parquet(path/'bars.parquet');symbol=symbols[0];count=market.filter(pl.col('symbol')==symbol).height
            first=replay_page(market,r,symbol,0);last=replay_page(market,r,symbol,count-1)
            for page in (first,last):
                if any(e['available_at']>page['as_of'].isoformat() for e in page['events']):raise ValueError('Replay exposed future event')
            replay_checks+=2
        entry={'template':template,'artifact_path':result.artifact_path,'children':len(record['children']),'replay_cursor_checks':replay_checks,'status':record['status']}
        results.append(entry);print(encode(entry),flush=True)
    (args.output/'result.json').write_text(encode(results))
