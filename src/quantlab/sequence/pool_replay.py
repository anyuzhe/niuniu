"""Render only liquidity-pool revisions already visible at the replay cursor."""
from datetime import datetime


def pool_replay_zones(events,visible):
    latest={};result=[];times=visible['datetime'].to_list()
    for event in sorted(events,key=lambda e:(e['available_at'],e.get('metadata',{}).get('event_index',0))):
        metadata=event.get('metadata',{})
        if metadata.get('profile')!='equal_extreme_pool_v1':continue
        pool=metadata.get('pool')
        if pool:latest[pool['id']]=(event,pool)
    for key,(event,pool) in latest.items():
        start=datetime.fromisoformat(pool['created_at'])
        terminal=pool['status'] in ('reclaimed','invalidated','expired')
        end=datetime.fromisoformat(event['available_at']) if terminal else times[-1]
        if end<times[0] or start>times[-1]:continue
        result.append({'zone_id':key,'symbol':event['symbol'],'timeframe':event['timeframe'],
            'available_at':event['available_at'],'lower_price':pool['lower_price'],
            'upper_price':pool['upper_price'],'kind':'equal_extreme_liquidity_pool','status':pool['status'],
            'touch_count':pool['touch_count'],'pivot_count':len(pool['anchors']),
            'start_visible_index':next((i for i,t in enumerate(times) if t>=start),0),
            'end_visible_index':max(i for i,t in enumerate(times) if t<=end)})
    return result
