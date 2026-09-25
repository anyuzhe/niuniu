"""Real-time 'is a 一买 forming' detector with the order book (2019-05..2020-06).
Context (minute grid, known at the minute end): the minute's low is the lowest of the last 30 minutes and the price is
>= 1.5% below the day's high so far. Book at the first snapshot after that minute: exhaustion = level-1 imbalance
>= thr and 30 s aggressor flow >= 0. Buy at ask1 (market). Exits: hold 60 min (sell at bid, taker) or closing auction.
Also reports how many signals fall within 5 minutes of a later-confirmed bi-level 一买 point bar."""
import sys, os, collections
sys.path.insert(0, os.environ['HOME']+'/research/ob')
from evalchan import *
from feat import load, features
b1pts=collections.defaultdict(list)
for p in pts:
    if p['level']=='' and p['type']=='1' and p['buy'] and p['point_date']==p['confirm_date']:
        b1pts[(p['symbol'],p['point_date'])].append(slot_of.get(p['point_minute'],-99))
Ln=np.where(np.isnan(z['L']),C,z['L'])
out=collections.defaultdict(list)
syms=sorted({str(s) for s in sym})
for s in syms:
    zb=load(s); F,Tg,mid,seg=features(zb); tsec=zb['t']; dts=zb['date']
    days=np.unique(dts)
    for d in days:
        k=row_of.get((s,d))
        if k is None or tick_bp[k]>12.5: continue
        idx=np.flatnonzero(dts==d); ts=tsec[idx]
        last_sig=-99
        for i in range(30,S-1):
            if slots[i]<'09:45' or slots[i]>'14:30': continue
            lo30=np.min(Ln[k,i-29:i+1])
            if Ln[k,i]>lo30+1e-9 or C[k,i]>HI[k,i]*(1-0.015) or i-last_sig<15: continue
            m=slots[i]; t0=int(m[:2])*3600+int(m[3:])*60
            j=np.searchsorted(ts,t0)
            if j>=len(idx): continue
            j=idx[j]
            imb=F['imb1'][j]; flow=F['flow10'][j]
            buy=zb['ask1_px'][j]
            if buy>=lim_up[k]-0.005: continue
            near=any(abs(i-b)<=5 for b in b1pts.get((s,d),[]))
            j60=min(i+60,S-1); o=O[k,j60+1] if j60+1<S else np.nan
            ex60=(C[k,j60] if np.isnan(o) else o)-tick if j60<S-1 else C[k,-1]
            for lab,ok in (('context only',True),('book imb>=0.3',imb>=0.3),('book imb>=0.5 & flow>=0',imb>=0.5 and flow>=0),
                           ('book imb<=-0.3 (sellers heavy)',imb<=-0.3)):
                if not ok: continue
                out[(lab,'close')].append(((C[k,-1]/buy-1)*1e4-fees[k],near))
                out[(lab,'hold60')].append(((ex60/buy-1)*1e4-fees[k],near))
            last_sig=i
    print(s,flush=True) if False else None
for key in sorted(out):
    a=np.array([x[0] for x in out[key]]); nr=np.mean([x[1] for x in out[key]])
    w=a[a>0]; l=a[a<=0]
    print(f'{key[0]:32s} exit={key[1]:6s} n={len(a):5d} per_trip={a.mean():+6.1f} win={len(w)/len(a):.2f} payoff={w.mean()/-l.mean():.2f}  落在真一买±5分钟内的比例={nr:.0%}')
