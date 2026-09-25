"""Upper bound with perfect early detection (entry right after the 一买 point bar): exits after 10/30/60 minutes (taker,
next open - 1 tick), at the first later opposite confirmed point, or with a take-profit of +X bp (limit, filled when a
later minute's high trades through by 1 tick), else the closing auction."""
from evalchan import *
import collections
by_day=collections.defaultdict(list)
for p in pts:
    if p['level']=='' : by_day[(p['symbol'],p['confirm_date'])].append(p)
res=collections.defaultdict(list)
for p in pts:
    if p['level']!='' or p['type']!='1' or p['point_date']!=p['confirm_date']: continue
    k=row_of.get((p['symbol'],p['confirm_date']))
    if k is None or p['point_minute'] not in slot_of or p['confirm_minute'] not in slot_of: continue
    i0=slot_of[p['point_minute']]
    if i0+1>=S or p['point_minute']>'14:30' or tick_bp[k]>12.5: continue
    side=1 if p['buy'] else -1
    o=O[k,i0+1]; entry=(C[k,i0] if np.isnan(o) else o)+side*tick
    part='train' if date[k]<='2022-12-31' else 'test'
    def taker(j):
        j=min(j,S-1)
        if j>=S-1: return C[k,-1]
        o2=O[k,j+1]; return (C[k,j] if np.isnan(o2) else o2)-side*tick
    for h in (10,30,60):
        res[(side,part,f'hold{h}m')].append(side*(taker(i0+1+h)/entry-1)*1e4-fees[k])
    ex=C[k,-1]
    for q in sorted(by_day[(p['symbol'],p['confirm_date'])],key=lambda q:q['confirm_minute']):
        if q['buy']!=p['buy'] and q['confirm_minute']>p['point_minute'] and q['confirm_minute'] in slot_of:
            ex=taker(slot_of[q['confirm_minute']]); break
    res[(side,part,'opposite point')].append(side*(ex/entry-1)*1e4-fees[k])
    Hn=z['H'][k]; Ln=z['L'][k]
    for tp in (30,60,100):
        target=round(entry*(1+side*tp/1e4),2); ex=C[k,-1]
        for j in range(i0+2,S-1):
            if (side>0 and Hn[j]>=target+tick-1e-9) or (side<0 and Ln[j]<=target-tick+1e-9): ex=target; break
        res[(side,part,f'take+{tp}bp')].append(side*(ex/entry-1)*1e4-fees[k])
for key in sorted(res):
    a=np.array(res[key]); w=a[a>0]; l=a[a<=0]
    print(f'{"一买" if key[0]>0 else "一卖"} {key[1]:5s} {key[2]:15s} n={len(a)} per_trip={a.mean():+.1f} win={len(w)/len(a):.2f} payoff={w.mean()/-l.mean():.2f}')
