"""Execution study on real order books (2019-05..2020-06) for the sell-first entries our minute-bar strategies produced.
For each entry (decision at the end of a minute, engine price = next minute's first trade minus 1 tick):
  market : sell at bid1 of the first snapshot after the decision time (what a market order would get)
  passive: rest an ask at ask1 at the decision time (back of the queue, conservative queue model);
           if not filled within W seconds, sell at bid1 then.
All prices in bp versus the engine's assumed price (positive = better for us)."""
import json, numpy as np, os, sys
from feat import load, TICK
H=os.environ['HOME']
trips=[]
for k in ('intraday_score','close_score','weak_close'):
    r=json.load(open(f'{H}/res2_{k}_None.json'))
    trips+=[(t['symbol'],t['date'],t['entry_minute'],t['entry_price'],k) for t in r['trips'] if t['direction']=='先卖后买' and t['date']<='2020-06-22']
trips=sorted(set(trips))
print('sell-first entries in the quote window',len(trips))
W=[60,180,300]
res={w:[] for w in W}; mkt=[]; fills={w:0 for w in W}
cache={}
for sym,day,em,eng_px,k in trips:
    if sym not in cache: cache.clear(); cache[sym]=load(sym)
    z=cache[sym]
    idx=np.flatnonzero(z['date']==day)
    if not len(idx): continue
    t0=int(em[:2])*3600+int(em[3:])*60-60
    j=idx[np.searchsorted(z['t'][idx],t0)] if np.searchsorted(z['t'][idx],t0)<len(idx) else None
    if j is None: continue
    b1,a1,av,last,cum,t=z['bid1_px'],z['ask1_px'],z['ask1_vol'],z['last'],z['cum_volume'],z['t']
    mkt.append((b1[j]/eng_px-1)*1e4)
    qty=max(100,int(50000/((a1[j]+b1[j])/2)/100)*100)
    for w in W:
        px=a1[j]; queue=av[j]; done=0.0; got=None
        m=j+1
        while m<=idx[-1] and t[m]-t[j]<=w:
            dv=max(0.0,cum[m]-cum[m-1])
            if a1[m]>px+1e-6 or (last[m]>px+1e-6 and dv>0): got=px; break
            if abs(last[m]-px)<1e-6: done+=dv
            if done>=queue+qty: got=px; break
            m+=1
        if got is None:
            m=min(m,idx[-1]); got=b1[m]
        else: fills[w]+=1
        res[w].append((got/eng_px-1)*1e4)
n=len(mkt)
print(f'n={n}  market order at the real bid vs engine assumption: mean {np.mean(mkt):+.1f} bp (median {np.median(mkt):+.1f})')
for w in W:
    print(f'passive ask, cross after {w}s: fill rate {fills[w]/n:.0%}, mean {np.mean(res[w]):+.1f} bp vs engine, improvement over market order {np.mean(res[w])-np.mean(mkt):+.1f} bp')
