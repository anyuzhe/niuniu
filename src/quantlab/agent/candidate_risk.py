"""Fixed descriptive risk sensitivity using only already archived observations.

No factor/label recomputation, statistical test, account simulation or persistence.
Greedy scheduling uses baseline signals and saved calendar endpoints, never risk,
returns, candidate membership or maturity. Both schedules are always reported.
"""
from datetime import date
import hashlib
from pathlib import Path

import polars as pl
from quantlab.agent.conditional_events import _tail
from quantlab.storage.codec import digest, encode
from quantlab.storage.artifact_integrity import verify_tree

METHOD = 'matched_nested_risk_audit_v1'
LIMITATIONS = [
    'Post-exploration descriptive sensitivity, not independent confirmation, p-values or causal risk attribution.',
    'Selected and rejected are disjoint within baseline==1. Match dates only after requiring finite saved forward return AND MAE.',
    'Tail means are event-weighted, ceil(5%*n); date-paired means are date-weighted. Their magnitudes are not interchangeable.',
    'Nonoverlap is per security and stage only; it does not remove cross-security dependence or prove independent observations.',
    'Saved close labels and future lows are not fills, stop losses, portfolio drawdown or cost-adjusted returns.',
    'No industry/size/volatility-exposure neutralization, PIT qualification or automatic watch/strategy promotion.',
]


def _mean(values):
    return float(values.mean()) if len(values) else None


def _difference(left, right):
    return left-right if left is not None and right is not None else None


def _keys(frame):
    sha=hashlib.sha256()
    for row in frame.sort(['symbol','datetime']).select('symbol','datetime').iter_rows():
        sha.update(encode([row[0],row[1].isoformat()]).encode('utf-8'));sha.update(b'\n')
    return sha.hexdigest()


def _scheduled(cohort, endpoint):
    """Retain the first baseline signal, then strictly AFTER its saved end time.

    The fixed end time is calendar metadata, not a realized outcome. A final
    signal with no endpoint stays pending and blocks further selection in that
    security; missing forward/MAE does not cause replacement by a later winner.
    """
    locks={};keep=[]
    for row in cohort.select('symbol','datetime',endpoint).iter_rows(named=True):
        symbol=row['symbol'];stamp=row['datetime']
        take=symbol not in locks or (locks[symbol] is not None and stamp>locks[symbol])
        keep.append(take)
        if take:locks[symbol]=row[endpoint]
    return cohort.filter(pl.Series('_keep',keep,dtype=pl.Boolean))


def _group(frame, label, risk):
    return {'events':frame.height,'securities':frame['symbol'].n_unique(),
            'dates':frame['datetime'].n_unique(),
            'event_equal_mean_return':_mean(frame[label]),'event_equal_mean_mae':_mean(frame[risk]),
            'return_tail':_tail(frame[label]),'mae_tail':_tail(frame[risk])}


def _panel(cohort, scheduled, label, risk, endpoint):
    known=scheduled.filter(pl.col('candidate').is_not_null())
    mature=known.filter(pl.col(label).is_finite())
    complete=mature.filter(pl.col(risk).is_finite())
    left=complete.filter(pl.col('candidate')==1);right=complete.filter(pl.col('candidate')==0)
    dates=left.select('datetime').unique().join(right.select('datetime').unique(),on='datetime',validate='1:1')
    left=left.join(dates,on='datetime',how='semi');right=right.join(dates,on='datetime',how='semi')
    matched=pl.concat([left,right]).sort(['symbol','datetime'])
    daily_left=left.group_by('datetime').agg(pl.col(label).mean().alias('return'),pl.col(risk).mean().alias('mae'))
    daily_right=right.group_by('datetime').agg(pl.col(label).mean().alias('return'),pl.col(risk).mean().alias('mae'))
    paired=daily_left.join(daily_right,on='datetime',suffix='_reference',validate='1:1').sort('datetime')
    pairs={}
    for name in ('return','mae'):
        delta=paired[name]-paired[name+'_reference']
        pairs[name]={'selected':_mean(paired[name]),'rejected':_mean(paired[name+'_reference']),
                     'difference':_mean(delta),'matched_dates':paired.height,
                     'positive_date_fraction':float((delta>0).mean()) if paired.height else None}
    a=_group(left,label,risk);b=_group(right,label,risk)
    return {'status':'descriptive_comparison' if paired.height else 'no_common_complete_dates',
            'coverage':{'baseline_events':cohort.height,'scheduled_baseline_events':scheduled.height,
                'overlap_excluded_events':cohort.height-scheduled.height,
                'unknown_candidate_events':scheduled.height-known.height,
                'selected_signals':known.filter(pl.col('candidate')==1).height,
                'rejected_signals':known.filter(pl.col('candidate')==0).height,
                'pending_forward_events':known.height-mature.height,
                'mature_missing_mae_events':mature.height-complete.height,
                'complete_before_date_match':complete.height,
                'events_without_opposite_group_date':complete.height-matched.height,
                'matched_events':matched.height,'matched_dates':paired.height},
            'scheduled_key_sha256':_keys(scheduled),'matched_key_sha256':_keys(matched),
            'selected':a,'rejected':b,'date_equal_pairs':pairs,
            'event_equal_mae_tail_difference':_difference(a['mae_tail']['worst_5pct_mean'],b['mae_tail']['worst_5pct_mean']),
            'event_equal_return_tail_difference':_difference(a['return_tail']['worst_5pct_mean'],b['return_tail']['worst_5pct_mean']),
            'units':'returns and MAE are fractions; multiply differences by 100 for percentage points; positive MAE difference is less adverse'}


