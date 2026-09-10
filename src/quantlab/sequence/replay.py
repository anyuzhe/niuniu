"""Frozen replay evidence; query-time views are truncated by information availability."""
from dataclasses import asdict
from datetime import datetime
import polars as pl
from quantlab.structure.pivots import ConfirmedPivotEngine
from quantlab.structure.breaks import ConfirmedSwingBreakEngine
from quantlab.zones.fvg import FVGZoneEngine


def replay_evidence(bars, parameters=None):
    parameters=parameters or {}
    params={k:parameters.get(k,2) for k in ('left','right')}
    zones=FVGZoneEngine().analyze(bars)
    zone_symbols={z.zone_id:z.symbol for z in zones.zones}
    _,events=ConfirmedSwingBreakEngine(**params).analyze(bars)
    return {'version':'1.0.0','overlay_rules':{'confirmed_pivots':params,'swing_break':params,'fvg':'three_bar_1.0.0'},
        'scope':'diagnostic overlays, not necessarily the experiment factor or a trading signal',
        'structures':[asdict(v) for v in ConfirmedPivotEngine(**params).detect(bars)],
        'events':[asdict(v) for v in events], 'zones':[asdict(v) for v in zones.zones],
        'zone_updates':[{**asdict(v),'symbol':zone_symbols[v.zone_id]} for v in zones.updates]}


def replay_page(bars, record, symbol, at=0, limit=100):
    symbols=sorted(bars['symbol'].unique().to_list())
    if not symbol:
        symbol=symbols[0] if symbols else ''
    frame=bars.filter(pl.col('symbol')==symbol).sort('datetime')
    if frame.is_empty() or not 0 <= at < frame.height:
        raise ValueError('Replay symbol or cursor outside saved bars')
    cutoff=frame['available_at'][at]
    visible=frame.head(at+1).filter(pl.col('available_at')<=cutoff).tail(limit)
    evidence=record.get('replay',{})
    def known(items,time_key='available_at'):
        return [v for v in items if v['symbol']==symbol and datetime.fromisoformat(v[time_key])<=cutoff]
    zones=known(evidence.get('zones',[]))
    updates=known(evidence.get('zone_updates',[]))
    events=known(evidence.get('events',[]))
    for sequence in record.get('sequence_audit',{}).get('sequences',[]):
        events.extend(known(sequence.get('events',[])))
    events=list({e['event_id']:e for e in events}.values())
    structures=known(evidence.get('structures',[]))
    # Each nesting definition maintains its own last visible chain. The node
    # clocks belong to actual periods; map them to the displayed candle grid.
    nests={}
    for event in sorted(events,key=lambda e:(e['available_at'],e['event_id'])):
        obj=event.get('metadata',{})
        if obj.get('rule')=='actual_timeframe_confirmed_segment_containment_v1':
            nests[(event['factor_id'],tuple(obj['levels']),obj['same_direction'])]=event
    if nests:
        from bisect import bisect_left
        clocks=frame['datetime'].to_list();offset=at+1-visible.height
        for event in nests.values():
            for node in event['metadata']['segments']:
                if datetime.fromisoformat(node['available_at'])>cutoff:continue
                start=datetime.fromisoformat(node['start_at']);end=datetime.fromisoformat(node['end_at'])
                structures.append({**node,'structure_id':event['metadata']['chain_id']+':'+node['timeframe'],
                    'kind':'chan_multiscale_segment','symbol':symbol,'occurred_at':node['end_at'],
                    'start_visible_index':bisect_left(clocks,start)-offset,'end_visible_index':bisect_left(clocks,end)-offset})
    if evidence.get('version')=='classic_snapshots_v1':
        snapshots={}
        for event in sorted(events,key=lambda e:(e['available_at'],e['event_id'])):
            obj=event.get('metadata',{});key=obj.get('object_key')
            if not key:continue
            if obj['status']=='removed':snapshots.pop(key,None)
            else:snapshots[key]=(event,obj)
        for key,(event,obj) in snapshots.items():
            base={'structure_id':key,'kind':obj['kind'],'symbol':symbol,'timeframe':event['timeframe'],
                'occurred_at':event['occurred_at'],'available_at':event['available_at'],**obj}
            if obj['kind'] in ('center','higher_center'):
                zones.append({'zone_id':key,'symbol':symbol,'available_at':event['available_at'],
                    'lower_price':obj['lower'],'upper_price':obj['upper'],
                    'start_visible_index':obj['start_index']-(at+1-visible.height),
                    'end_visible_index':obj['end_index']-(at+1-visible.height)})
            else:
                if 'start_index' in obj:
                    base.update(start_at=frame[obj['start_index'],'datetime'].isoformat(),end_at=frame[obj['end_index'],'datetime'].isoformat())
                    base.update(start_visible_index=obj['start_index']-(at+1-visible.height),end_visible_index=obj['end_index']-(at+1-visible.height))
                structures.append(base)
    if evidence.get('version')=='wyckoff_ae_v1':
        latest={}
        for event in sorted(events,key=lambda e:e['available_at']):
            ep=event.get('metadata',{}).get('episode')
            if ep:latest[ep['id']]=(event,ep)
        for key,(event,ep) in latest.items():
            lo,hi=sorted((ep['d']*ep['lo'],ep['d']*ep['hi']))
            structures.append({'structure_id':key,'kind':'wyckoff_'+ep['phase'],'symbol':symbol,'timeframe':event['timeframe'],
                'occurred_at':ep['at'],'available_at':event['available_at'],'price':(lo+hi)/2,'lower':lo,'upper':hi,'direction':ep['d']})
            start=datetime.fromisoformat(ep['at']);visible_times=visible['datetime'].to_list()
            terminal=event['factor_id'].rsplit('_',1)[-1] in ('EXIT','INVALIDATED','EXPIRED') or event['factor_id'].endswith('TARGET_HIT')
            end=datetime.fromisoformat(event['occurred_at']) if terminal else visible_times[-1]
            if end<visible_times[0]:continue
            zones.append({'zone_id':key,'symbol':symbol,'available_at':event['available_at'],'lower_price':lo,'upper_price':hi,
                'start_visible_index':next((j for j,t in enumerate(visible_times) if t>=start),0),
                'end_visible_index':max(j for j,t in enumerate(visible_times) if t<=end)})
    state={}
    for update in updates:
        state[update['zone_id']]=update
    # Only known fills, never future trades or full-sample research labels.
    fills=[v for v in record.get('fills',[]) if v['symbol']==symbol and datetime.fromisoformat(v['filled_at'])<=cutoff]
    return {'symbols':symbols,'symbol':symbol,'at':at,'total_bars':frame.height,'as_of':cutoff,
        'bars':visible.to_dicts(),'events':events,'structures':structures,
        'zones':zones,'zone_states':state,'fills':fills,'overlay_rules':evidence.get('overlay_rules',{})}
