"""Anytime-valid Watch monitoring against a frozen empirical Rank-IC reference.

The e-process controls repeated looks in one Watch/horizon under its conditional-
mean null. It does not turn the frozen baseline sample into a known population
parameter and does not prove future profitability or regime causality.
"""
from __future__ import annotations

from datetime import datetime
from importlib import import_module
from math import exp, isfinite, log, log1p
from pathlib import Path

import polars as pl

from quantlab.data.validation import ordered_bars
from quantlab.experiments.research import FactorResearchEngine
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.storage.codec import digest
from quantlab.storage.experiments import load_record_fields
from quantlab.workbench.server import ArtifactCatalog

VERSION='daily-rank-ic-eprocess-v1'
LAMBDA_GRID=(0.05,0.10,0.20,0.30,0.40)

def sequential_fingerprint():
    modules=('quantlab.agent.watch_sequential','quantlab.experiments.research','quantlab.data.validation')
    return digest({'modules':{name:Path(import_module(name).__file__).read_text() for name in modules},
        'polars':pl.__version__})


def _validate_settings(alpha,min_effect,min_new_dates,block_sessions):
    if type(alpha) not in (int,float) or not isfinite(alpha) or not 0.001<=alpha<=0.2:
        raise ValueError('Sequential family alpha须在0.001–0.2')
    if type(min_effect) not in (int,float) or not isfinite(min_effect) or not 0<=min_effect<=0.5:
        raise ValueError('Sequential Rank IC最小衰减幅度须在0–0.5')
    if type(min_new_dates) is not int or not 1<=min_new_dates<=1000:
        raise ValueError('Sequential最少新增成熟日期须为1–1000')
    if type(block_sessions) is not int or not 1<=block_sessions<=20:
        raise ValueError('Sequential block_sessions须为1–20')


def _read_daily_series(output,run_id,as_of,expected_fingerprint):
    cutoff=datetime.fromisoformat(as_of)
    if cutoff.tzinfo is None:raise ValueError('Sequential cutoff必须带时区')
    catalog=ArtifactCatalog(output);tree=snapshot_tree(catalog.root,run_id)
    if digest(tree)!=expected_fingerprint:raise ValueError('Sequential source fingerprint changed before read')
    record=load_record_fields(catalog.file(run_id,'experiment.json'),{'run_id','status','kind','manifest'})
    if record['status']!='completed' or record.get('kind','factor')!='factor':raise ValueError('Sequential monitor需要已完成单因子归档')
    cfg=record['manifest']['config']
    if len(cfg['horizons'])>5 or len(cfg['data']['symbols'])>100:raise ValueError('Sequential monitor预算最多5个horizon和100只证券')
    frames=[]
    for name in ('bars.parquet','observations.parquet'):
        source=catalog.file(run_id,name)
        if source.stat().st_size>150_000_000:raise ValueError('Sequential source file exceeds 150MB')
        lazy=pl.scan_parquet(source)
        if lazy.select(pl.len()).collect().item()>250000:raise ValueError('Sequential source exceeds 250000 rows')
        frames.append(lazy.collect())
    bars=ordered_bars(frames[0]);observations=frames[1]
    if bars.filter(pl.col('available_at')!=pl.col('datetime')).height:
        raise ValueError('Sequential monitor暂不支持延迟发布bar')
    zone=bars.schema['available_at'].time_zone
    if zone is None:raise ValueError('Sequential source bar缺少时区')
    cutoff=cutoff.astimezone(__import__('zoneinfo').ZoneInfo(zone))
    known=bars.filter(pl.col('available_at')<=cutoff).sort('symbol','datetime')
    values=observations.select('symbol','datetime','available_at','value').filter(pl.col('available_at')<=cutoff).sort('symbol','datetime')
    if known.is_empty() or values.is_empty():raise ValueError('Sequential cutoff之前没有可用bar/因子值')
    mask=values.select('symbol','datetime',pl.lit(True).alias('eligible'))
    horizons=tuple(cfg['horizons'])
    _,labelled=FactorResearchEngine().evaluate(known,values,mask,horizons,cfg['quantiles'])
    series={}
    for horizon in horizons:
        label=f'forward_{horizon}';endpoint=f'label_end_{horizon}'
        valid=labelled.filter(pl.col('value').is_finite() & pl.col(label).is_finite() & pl.col(endpoint).is_not_null())
        by_time=valid.group_by('datetime').agg(pl.len().alias('n'),
            pl.corr('value',label,method='spearman').alias('rank_ic'),pl.col(endpoint).max().alias('mature_at'))
        daily=by_time.filter((pl.col('n')>=3)&pl.col('rank_ic').is_finite()).with_columns(
            pl.col('datetime').dt.date().alias('signal_date')).group_by('signal_date').agg(
            pl.col('rank_ic').mean().alias('rank_ic'),pl.col('mature_at').max().alias('mature_at'),pl.len().alias('timestamps'))
        daily=daily.sort('mature_at','signal_date')
        series[str(horizon)]=[{'signal_date':str(r['signal_date']),'rank_ic':float(r['rank_ic']),
            'mature_at':r['mature_at'].isoformat(),'timestamps':int(r['timestamps'])} for r in daily.to_dicts()]
    if digest(snapshot_tree(catalog.root,run_id))!=expected_fingerprint:
        raise ValueError('Sequential source changed during read')
    return cfg,series

