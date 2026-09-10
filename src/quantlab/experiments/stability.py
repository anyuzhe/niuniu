"""Explicit date-block tests of paired parameter IC changes."""
from datetime import date,datetime,timezone
from pathlib import Path
from uuid import uuid4
import math
import re
import polars as pl
from quantlab.statistics.bootstrap import BootstrapConfig,block_mean_interval
from quantlab.statistics.permutation import PermutationConfig,block_sign_test,holm
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.codec import digest,encode
from quantlab.storage.experiments import LocalExperimentStore,load_identity


def daily_ic(frame,horizon,start,end):
    frame=frame.filter(pl.col('datetime').dt.date().is_between(start,end))
    label='forward_'+str(horizon)
    frame=frame.filter(pl.col('value').is_finite() & pl.col(label).is_finite())
    return frame.group_by('datetime').agg(pl.len().alias('n'),pl.corr('value',label,method='spearman').alias('value')).filter(pl.col('n')>=3).with_columns(pl.col('datetime').dt.date().alias('date')).group_by('date').agg(pl.col('value').filter(pl.col('value').is_finite()).mean()).sort('date')


def run_stability(plan, output, *, source_paths=None):
    """Test changes, not equivalence: non-rejection is not proof of stability.

    Each item specifies two saved research paths and a shared label-safe period.
    End dates must match the artifact's existing label boundary: archived future
    labels must not be silently reused across a newly chosen earlier endpoint.
    """
    required={'name','comparisons','permutation','bootstrap'}
    if set(plan)-required-{'comparison_kind'} or not required<=set(plan) or not plan['name'] or not plan['comparisons']:raise ValueError('Require name, comparisons, permutation, bootstrap')
    kind=plan.get('comparison_kind','parameter_change')
    if kind not in ('parameter_change','subsample_equivalence','cross_market_equivalence'):raise ValueError('Unknown comparison kind')
    cohorts=kind!='parameter_change'
    pc=PermutationConfig(**plan['permutation']);bc=BootstrapConfig(**plan['bootstrap'])
    rows=[];sources=[];identities=set();frames=[]
    for item in plan['comparisons']:
        keys={'name','candidate','baseline','start','end','horizon'}|({'candidate_symbols','baseline_symbols','equivalence_margin'} if cohorts else set())
        if set(item)!=keys:raise ValueError('Invalid comparison fields')
        if cohorts:
            margin=item['equivalence_margin']
            if type(margin) not in (int,float) or not math.isfinite(margin) or not 0<margin<=2:raise ValueError('Require a predefined positive Rank IC margin no greater than 2')
            selections=[item[k+'_symbols'] for k in ('candidate','baseline')]
            if any(not isinstance(v,list) or len(v)<3 or any(not isinstance(s,str) or not s for s in v) or len(v)!=len(set(v)) for v in selections):raise ValueError('Each cohort requires at least three distinct symbols')
            if set(selections[0])&set(selections[1]):raise ValueError('Subsample cohorts must not overlap')
            if kind=='cross_market_equivalence':
                markets=[{s.split('.')[0] for s in v} for v in selections]
                if any(not re.fullmatch(r'(sh|sz)\.\d{6}',s) for v in selections for s in v) or any(len(v)!=1 for v in markets) or markets[0]==markets[1]:raise ValueError('Cross-market validation requires separate Shanghai and Shenzhen cohorts')
        if item['name'] in identities:raise ValueError('Duplicate comparison name')
        identities.add(item['name']);start=date.fromisoformat(item['start']);end=date.fromisoformat(item['end']);h=item['horizon']
        if start>end or type(h) is not int or h<1:raise ValueError('Invalid stability period/horizon')
        paths=[Path(source_paths[str(Path(item[k]))]) if source_paths is not None else Path(item[k]) for k in ('candidate','baseline')]
        records=[load_identity(p/'experiment.json') for p in paths]
        if any(r.get('status')!='completed' or r.get('kind','factor')!='factor' for r in records):raise ValueError('Completed factor observation artifacts required')
        for field in ('data_snapshot','universe'):
            if records[0]['manifest'].get(field)!=records[1]['manifest'].get(field):raise ValueError('Stability comparison requires identical '+field)
        for field in ('factor_id','factor_version','context','processor','regime','regime_filter'):
            if records[0]['manifest']['config'].get(field)!=records[1]['manifest']['config'].get(field):raise ValueError('Parameter stability must preserve '+field)
        if cohorts and records[0]['manifest']['config'].get('parameters')!=records[1]['manifest']['config'].get('parameters'):raise ValueError('Cohort validation must preserve factor parameters')
        values=[]
        for path,r in zip(paths,records):
            cfg=r['manifest']['config']
            if end.isoformat()!=cfg['data']['end'] or start<date.fromisoformat(cfg['data']['start']):raise ValueError('Evaluation end must equal the saved label boundary; rerun a holdout for a different end')
            frame=pl.read_parquet(path/'observations.parquet')
            if 'forward_'+str(h) not in frame.columns:raise ValueError('Horizon missing from artifact')
            values.append(frame)
            sources.append({'run_id':r['run_id'],'artifact_path':str(path.resolve()),'name':item['name']})
        # The comparison uses exactly the same security-date samples for both
        # variants, not ICs from independently dropped rows.
        if cohorts:
            if any(set(symbols)-set(value['symbol'].unique()) for value,symbols in zip(values,selections)):raise ValueError('Requested cohort symbols are absent from source observations')
            series=[daily_ic(value.filter(pl.col('symbol').is_in(symbols)),h,start,end) for value,symbols in zip(values,selections)]
        else:
            common=values[0].select('symbol','datetime',pl.col('value').alias('candidate'),'forward_'+str(h)).join(values[1].select('symbol','datetime',pl.col('value').alias('baseline'),pl.col('forward_'+str(h)).alias('baseline_label')),on=['symbol','datetime'],validate='1:1')
            common=common.filter(pl.col('candidate').is_finite() & pl.col('baseline').is_finite() & pl.col('forward_'+str(h)).is_finite() & pl.col('baseline_label').is_finite())
            if common.filter(pl.col('forward_'+str(h))!=pl.col('baseline_label')).height:raise ValueError('Paired research labels differ')
            series=[daily_ic(common.rename({key:'value'}),h,start,end) for key in ('candidate','baseline')]
        grid=pl.concat([v.select(pl.col('datetime').dt.date().alias('date')) for v in values]).unique().filter(pl.col('date').is_between(start,end)).sort('date')
        panel=grid.join(series[0],on='date',how='left').join(series[1],on='date',how='left',suffix='_baseline').with_columns((pl.col('value')-pl.col('value_baseline')).alias('difference'))
        differences=panel['difference'].to_list();seed=int(digest(item),16)
        test=block_sign_test(differences,pc,seed)
        rows.append({'name':item['name'],'horizon':h,'dates':panel.height,'estimate':panel['difference'].mean(),'test':test,'interval':block_mean_interval(differences,bc,seed),'source_hashes':[digest(v.select('symbol','datetime','value','forward_'+str(h)).write_json()) for v in values]})
        if cohorts:
            local_alpha=pc.alpha/len(plan['comparisons'])
            if local_alpha>=.5:raise ValueError('Equivalence requires per-comparison alpha below 0.5')
            interval=block_mean_interval(differences,BootstrapConfig(bc.resamples,bc.block_days,1-2*local_alpha),seed)
            enough_tail_samples=bc.resamples*local_alpha>=10
            computed=interval['status']=='computed' and enough_tail_samples
            rows[-1]['equivalence']={'margin':margin,'family_alpha':pc.alpha,'comparison_alpha':local_alpha,
                'method':'circular_date_block_percentile_interval_bonferroni_v1','interval':interval,
                'status':'computed' if computed else 'unavailable',
                'reason':None if computed else (interval.get('reason') or 'insufficient_resamples_in_tail'),
                'equivalent':interval['ci_low']>-margin and interval['ci_high']<margin if computed else None,
                'candidate_symbols':selections[0],'baseline_symbols':selections[1],
                'paired_valid_dates':panel['difference'].count()}
        frames.append(panel.with_columns(pl.lit(item['name']).alias('comparison')))
    adjusted=holm([r['test'].get('p_value') for r in rows])
    for r,p in zip(rows,adjusted):r.update(p_holm=p,reject_equal_mean=p<=pc.alpha if p is not None else None)
    manifest={'runtime':runtime_fingerprint(),'config':{'research_question':plan['name']},'plan':plan,'code_hash':digest(Path(__file__).read_text())}
    summary={'method':'paired_parameter_daily_rank_ic_change','comparisons':rows,'planned_tests':len(rows),
        'limitations':'Explicit pairwise parameter comparisons on common security-date rows. Date-block sign tests and Holm; failure to reject is not an equivalence/stability proof. No automatic parameter selection. Date range and comparisons must be frozen before result inspection. Subsample equivalence and cross-market validation are separate.'}
    if cohorts:
        summary.update(method=kind,limitations='Predefined disjoint stock cohorts with unchanged factor parameters on paired dates. Equivalence requires the entire 1-2*alpha/m circular-date-block percentile interval strictly inside the predefined margin; unavailable comparisons retain the family denominator. Approximate bootstrap inference, not an exact finite-sample TOST. No automatic selection or proof of future profitability. Cohorts and margin must be chosen before inspection; existing archives do not establish preregistration. Cross-market means Shanghai versus Shenzhen only; historical eligibility and data-source limitations still apply.',
            statistical_reference='https://pmc.ncbi.nlm.nih.gov/articles/PMC5502906/')
    run_id=str(uuid4());record={'run_id':run_id,'experiment_id':digest(manifest),'status':'completed','kind':'stability','created_at':datetime.now(timezone.utc).isoformat(),'manifest':manifest,'summary':summary,'children':sources}
    path=LocalExperimentStore(output).save(run_id,record,pl.concat(frames))
    return {'run_id':run_id,'artifact_path':str(path),'summary':summary}
