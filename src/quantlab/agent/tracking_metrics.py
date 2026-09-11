"""Manual snapshot tracking: observed-session windows and mature gross labels."""
from datetime import datetime
import polars as pl
from zoneinfo import ZoneInfo
from quantlab.experiments.research import FactorResearchEngine
from quantlab.storage.codec import digest
from quantlab.data.validation import ordered_bars

VERSION='observed-session-mature-labels-v1'
KEYS=['symbol','datetime','available_at']


def compute_tracking(bars,observations,config,as_of,windows,min_dates):
    if not isinstance(as_of,datetime) or as_of.tzinfo is None:
        raise ValueError('Tracking cutoff requires an explicit timezone')
    bars=ordered_bars(bars)
    if observations.select(pl.struct('symbol','datetime').is_duplicated().any()).item():
        raise ValueError('Duplicate factor observations in source archive')
    if observations.filter(pl.col('value').is_not_null() & ~pl.col('value').is_finite()).height:
        raise ValueError('Nonfinite source factor observations')
    # The current research evaluator requires close-time availability. Do not
    # silently treat delayed provider data as immediately available.
    if bars.filter(pl.col('available_at')!=pl.col('datetime')).height:
        raise ValueError('Delayed bars require a separate publication-time tracking contract')
    zone=bars.schema['available_at'].time_zone
    if zone is None:raise ValueError('Archive bar timestamps require timezone')
    as_of=as_of.astimezone(ZoneInfo(zone))
    known=bars.filter(pl.col('available_at')<=as_of).sort('symbol','datetime')
    if known.is_empty(): raise ValueError('No completed bars before the tracking cutoff')
    values=observations.select(*KEYS,'value').filter(pl.col('available_at')<=as_of).sort('symbol','datetime')
    if values.is_empty(): raise ValueError('No eligible factor observations at the cutoff')
    mask=values.select('symbol','datetime',pl.lit(True).alias('eligible'))
    engine=FactorResearchEngine();horizons=tuple(config['horizons'])
    _,labelled=engine.evaluate(known,values,mask,horizons,config['quantiles'])
    sessions=known['datetime'].dt.date().unique().sort().to_list();results={}
    for window in windows:
        start=sessions[max(0,len(sessions)-window)]
        selected=values.filter(pl.col('datetime').dt.date()>=start)
        stats,_=engine.evaluate(known,selected,mask,horizons,config['quantiles'])
        sub=labelled.filter(pl.col('datetime').dt.date()>=start)
        clocks=known.filter(pl.col('datetime').dt.date()>=start)['datetime'].n_unique()
        expected=clocks*len(config['data']['symbols'])
        results[str(window)]={'start':str(start),'end':str(sessions[-1]),
            'observed_sessions':min(window,len(sessions)),'expected_symbol_bars':expected,
            'eligible_observations':sub.height,'missing_or_ineligible':max(0,expected-sub.height),'horizons':{}}
        for h in horizons:
            valid=sub.filter(pl.col('value').is_finite() & pl.col(f'forward_{h}').is_finite())
            counts=valid.group_by('datetime').agg(pl.len().alias('n'),
                pl.corr('value',f'forward_{h}',method='spearman').alias('rank_ic'))
            ic_dates=counts.filter((pl.col('n')>=3)&pl.col('rank_ic').is_finite())['datetime'].dt.date().n_unique()
            finite=sub.filter(pl.col('value').is_finite())
            mature=valid.height;pending=finite.filter(pl.col(f'forward_{h}').is_null()).height
            results[str(window)]['horizons'][str(h)]={'status':'computed' if ic_dates>=min_dates else 'insufficient_mature_dates',
                'valid_ic_sessions':ic_dates,'mature_observations':mature,'pending_observations':pending,
                'latest_mature_signal_at':valid['available_at'].max(),'metrics':stats[str(h)]}
    watermarks={}
    for symbol in config['data']['symbols']:
        b=known.filter(pl.col('symbol')==symbol);v=values.filter(pl.col('symbol')==symbol)
        s=labelled.filter(pl.col('symbol')==symbol)
        watermarks[symbol]={'data_at':b['available_at'].max(),'factor_at':v.filter(pl.col('value').is_finite())['available_at'].max(),
            'labels':{str(h):s.filter(pl.col('value').is_finite() & pl.col(f'forward_{h}').is_finite())['available_at'].max() for h in horizons}}
    return {'method':VERSION,'weighting':'Equal observed bar timestamps; sessions define window and minimum-date gates','as_of':as_of,'watermarks':watermarks,'windows':results,
        'input_bar_hash':digest(known.write_json()),'input_factor_hash':digest(values.write_json()),
        'bars':known.height,'factor_rows':values.height},known,values