def risk_panels(common, horizon):
    if type(horizon) is not int or not 1<=horizon<=1000:raise ValueError('Invalid risk-audit horizon')
    label=f'forward_{horizon}';risk=f'mae_{horizon}';endpoint=f'label_end_{horizon}'
    required={'symbol','datetime','candidate','baseline',label,risk,endpoint}
    if not required<=set(common.columns):raise ValueError('Risk audit requires saved forward, MAE and calendar endpoint')
    if common.height>250000:raise ValueError('Risk audit exceeds 250000 observations')
    if common.select(pl.struct('symbol','datetime').is_duplicated().any()).item():raise ValueError('Duplicate risk-audit keys')
    if any(common[c].null_count() for c in ('symbol','datetime')):raise ValueError('Missing risk-audit key')
    for name in ('candidate','baseline'):
        if common.filter(pl.col(name).is_not_null() & ~pl.col(name).is_in([0.,1.])).height:raise ValueError('Risk audit requires binary 0/1/null')
    for name in (label,risk):
        if common.filter(pl.col(name).is_not_null() & ~pl.col(name).is_finite()).height:raise ValueError('Nonfinite saved risk/return')
    if common.filter(pl.col(risk)>0).height:raise ValueError('Positive MAE is invalid')
    if common.filter(pl.col(endpoint).is_not_null() & (pl.col(endpoint)<=pl.col('datetime'))).height:raise ValueError('Invalid saved label endpoint')
    if common.filter((pl.col(label).is_not_null() | pl.col(risk).is_not_null()) & pl.col(endpoint).is_null()).height:raise ValueError('Saved outcome without endpoint')
    result={'method':METHOD,'horizon':horizon,'p_value':None,'alpha_verified':False,
            'new_research_jobs':0,'label_recomputed':False,'limitations':LIMITATIONS}
    if common.filter((pl.col('candidate')==1)&((pl.col('baseline')!=1)|pl.col('baseline').is_null())).height:
        return {**result,'status':'not_a_nested_filter','panels':{}}
    cohort=common.filter(pl.col('baseline')==1).sort(['symbol','datetime'])
    scheduled=_scheduled(cohort,endpoint)
    return {**result,'status':'descriptive_sensitivity','reference':'candidate==0 within baseline==1; never baseline including selected',
            'schedule_policy':'Per symbol/stage: earliest baseline==1, then datetime strictly after saved label_end_h. Unknown candidate and missing outcomes retain cooldown. No retuning.',
            'panels':{'all_signals':_panel(cohort,cohort,label,risk,endpoint),
                      'nonoverlapping':_panel(cohort,scheduled,label,risk,endpoint)}}


def audit_candidate_risk(output,candidate_run_id,baseline_run_id,horizon):
    from quantlab.agent.candidate_review import _load_candidate_pair
    catalog,trees,records,frames,common,runtime_note=_load_candidate_pair(output,candidate_run_id,baseline_run_id,horizon)
    if any(r['manifest'].get('factor',{}).get('factor_type')!='boolean' for r in records):
        raise ValueError('Risk audit requires two archived boolean factors')
    if common.height!=frames[0].height or common.height!=frames[1].height:
        raise ValueError('Risk audit requires identical saved key sets; missing rows cannot be silently removed')
    risk=f'mae_{horizon}';other='baseline_'+risk;endpoint=f'label_end_{horizon}'
    if risk not in common.columns or other not in common.columns:raise ValueError('Risk audit requires saved MAE in both sources')
    if not common[risk].equals(common[other]):raise ValueError('Saved MAE differs between sources')
    end=date.fromisoformat(records[0]['manifest']['config']['data']['end'])
    if common.filter(pl.col(endpoint).is_not_null() & (pl.col(endpoint).dt.date()>end)).height:
        raise ValueError('Risk-audit endpoint exceeds saved study interval')
    result=risk_panels(common,horizon)
    result.update(candidate_run_id=candidate_run_id,baseline_run_id=baseline_run_id,
        data=records[0]['manifest']['config']['data'],adjustment=records[0]['manifest']['data_snapshot']['adjustment'],
        source_fingerprints=[digest(t) for t in trees],runtime_compatibility=runtime_note,
        diagnostic_code_sha256=digest({name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('candidate_risk.py','candidate_review.py','conditional_events.py')}))
    result['report_digest']=digest(result)
    for tree in trees:verify_tree(catalog.root,tree)
    return json_or_value(result)


def json_or_value(value):
    # Standard archive codec rejects nonfinite output; the public API is JSON-only.
    import json
    return json.loads(encode(value))
