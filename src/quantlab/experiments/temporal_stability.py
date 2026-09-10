"""Prespecified, disjoint time subsamples with label-boundary protection."""
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
import math
import polars as pl
from quantlab.statistics.bootstrap import BootstrapConfig
from quantlab.statistics.permutation import PermutationConfig, holm
from quantlab.statistics.independent_blocks import independent_mean_difference
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore, load_identity


def label_safe_frame(path, record, horizon, start, end):
    cfg = record['manifest']['config']; label = f'forward_{horizon}'
    if not date.fromisoformat(cfg['data']['start']) <= start <= end <= date.fromisoformat(cfg['data']['end']):
        raise ValueError('Subsample lies outside the saved research interval')
    frame = pl.read_parquet(path/'observations.parquet')
    if label not in frame.columns: raise ValueError('Horizon missing from artifact')
    endpoint = f'label_end_{horizon}'
    if endpoint not in frame.columns:
        if not (path/'bars.parquet').is_file():
            raise ValueError('Label end times or frozen bars required; rerun with replay enabled')
        bars = pl.read_parquet(path/'bars.parquet').sort('symbol', 'datetime')
        ends = bars.select('symbol', 'datetime',
            pl.col('datetime').shift(-horizon).over('symbol').alias(endpoint))
        frame = frame.join(ends, on=['symbol', 'datetime'], how='left', validate='1:1')
    frame = frame.filter(pl.col('datetime').dt.date().is_between(start, end))
    safe = pl.col(endpoint).is_not_null() & (pl.col(endpoint).dt.date() <= end)
    purged = frame.filter(pl.col(label).is_not_null() & ~safe.fill_null(False)).height
    frame = frame.with_columns(pl.when(safe).then(pl.col(label)).otherwise(None).alias(label))
    return frame, purged