def build_baseline(output,run_id,as_of,expected_fingerprint,min_dates,*,family_alpha=0.05,min_effect=0.02,min_new_dates=10,block_sessions=5):
    _validate_settings(family_alpha,min_effect,min_new_dates,block_sessions)
    if type(min_dates) is not int or not 1<=min_dates<=1000:raise ValueError('Sequential baseline min_dates无效')
    cfg,series=_read_daily_series(output,run_id,as_of,expected_fingerprint)
    horizons={};count=max(1,len(cfg['horizons']));local_alpha=float(family_alpha)/count
    for horizon in cfg['horizons']:
        rows=series[str(horizon)];values=[r['rank_ic'] for r in rows]
        ready=len(values)>=min_dates
        horizons[str(horizon)]={'status':'ready' if ready else 'insufficient_baseline',
            'reference_mean':sum(values)/len(values) if values else None,'valid_sessions':len(values),
            'first_signal_date':rows[0]['signal_date'] if rows else None,
            'last_signal_date':rows[-1]['signal_date'] if rows else None,
            'last_mature_at':rows[-1]['mature_at'] if rows else None,'local_alpha':local_alpha}
    return {'version':VERSION,'algorithm':sequential_fingerprint(),'family_alpha':float(family_alpha),
        'min_effect':float(min_effect),'min_new_dates':min_new_dates,'block_sessions':block_sessions,'baseline_min_dates':min_dates,
        'baseline_as_of':as_of,'horizons':horizons,
        'method':'nonoverlapping_block_rank_ic_mixture_e_process_against_frozen_empirical_reference',
        'lambda_grid':list(LAMBDA_GRID),
        'limitations':['Anytime-valid repeated-look control is relative to the frozen empirical baseline mean, not an unknown population mean.',
            'Family alpha is allocated across horizons inside one Watch; it does not correct across many adaptively selected Watches.',
            'New mature daily Rank IC is grouped into fixed non-overlapping blocks before betting; incomplete tail blocks never enter evidence.',
            'Validity requires bounded block Rank IC and the stated conditional-mean null; longer market dependence/regime selection can still weaken interpretation.',
            'Evidence of degradation is not automatic factor disablement, trading approval, or proof of future loss.']}


def _mixture_e_path(values,threshold):
    logs=[0.0 for _ in LAMBDA_GRID];path=[]
    for value in values:
        for i,lam in enumerate(LAMBDA_GRID):
            factor=1.0+lam*(threshold-value)
            if factor<=0:raise ValueError('Sequential betting factor became nonpositive')
            logs[i]+=log(factor)
        peak=max(logs);log_mix=peak+log(sum(exp(v-peak) for v in logs)/len(logs))
        path.append(exp(min(log_mix,700.0)))
    return path

