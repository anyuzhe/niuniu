"""Chan 1-minute points confirmed by the order book at the moment of entry (2019-05..2020-06 only).
Entry: the first snapshot after the confirmation minute ends, at the opposite best (market order);
confirmation: level-1 imbalance and 30 s aggressor flow in the trade direction. Exit: closing auction."""
import sys, os
sys.path.insert(0, os.environ['HOME']+'/research/ob')
from evalchan import *
from feat import load, features
import numpy as np, collections
books={}
rows=[]
for p in pts:
    if p['level']!='' or p['type'] not in ('1','2','3a','3b') or p['confirm_date']>'2020-06-22' or p['confirm_minute']>'14:30': continue
    k=row_of.get((p['symbol'],p['confirm_date']))
    if k is None: continue
    rows.append((p['symbol'],p,k))
rows.sort(key=lambda r:r[0])
out=[]
cur=None
for s,p,k in rows:
    if s!=cur:
        z=load(s); F,Tg,mid,seg=features(z); cur=s
        tsec=z['t']; dts=z['date']
    idx=np.flatnonzero(dts==p['confirm_date'])
    if not len(idx): continue
    t0=int(p['confirm_minute'][:2])*3600+int(p['confirm_minute'][3:])*60
    j=np.searchsorted(tsec[idx],t0)
    if j>=len(idx): continue
    j=idx[j]
    side=1 if p['buy'] else -1
    px=z['ask1_px'][j] if side>0 else z['bid1_px'][j]
    net=side*(C[k,-1]/px-1)*1e4-fees[k]
    out.append((p['type'],side,F['imb1'][j],F['flow10'][j],net,tick_bp[k]<=12.5,date[k]))
a=np.array([(o[1],o[2],o[3],o[4],o[5]) for o in out],dtype=float)
print('points with a book',len(a))
for lab,m in (('all',np.ones(len(a),bool)),('px>=8',a[:,4]==1)):
    for cond,cm in (('no book filter',np.ones(len(a),bool)),('imb same side >0.3',a[:,0]*a[:,1]>0.3),
                    ('flow same side >0.3',a[:,0]*a[:,2]>0.3),('both',(a[:,0]*a[:,1]>0.3)&(a[:,0]*a[:,2]>0.3)),
                    ('book against (imb<-0.3)',a[:,0]*a[:,1]<-0.3)):
        for sd,sm in (('buy',a[:,0]>0),('sell',a[:,0]<0)):
            mm=m&cm&sm
            if mm.sum()<10: continue
            b=a[mm,3]; print(f'{lab:6s} {cond:24s} {sd}: n={mm.sum():4d} net={b.mean():+6.1f} bp  win={np.mean(b>0):.2f}')
