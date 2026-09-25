"""Step 1: how much is early detection of a 1-minute 一买 worth? For every confirmed bi-level 一买 (and 一卖 mirror):
entry at the point bar (next minute open after the point bar: an upper bound, since the point is not known then)
versus entry after confirmation (next minute open after the confirmation bar). Exit: closing auction. Costs: 1 tick + fees."""
from evalchan import *
import collections
res=collections.defaultdict(list)
for p in pts:
    if p['level']!='' or p['type']!='1': continue
    if p['point_date']!=p['confirm_date']: continue
    k=row_of.get((p['symbol'],p['confirm_date']))
    if k is None or p['point_minute'] not in slot_of or p['confirm_minute'] not in slot_of: continue
    i0=slot_of[p['point_minute']]; i1=slot_of[p['confirm_minute']]
    if i1+1>=S or p['confirm_minute']>'14:30' or tick_bp[k]>12.5: continue
    side=1 if p['buy'] else -1
    def px(i):
        o=O[k,i+1]; return (C[k,i] if np.isnan(o) else o)+side*tick
    e0,e1=px(i0),px(i1)
    net0=side*(C[k,-1]/e0-1)*1e4-fees[k]; net1=side*(C[k,-1]/e1-1)*1e4-fees[k]
    missed=side*(e1/e0-1)*1e4
    part='train' if date[k]<='2022-12-31' else 'test'
    res[(side,part)].append((net0,net1,missed,i1-i0))
for (side,part),v in sorted(res.items()):
    a=np.array(v)
    print(f'{"一买" if side>0 else "一卖"} {part}: n={len(a)} 在点位K线后买 {a[:,0].mean():+.1f} bp | 确认后买 {a[:,1].mean():+.1f} bp | 等确认错过 {a[:,2].mean():+.1f} bp | 确认滞后中位 {np.median(a[:,3]):.0f} 分钟')