def monitor(output,run_id,as_of,expected_fingerprint,baseline,*,historical_revision=False):
    if not isinstance(baseline,dict) or baseline.get('version')!=VERSION:raise ValueError('Sequential baseline格式无效')
    if baseline.get('algorithm')!=sequential_fingerprint():raise ValueError('Sequential monitor算法已变化；请新建Watch或正式换版')
    if historical_revision:
        return {'version':VERSION,'status':'HISTORICAL_REVISION_BLOCKED','as_of':as_of,'horizons':{},
            'limitations':['历史输入发生修订时不继续解释序贯衰减；先核对来源或重建基准。']}
    cfg,series=_read_daily_series(output,run_id,as_of,expected_fingerprint)
    if {str(h) for h in cfg['horizons']}!=set(baseline['horizons']):raise ValueError('Sequential horizons changed')
    cutoff=datetime.fromisoformat(baseline['baseline_as_of']);results={};degraded=[]
    for horizon in cfg['horizons']:
        key=str(horizon);base=baseline['horizons'][key];rows=[]
        for row in series[key]:
            if datetime.fromisoformat(row['mature_at'])>cutoff:rows.append(row)
        values=[r['rank_ic'] for r in rows];reference=base.get('reference_mean');local_alpha=base['local_alpha']
        threshold=None if reference is None else max(-1.0,min(1.0,reference-baseline['min_effect']))
        block=baseline.get('block_sessions',5);complete=len(values)//block
        block_values=[sum(values[i*block:(i+1)*block])/block for i in range(complete)]
        status='INSUFFICIENT_BASELINE' if base['status']!='ready' else 'INSUFFICIENT_NEW_DATES'
        current_e=max_e=1.0;crossed_at=None
        if base['status']=='ready' and threshold is not None and block_values:
            path=_mixture_e_path(block_values,threshold);current_e=path[-1];max_e=max(path)
            evidence_level=1.0/local_alpha
            for index,value in enumerate(path,1):
                used_dates=index*block
                if used_dates>=baseline['min_new_dates'] and value>=evidence_level:
                    crossed_at=rows[used_dates-1]['mature_at'];break
            if len(values)>=baseline['min_new_dates']:
                status='DEGRADATION_EVIDENCE' if crossed_at else 'NO_DECISIVE_CHANGE'
        else:evidence_level=1.0/local_alpha
        online_mean=sum(values)/len(values) if values else None
        result={'status':status,'baseline_reference_mean':reference,'degradation_threshold':threshold,
            'min_effect':baseline['min_effect'],'new_mature_sessions':len(values),'min_new_dates':baseline['min_new_dates'],
            'block_sessions':block,'complete_blocks':complete,'pending_block_sessions':len(values)-complete*block,
            'online_mean_rank_ic':online_mean,'observed_drop':reference-online_mean if reference is not None and online_mean is not None else None,
            'current_e_value':current_e,'max_e_value':max_e,'evidence_threshold':evidence_level,'first_crossed_at':crossed_at,
            'first_new_mature_at':rows[0]['mature_at'] if rows else None,'last_new_mature_at':rows[-1]['mature_at'] if rows else None}
        results[key]=result
        if status=='DEGRADATION_EVIDENCE':degraded.append(key)
    overall='DEGRADATION_EVIDENCE' if degraded else ('NO_DECISIVE_CHANGE' if any(v['status']=='NO_DECISIVE_CHANGE' for v in results.values()) else 'INSUFFICIENT')
    return {'version':VERSION,'status':overall,'as_of':as_of,'degraded_horizons':degraded,'horizons':results,
        'family_alpha':baseline['family_alpha'],'method':baseline['method'],'limitations':baseline['limitations']}


__all__=['VERSION','LAMBDA_GRID','sequential_fingerprint','build_baseline','monitor']
