"""Paired net daily return differences on comparable saved execution accounts."""
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import polars as pl
from quantlab.statistics.bootstrap import BootstrapConfig,block_mean_interval
from quantlab.statistics.permutation import PermutationConfig,block_sign_test
from quantlab.storage.experiments import LocalExperimentStore,load_identity
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.codec import digest


def compare_returns(candidate,baseline,start,output):
    paths=[Path(candidate),Path(baseline)];records=[load_identity(p/'experiment.json') for p in paths]
    if any(r.get('kind')!='execution' or r.get('status')!='completed' for r in records):raise ValueError('Completed execution accounts required')
    for key in ('data_snapshot','universe','execution','portfolio','backend','market_rules'):
        if records[0]['manifest'].get(key)!=records[1]['manifest'].get(key):raise ValueError('Incomparable accounts: '+key)
    curves=[pl.read_parquet(p/'observations.parquet').sort('datetime') for p in paths]
    if curves[0]['datetime'].to_list()!=curves[1]['datetime'].to_list():raise ValueError('Account valuation clocks must match exactly')
    daily=[]
    for curve,r in zip(curves,records):
        f=curve.with_columns(pl.col('datetime').dt.date().alias('date')).group_by('date').agg(pl.col('equity').last()).sort('date')
        f=f.with_columns((pl.col('equity')/pl.col('equity').shift(1).fill_null(r['manifest']['execution']['initial_cash'])-1).alias('return'))
        daily.append(f.filter(pl.col('date')>=start))
    frame=daily[0].join(daily[1],on='date',suffix='_baseline',validate='1:1').with_columns((pl.col('return')-pl.col('return_baseline')).alias('difference'))
    if frame.height<2:raise ValueError('Insufficient evaluation days')
    values=frame['difference'].to_list()
    summary={'method':'paired_net_daily_return_difference','evaluation_start':start,'days':frame.height,
        'mean_daily_difference':frame['difference'].mean(),'bootstrap':block_mean_interval(values,BootstrapConfig(),0),
        'permutation':block_sign_test(values,PermutationConfig(),0),
        'limitations':'Net simulation return difference, not risk-adjusted regression alpha or causal attribution. Shared initial conditions and costs required. Evaluation carries prior positions; start date does not liquidate or retrain. Repeated comparisons require a separately planned multiplicity family.'}
    manifest={'runtime':runtime_fingerprint(),'config':{'research_question':'相同约束下的组合净收益增量比较','data':records[0]['manifest']['config']['data']},
        'evaluation_start':start,'source_experiments':[r['experiment_id'] for r in records],
        'curve_hashes':[digest(f.write_json()) for f in curves],'code_hash':digest(Path(__file__).read_text())}
    run_id=str(uuid4());record={'run_id':run_id,'experiment_id':digest(manifest),'created_at':datetime.now(timezone.utc).isoformat(),
        'status':'completed','kind':'return_increment','manifest':manifest,'summary':summary,
        'children':[{'name':name,'run_id':r['run_id'],'artifact_path':str(p.resolve())} for name,r,p in zip(('候选组合','基准组合'),records,paths)]}
    path=LocalExperimentStore(output).save(run_id,record,frame)
    return {'run_id':run_id,'artifact_path':str(path),'summary':summary}
