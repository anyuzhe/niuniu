"""Cross-round comparison helpers for immutable Decisions."""
from __future__ import annotations

from .decision import FRAMES

INTRADAY_FRAMES=('PREP','AUCTION','R1','R2','R3')


def compare_intraday(store,symbol,trading_day):
    records=store.list(symbol=symbol,trading_day=trading_day,include_superseded=False,limit=200)['records']
    by_frame={record['frame']:record for record in records if record['frame'] in INTRADAY_FRAMES}
    rows=[];previous=None
    for frame in INTRADAY_FRAMES:
        current=by_frame.get(frame)
        if current is None:
            rows.append({'frame':frame,'status':'missing','decision':None,'changes':{}});continue
        changes={}
        if previous is not None:
            for key in ('action','theme','theme_role','machine_state'):
                changes[key]={'from':previous.get(key,''),'to':current.get(key,''),'changed':previous.get(key,'')!=current.get(key,'')}
            changes['ai_thesis_changed']=previous.get('ai_thesis','')!=current.get('ai_thesis','')
        rows.append({'frame':frame,'status':'present','decision':current,'changes':changes})
        previous=current
    return {'symbol':symbol,'trading_day':trading_day,'rows':rows,
        'policy':'缺失 Frame 保持 missing；只比较当时保存的当前版本，不回填旧判断。'}


def followup_chain(store,reference_decision_id,limit=200):
    source=store.get(reference_decision_id)
    rows=[]
    for record in store.list(symbol=source['symbol'],include_superseded=False,limit=limit)['records']:
        if record.get('reference_decision_id')==reference_decision_id:
            rows.append(record)
    rows.sort(key=lambda r:(r['trading_day'],FRAMES.index(r['frame']),r['submitted_at']))
    return {'source':source,'followups':rows}
