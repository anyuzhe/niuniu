"""Observed-data quality audit; calendar gaps are not inferred suspensions."""
from datetime import date,timedelta
from pathlib import Path
import polars as pl
from quantlab.data.query import query_bars
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest


def audit_market(root,request,snapshot_manifest=None,calendar_file=None):
    calendar_path=Path(calendar_file) if calendar_file else Path(root)/'lake/bronze/provider=baostock/trade_calendar/calendar.parquet'
    calendar=pl.read_parquet(calendar_path)
    calendar=calendar.with_columns(pl.col('calendar_date').cast(pl.String).str.to_date(),pl.col('is_trading_day').cast(pl.String))
    if calendar['calendar_date'].null_count() or calendar['calendar_date'].n_unique()!=calendar.height or calendar.filter(~pl.col('is_trading_day').is_in(['0','1']) | pl.col('is_trading_day').is_null()).height:
        raise ValueError('Calendar requires unique dates and explicit trading-day flags')
    sessions=set(calendar.filter(pl.col('is_trading_day')=='1')['calendar_date'].to_list())
    calendar_dates=set(calendar['calendar_date'])
    unknown_dates=[request.start+timedelta(days=i) for i in range((request.end-request.start).days+1) if request.start+timedelta(days=i) not in calendar_dates]
    expected=sorted(d for d in sessions if request.start<=d<=request.end)
    if snapshot_manifest is None:frame,files=query_bars(root,request)
    else:
        from quantlab.data.archive import ArchivedBarProvider
        provider=ArchivedBarProvider(snapshot_manifest)
        if request.timeframe.value!=provider.manifest['timeframe'] or not set(request.symbols)<=set(provider.manifest['symbols']):
            raise ValueError('Request outside archived symbols/timeframe')
        normalized=provider.all_bars().with_columns(pl.col('datetime').dt.convert_time_zone('Asia/Shanghai'))
        frame=normalized.filter(pl.col('symbol').is_in(request.symbols)&pl.col('datetime').dt.date().is_between(request.start,request.end)).select(
            pl.col('symbol').alias('code'),pl.col('datetime').dt.date().alias('date'),pl.col('datetime').dt.strftime('%Y%m%d%H%M%S%3f').alias('time'),
            'open','high','low','close','volume',pl.col('turnover').alias('amount'))
        files=[{'path':str(provider.path),'version_id':provider.manifest['version_id'],'sha256':provider.manifest['sha256'],
            'observed_at':provider.manifest['observed_at'],'symbol':s,'null_date_rows_in_source':0} for s in sorted(request.symbols)]
    file_metadata=dict(zip(sorted(request.symbols),files))
    results=[]
    for symbol in request.symbols:
        f=frame.filter(pl.col('code')==symbol)
        if f.is_empty():
            results.append({'symbol':symbol,'status':'no_data','rows':0,'session_coverage':[{'date':d,'status':'missing','observed_slots':0,'expected_slots':48 if request.timeframe==Timeframe.MIN5 else 1} for d in expected]});continue
        keys=['code','date']+(['time'] if request.timeframe==Timeframe.MIN5 else [])
        invalid=f.filter(pl.any_horizontal(~pl.col(c).cast(pl.Float64,strict=False).is_finite().fill_null(False) for c in ('open','high','low','close','volume','amount')) |
            (pl.min_horizontal('open','high','low','close')<=0) | (pl.col('high')<pl.max_horizontal('open','close','low')) |
            (pl.col('low')>pl.min_horizontal('open','close','high')) | (pl.col('volume')<0) | (pl.col('amount')<0))
        observed=set(f['date'].to_list());start=max(request.start,min(observed));end=min(request.end,max(observed))
        missing=sorted(d for d in sessions if start<=d<=end and d not in observed)
        row={'null_date_rows_in_source':file_metadata[symbol]['null_date_rows_in_source'],'symbol':symbol,'rows':f.height,'first':min(observed),'last':max(observed),
            'duplicate_rows':f.select(pl.struct(keys).is_duplicated().sum()).item(),'invalid_ohlcv_rows':invalid.height,
            'unexplained_calendar_gaps':missing,'nontrading_dates':sorted((observed&calendar_dates)-sessions),'unknown_calendar_dates':sorted(observed-calendar_dates),
            'outside_observed_coverage':sorted(d for d in sessions if request.start<=d<=request.end and (d<min(observed) or d>max(observed))),
            'zero_volume_rows':f.filter(pl.col('volume')==0).height,'null_counts':dict(zip(f.columns,f.null_count().row(0)))}
        if request.timeframe==Timeframe.MIN5:
            times=f['time'].str.strptime(pl.Datetime,'%Y%m%d%H%M%S%3f',strict=False)
            valid_minutes=set(range(9*60+35,11*60+31,5))|set(range(13*60+5,15*60+1,5))
            row['invalid_timestamps']=sum(t is None or t.date()!=day or t.hour*60+t.minute not in valid_minutes or t.second!=0 or t.microsecond!=0 for t,day in zip(times,f['date']))
            row['incomplete_sessions']=[{'date':r['date'],'observed_slots':r['slots']} for r in f.group_by('date').agg(pl.col('time').n_unique().alias('slots')).sort('date').to_dicts() if r['slots']!=48]
            slots={}
            for t,day in zip(times,f['date']):
                if t is not None and t.date()==day and t.hour*60+t.minute in valid_minutes and t.second==0 and t.microsecond==0:
                    slots.setdefault(day,set()).add(t.hour*60+t.minute)
            row['session_coverage']=[{'date':d,'status':'complete' if len(slots.get(d,set()))==48 else 'incomplete' if d in observed else 'missing',
                'observed_slots':len(slots.get(d,set())),'expected_slots':48,
                'missing_slots':[f'{m//60:02d}:{m%60:02d}' for m in sorted(valid_minutes-slots.get(d,set()))]} for d in expected]
        else:
            row['session_coverage']=[{'date':d,'status':'complete' if d in observed else 'missing','observed_slots':int(d in observed),'expected_slots':1} for d in expected]
        row['status']='issues' if row['null_date_rows_in_source'] or row['duplicate_rows'] or row['invalid_ohlcv_rows'] or missing or row['nontrading_dates'] or unknown_dates or row['outside_observed_coverage'] or row.get('invalid_timestamps') or row.get('incomplete_sessions') else 'checked'
        results.append(row)
    return {'request':request,'files':files,'calendar_path':str(calendar_path.resolve()),'calendar_sha256':digest(calendar.write_json()),'results':results,
        'status':'checked' if expected and not unknown_dates and all(r['status']=='checked' for r in results) else 'issues',
        'calendar_missing_dates':unknown_dates,'expected_symbol_sessions':len(expected)*len(request.symbols),
        'complete_symbol_sessions':sum(s['status']=='complete' for r in results for s in r['session_coverage']),
        'limitations':'Only requested symbols/window inspected. Missing dates and incomplete sessions may reflect suspension, listing, source loss or partial coverage; not inferred as tradable or suspended. No PIT eligibility or price-limit certification.'}
