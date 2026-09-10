"""Explicit conservative stroke progression, speed divergence and point proxies.

Not a complete implementation of Chan feature-sequence/gap conventions.
Only confirmed strokes enter this module; all publications are append-only.
"""
from quantlab.storage.codec import digest


def endpoint(stroke):return stroke['upper'] if stroke['direction']==1 else stroke['lower']
def startpoint(stroke):return stroke['lower'] if stroke['direction']==1 else stroke['upper']


def progression_events(strokes,centers,positions,divergence_ratio=.8,max_follow_strokes=12):
    pending={};previous_segments={};setups={};records=[]
    center_by_stroke={}
    for center in centers:
        if center['kind'] in ('chan_center_exit_up','chan_center_exit_down'):
            center_by_stroke[center['components'][-1]]=center
    def emit(kind,stroke,metadata,direction):
        record={'kind':kind,'symbol':stroke['symbol'],'timeframe':stroke['timeframe'],'occurred_at':stroke['end_at'],
            'available_at':stroke['available_at'],'direction':direction,'version':'confirmed_progression_v1',**metadata}
        record['structure_id']=digest(record);records.append(record);return record
    for stroke in sorted(strokes,key=lambda s:(s['available_at'],s['symbol'])):
        symbol=stroke['symbol']
        # Existing point setups only consume subsequent strokes, never the creator.
        for key,state in list(setups.items()):
            if key[0]!=symbol:continue
            state['age']+=1;d=state['direction']
            invalid=stroke['lower']<=state['floor'] if d==1 else stroke['upper']>=state['floor']
            if state['age']>max_follow_strokes or invalid:
                emit('setup_expired' if state['age']>max_follow_strokes else 'setup_invalidated',stroke,
                    {'setup':dict(state),'cause_stroke':stroke['structure_id']},d);del setups[key];continue
            if state['pullback'] is None and stroke['direction']==-d:
                state['pullback']=stroke;continue
            if state['pullback'] is not None and stroke['direction']==d:
                threshold=startpoint(state['pullback'])
                broken=d*(endpoint(stroke)-threshold)>0
                emit(state['point'] if broken else 'setup_invalidated',stroke,
                    {'setup':dict(state),'confirmation_stroke':stroke['structure_id'],'break_threshold':threshold,
                     'reason':'pullback_break' if broken else 'first_confirmation_failed'},d)
                del setups[key]
        history=pending.setdefault(symbol,[]);history.append(stroke)
        d=history[0]['direction']
        best=max((i for i,s in enumerate(history) if s['direction']==d),key=lambda i:d*endpoint(history[i]))
        if best>=2 and best<len(history)-1 and stroke['direction']==-d:
            counter=next(s for s in reversed(history[:best]) if s['direction']==-d)
            if d*(endpoint(stroke)-endpoint(counter))<0:
                origin=history[0];finish=history[best]
                duration=positions[(symbol,finish['end_at'])]-positions[(symbol,origin['occurred_at'])]
                if duration<1:raise ValueError('Segment endpoints must span observed bars')
                start=startpoint(origin);end=endpoint(finish)
                segment=emit('segment_up' if d==1 else 'segment_down',stroke,
                    {'start_at':origin['occurred_at'],'end_at':finish['end_at'],'start_price':start,'end_price':end,
                     'lower':min(start,end),'upper':max(start,end),'observed_bar_span':duration,
                     'price_speed':abs(end-start)/start/duration,'components':[s['structure_id'] for s in history[:best+1]],
                     'strokes':list(history[:best+1]),'confirmation_stroke':stroke['structure_id'],
                     'confirmation':stroke,'counter_break_price':endpoint(counter)},d)
                prior=previous_segments.get((symbol,d))
                if prior and d*(end-prior['end_price'])>0 and segment['price_speed']<prior['price_speed']*divergence_ratio:
                    divergence=emit('divergence_up' if d==1 else 'divergence_down',stroke,
                        {'segment':segment,'previous_segment':prior,'ratio':divergence_ratio},-d)
                    point=emit('sell1' if d==1 else 'buy1',stroke,{'divergence':divergence['structure_id'],
                        'segment_id':segment['structure_id'],'extreme':end,'confirmation_stroke':stroke['structure_id']},-d)
                    setup_key=(symbol,2,-d)
                    if setup_key in setups:emit('setup_superseded',stroke,{'setup':dict(setups[setup_key])},-d)
                    setups[setup_key]={'point':'sell2' if d==1 else 'buy2','direction':-d,'floor':end,
                        'source_id':point['structure_id'],'age':0,'pullback':None}
                previous_segments[(symbol,d)]=segment
                pending[symbol]=history[best+1:]
        center=center_by_stroke.get(stroke['structure_id'])
        if center:
            d=1 if center['kind']=='chan_center_exit_up' else -1
            for key in [k for k in setups if k[0]==symbol and k[1]==3]:
                emit('setup_superseded',stroke,{'setup':dict(setups.pop(key))},key[2])
            setups[(symbol,3,d)]={'point':'buy3' if d==1 else 'sell3','direction':d,
                'floor':center['upper'] if d==1 else center['lower'],'source_id':center['structure_id'],
                'center_exit':center,'exit_stroke':stroke,'age':0,'pullback':None}
    return records
