"""Descriptive nested-event comparison over already archived observations.

The caller verifies archive identities, conditions, original labels and keys.
No factor fitting, new labels, hypothesis selection, execution or persistence.
"""
import math
import polars as pl


def _mean(series):
    values = series.filter(series.is_finite())
    return float(values.mean()) if len(values) else None


def _tail(series):
    values = series.filter(series.is_finite()).sort()
    count = math.ceil(len(values) * .05)
    return {'count':len(values), 'tail_count':count,
            'q05':float(values.quantile(.05, interpolation='linear')) if len(values) else None,
            'worst_5pct_mean':float(values.head(count).mean()) if count else None}


def _describe(frame, label, risk):
    daily = frame.group_by('datetime').agg(pl.col(label).mean().alias('mean'))
    result = {'events':frame.height, 'dates':daily.height,
              'date_equal_mean_return':_mean(daily['mean']),
              'event_equal_mean_return':_mean(frame[label]),
              'positive_fraction':float((frame[label] > 0).mean()) if frame.height else None,
              'return_tail':_tail(frame[label]), 'mae_available':risk is not None,
              'mean_mae':None, 'mae_tail':None, 'mae_missing_events':frame.height}
    if risk is not None:
        result.update(mean_mae=_mean(frame[risk]), mae_tail=_tail(frame[risk]),
                      mae_missing_events=frame[risk].null_count())
    return result


def _pair(left, right, column):
    a = left.filter(pl.col(column).is_finite()).group_by('datetime').agg(pl.col(column).mean().alias('left'))
    b = right.filter(pl.col(column).is_finite()).group_by('datetime').agg(pl.col(column).mean().alias('right'))
    pair = a.join(b, on='datetime', validate='1:1')
    return {'dates':pair.height, 'selected':_mean(pair['left']), 'reference':_mean(pair['right']),
            'difference':_mean(pair['left']-pair['right']),
            'weighting':'equal matched dates; equal securities within each date; overlapping windows are not independent'}


def conditional_event_review(common, horizon, *, risk_available=False):
    """Baseline value==1 defines the opportunity set, before using future labels.

    Missing candidate values are UNKNOWN, never rejected signals. A candidate
    triggering outside the known baseline is not a nested filter: do not compare
    it as if it were. Match dates to separate selection from market timing.
    """
    label = f'forward_{horizon}'; risk = f'mae_{horizon}' if risk_available else None
    for column in ('candidate','baseline'):
        if common.filter(pl.col(column).is_not_null() & ~pl.col(column).is_in([0.,1.])).height:
            raise ValueError('Conditional event comparison requires binary 0/1/null values')
    result = {'method':'nested_event_review_v1', 'status':'unavailable',
              'cohort_rule':'baseline==1, then candidate==1 selected and candidate==0 rejected; missing is unknown',
              'horizon':horizon, 'p_value':None, 'alpha_verified':False, 'new_research_jobs':0,
              'limitation':'Descriptive, previously specified cohort only. Close labels are not fills. No costs, risk-neutral matching, preregistration certificate or cross-study correction. Tails are event-weighted, ceil(5%*n); no iid assumption.'}
    outside = common.filter((pl.col('candidate') == 1) & ((pl.col('baseline') != 1) | pl.col('baseline').is_null())).height
    result['candidate_triggered_outside_baseline'] = outside
    if outside:
        result['status'] = 'not_a_nested_filter'
        return result
    cohort = common.filter(pl.col('baseline') == 1)
    ready = cohort.filter(pl.col('candidate').is_not_null())
    selected = ready.filter(pl.col('candidate') == 1)
    rejected = ready.filter(pl.col('candidate') == 0)
    mature = ready.filter(pl.col(label).is_finite())
    selected_mature = selected.filter(pl.col(label).is_finite())
    rejected_mature = rejected.filter(pl.col(label).is_finite())
    selected_dates = selected_mature.select('datetime').unique()
    matched_baseline = mature.join(selected_dates, on='datetime', how='semi')
    coverage = {'baseline_events':cohort.height,
                'candidate_ready_baseline_events':ready.height,
                'candidate_unknown_baseline_events':cohort.height-ready.height,
                'selected_events':selected.height, 'rejected_events':rejected.height,
                'selected_mature_events':selected_mature.height,
                'selected_pending_events':selected.height-selected_mature.height,
                'rejected_mature_events':rejected_mature.height,
                'rejected_pending_events':rejected.height-rejected_mature.height,
                'baseline_mature_dates':mature['datetime'].n_unique(),
                'selected_mature_dates':selected_dates.height,
                'baseline_mature_dates_without_selection':mature['datetime'].n_unique()-selected_dates.height}
    result.update(coverage=coverage,
        baseline_all_mature=_describe(cohort.filter(pl.col(label).is_finite()),label,risk),
        selected=_describe(selected_mature,label,risk),
        rejected=_describe(rejected_mature,label,risk),
        baseline_on_selected_dates=_describe(matched_baseline,label,risk),
        paired_return_vs_baseline=_pair(selected_mature,mature,label),
        paired_return_vs_rejected=_pair(selected_mature,rejected_mature,label),
        paired_mae_vs_baseline=_pair(selected_mature,mature,risk) if risk is not None else None,
        paired_mae_vs_rejected=_pair(selected_mature,rejected_mature,risk) if risk is not None else None)
    result['status'] = ('no_selected_mature_events' if not selected_mature.height else
                        'no_rejected_mature_events' if not rejected_mature.height else
                        'no_same_date_selected_rejected' if not result['paired_return_vs_rejected']['dates'] else
                        'descriptive_comparison')
    result['mae_policy'] = ('Saved adverse excursion uses the original future window. Null/incomplete paths excluded from risk summaries, counted separately. Less negative is better; not a realizable stop loss.')
    return result
