"""Evaluate 1-minute Chan buy/sell points as 底仓做T entries on the minute grid.
Buy point -> buy first at the next minute's open + 1 tick; sell point -> sell first at next open - 1 tick.
Exit: 'close' = closing auction; 'opp' = first opposite confirmed point later that day (taker, next open ∓ 1 tick),
else the closing auction; 'stop' = like 'opp' but also exit when a close breaks the point's price (the bi extreme)."""
import sys, os, json, glob, numpy as np
sys.path.insert(0, os.environ['HOME']+'/research')
from lib import *
fees=5+stamp+0.2
S=len(slots); slot_of={s:i for i,s in enumerate(slots)}
row_of={(str(a),str(b)):k for k,(a,b) in enumerate(zip(sym,date))}
ud,inv=np.unique(date,return_inverse=True)
def dm(x):
    s=np.bincount(inv,np.nan_to_num(x)*np.isfinite(x));n=np.bincount(inv,np.isfinite(x)); return (s/np.maximum(n,1))[inv]
mkt=np.column_stack([dm(C[:,i]/pc-1) for i in (T('10:00'),)])  # placeholder
MKT={}
def mkt_at(i):
    if i not in MKT: MKT[i]=dm(C[:,i]/pc-1)
    return MKT[i]
pts=[]
for f in glob.glob(os.environ['HOME']+'/research/chan/out/*.json'):
    s=os.path.basename(f).split('_')[0]
    for p in json.load(open(f)):
        if p['confirm_date']!=p['point_date'] and p['level']=='': pass
        p['symbol']=s; pts.append(p)
def evaluate(filter_fn=None, exit_rule='close', last_entry='14:30'):
    by_day={}
    for p in pts:
        k=row_of.get((p['symbol'],p['confirm_date']))
        if k is None or p['confirm_minute'] not in slot_of: continue
        by_day.setdefault(k,[]).append(p)
    res=[]
    for k,lst in by_day.items():
        lst.sort(key=lambda p:p['confirm_minute'])
        busy_until=-1
        for n,p in enumerate(lst):
            i=slot_of[p['confirm_minute']]
            if i<=busy_until or p['confirm_minute']>last_entry or i+1>=S: continue
            side=1 if p['buy'] else -1
            if filter_fn and not filter_fn(p,k,i,side): continue
            o=O[k,i+1]; o=C[k,i] if np.isnan(o) else o
            entry=o+side*tick
            if (side>0 and entry>=lim_up[k]-0.005) or (side<0 and entry<=lim_dn[k]+0.005): continue
            exitp=C[k,-1]; j_exit=S-1; why='close'
            if exit_rule in ('opp','stop'):
                for q in lst[n+1:]:
                    j=slot_of[q['confirm_minute']]
                    if j<=i: continue
                    if q['buy']!=p['buy']:
                        if j+1<S:
                            o2=O[k,j+1]; o2=C[k,j] if np.isnan(o2) else o2; exitp=o2-side*tick; j_exit=j+1; why='opp'
                        break
                if exit_rule=='stop':
                    for j in range(i+1,j_exit):
                        if (side>0 and C[k,j]<p['price']) or (side<0 and C[k,j]>p['price']):
                            o2=O[k,j+1] if j+1<S and np.isfinite(O[k,j+1]) else C[k,j]; exitp=o2-side*tick; j_exit=j+1; why='stop'; break
            busy_until=j_exit
            net=side*(exitp/entry-1)*1e4-fees[k]
            res.append((k,p['type'],side,p['level'],net,why,i))
    return res
def report(tag,res,years=None):
    import collections
    for part,cond in (('train',lambda d:d<='2022-12-31'),('test',lambda d:d>'2022-12-31')):
        r=[x for x in res if cond(date[x[0]])]
        if not r: print(tag,part,'none'); continue
        b=np.array([x[4] for x in r]); ks=np.array([x[0] for x in r])
        by=collections.defaultdict(list)
        for x in r: by[date[x[0]]].append(x[4])
        m=b.mean(); se=np.sqrt(sum((np.sum(np.array(v)-m))**2 for v in by.values()))/len(b)
        w=b[b>0]; l=b[b<=0]
        ys=' '.join(f"{y[2:]}:{np.mean([x[4] for x in r if year[x[0]]==y]):+.0f}({sum(1 for x in r if year[x[0]]==y)})" for y in sorted({year[x[0]] for x in r}))
        print(f'{tag:40s} {part:5s} n={len(b):5d} trip={m:+6.1f} t={m/se:+.1f} win={len(w)/len(b):.2f} payoff={w.mean()/-l.mean():.2f}  {ys}',flush=True)