def run_temporal_stability(plan, output, *, source_paths=None):
    from quantlab.experiments.stability import daily_ic
    from quantlab.experiments.runner import runtime_fingerprint
    required = {'name','comparison_kind','comparisons','permutation','bootstrap'}
    if set(plan) != required or not plan['name'] or not plan['comparisons']:
        raise ValueError('Require a named, nonempty, fixed temporal comparison plan')
    pc = PermutationConfig(**plan['permutation']); bc = BootstrapConfig(**plan['bootstrap'])
    local_alpha = pc.alpha/len(plan['comparisons'])
    if local_alpha >= .5: raise ValueError('Equivalence alpha must be below 0.5')
    rows = []; sources = []; panels = []; seen = set()
    fields = {'name','candidate','baseline','candidate_start','candidate_end',
        'baseline_start','baseline_end','horizon','equivalence_margin',
        'candidate_symbols','baseline_symbols'}
    for item in plan['comparisons']:
        if set(item) != fields: raise ValueError('Invalid temporal comparison fields')
        if not item['name'] or item['name'] in seen: raise ValueError('Duplicate/empty comparison name')
        seen.add(item['name']); h = item['horizon']; margin = item['equivalence_margin']
        if type(h) is not int or h < 1: raise ValueError('Invalid horizon')
        if type(margin) not in (float,int) or not math.isfinite(margin) or not 0 < margin <= 2:
            raise ValueError('Require a predefined positive Rank IC margin <= 2')
        periods = [(date.fromisoformat(item[k+'_start']), date.fromisoformat(item[k+'_end'])) for k in ('candidate','baseline')]
        if any(a > b for a,b in periods): raise ValueError('Invalid temporal period')
        if max(a for a,b in periods) <= min(b for a,b in periods):
            raise ValueError('Temporal subsamples must not overlap')
        paths = [Path(source_paths[str(Path(item[k]))]) if source_paths is not None else Path(item[k]) for k in ('candidate','baseline')]
        records = [load_identity(path/'experiment.json') for path in paths]
        if any(r.get('status') != 'completed' or r.get('kind','factor') != 'factor' for r in records):
            raise ValueError('Completed factor artifacts required')
        for field in ('factor','factor_code_hash'):
            if records[0]['manifest'].get(field)!=records[1]['manifest'].get(field):
                raise ValueError('Temporal comparison requires the same implemented factor: '+field)
        configs = [r['manifest']['config'] for r in records]
        for field in ('factor_id','factor_version','parameters','context','processor','regime','regime_filter'):
            if configs[0].get(field) != configs[1].get(field):
                raise ValueError('Temporal comparison must preserve '+field)
        if configs[0]['data']['timeframe'] != configs[1]['data']['timeframe']:
            raise ValueError('Temporal comparison requires the same bar timeframe')
        snapshots = [r['manifest']['data_snapshot'] for r in records]
        if snapshots[0].get('adjustment') != snapshots[1].get('adjustment'):
            raise ValueError('Price adjustment conventions differ')
        series = []; hashes = []; boundary_audit = []
        for side,path,record,period in zip(('candidate','baseline'),paths,records,periods):
            symbols = item[side+'_symbols']
            if not isinstance(symbols,list) or len(symbols)<3 or any(not isinstance(s,str) or not s for s in symbols) or len(set(symbols))!=len(symbols):
                raise ValueError('Each temporal sample requires >=3 distinct explicit symbols')
            frame,purged = label_safe_frame(path,record,h,*period)
            if set(symbols)-set(frame['symbol'].unique()): raise ValueError('Sample symbols absent in selected period')
            frame = frame.filter(pl.col('symbol').is_in(symbols))
            grid = frame.select(pl.col('datetime').dt.date().alias('date')).unique().sort('date')
            daily = grid.join(daily_ic(frame,h,*period),on='date',how='left',validate='1:1')
            series.append(daily['value'].to_list())
            panels.append(daily.with_columns(pl.lit(item['name']).alias('comparison'),pl.lit(side).alias('sample')))
            hashes.append(digest(frame.select('symbol','datetime','value',f'forward_{h}',f'label_end_{h}').write_json()))
            boundary_audit.append({'sample':side,'start':str(period[0]),'end':str(period[1]),'purged_labels':purged})
            sources.append({'run_id':record['run_id'],'artifact_path':str(path.resolve()),'name':item['name']})
        seed = int(digest(item),16)
        test = independent_mean_difference(*series,BootstrapConfig(pc.resamples,pc.block_days,bc.confidence),seed)
        interval = independent_mean_difference(*series,BootstrapConfig(bc.resamples,bc.block_days,1-2*local_alpha),seed)
        enough = interval['resamples_used']*local_alpha >= 10
        computed = interval['status']=='computed' and enough
        rows.append({'name':item['name'],'horizon':h,'estimate':test['estimate'],
            'test':test,'interval':interval,'source_hashes':hashes,'label_boundary_audit':boundary_audit,
            'equivalence':{'margin':margin,'family_alpha':pc.alpha,'comparison_alpha':local_alpha,
                'method':'independent_date_block_interval_bonferroni_v1','interval':interval,
                'status':'computed' if computed else 'unavailable',
                'reason':None if computed else interval.get('reason') or 'insufficient_resamples_in_tail',
                'equivalent':interval['ci_low']>-margin and interval['ci_high']<margin if computed else None,
                'candidate_symbols':item['candidate_symbols'],'baseline_symbols':item['baseline_symbols']}})
    for row,p in zip(rows,holm([r['test']['p_value'] for r in rows])):
        row.update(p_holm=p,reject_equal_mean=p<=pc.alpha if p is not None else None)
    summary = {'method':'temporal_subsample_equivalence','comparisons':rows,'planned_tests':len(rows),
        'limitations':'Disjoint prespecified time periods; independent circular date-block bootstrap with unequal lengths and missing dates retained. Requires within-period weak stationarity and negligible cross-period dependence; nonstationarity or adjacent regimes can invalidate inference. Earlier-end labels are purged, not reused. Complete corrected intervals inside a prespecified margin support approximate equivalence, not future alpha or preregistration. Different stock selections add cohort confounding. No paired-date sign test or automatic period selection.'}
    manifest = {'runtime':runtime_fingerprint(),'config':{'research_question':plan['name']},
        'plan':plan,'code_hash':digest(Path(__file__).read_text())}
    run_id = str(uuid4())
    record = {'run_id':run_id,'experiment_id':digest(manifest),'status':'completed','kind':'stability',
        'created_at':datetime.now(timezone.utc).isoformat(),'manifest':manifest,'summary':summary,'children':sources}
    path = LocalExperimentStore(output).save(run_id,record,pl.concat(panels))
    return {'run_id':run_id,'artifact_path':str(path),'summary':summary}
