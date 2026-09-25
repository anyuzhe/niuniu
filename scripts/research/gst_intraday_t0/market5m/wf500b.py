"""Separate market timing from stock selection on the 500-stock universe (walk-forward from 2020).
Stock model: stock-only features, target = return minus the same-day/time cross-sectional mean (relative move).
Market model: market-only features (whole-market return vs prev close, vs open, gap) on the day-level mean target.
Strategies: (a) every day sell-first the k stocks with the lowest relative score (absolute P&L);
(b) only on days the market model predicts <= -m bp, sell-first the k lowest stocks."""
exec(open('wf500.py').read().split("key=np.char.add")[0])
import numpy as np
dk=np.char.add(dt,tt)
u,inv=np.unique(dk,return_inverse=True)
def cs_mean(v,m):
    s=np.bincount(inv[m],v[m],minlength=len(u)); n=np.bincount(inv[m],minlength=len(u)); return (s/np.maximum(n,1))[inv]
ymean=cs_mean(y,ok); yrel=y-ymean
Xs=X[:,:5]; Xs=np.column_stack([Xs,X[:,7]])      # ret_pc, ret_open, ret_30, vwap_dev, range_pos, gap
Xm=X[:,[5,6,8]]
def fitg(A,t,m,lam=0.01):
    mu=A[m].mean(0);sd=A[m].std(0);sd=np.where(sd>0,sd,1);Z=(A[m]-mu)/sd
    w=np.linalg.solve(Z.T@Z+lam*len(Z)*np.eye(Z.shape[1]),Z.T@(t[m]-t[m].mean())); return lambda B:((B-mu)/sd)@w+t[m].mean()
for Y in ('2021','2022','2023','2024'):
    fm=ok&(yr<Y)&(yr>='2020'); ps=fitg(Xs,yrel,fm)(Xs); pm=fitg(Xm,ymean,fm)(Xm)
    tm=ok&(yr==Y)
    print(Y,'stock-model corr with relative move',round(np.corrcoef(ps[tm],yrel[tm])[0,1],3),'| market-model corr with day mean',round(np.corrcoef(pm[tm],ymean[tm])[0,1],3))
res={}
for Y in ('2021','2022','2023','2024'):
    fm=ok&(yr<Y)&(yr>='2020'); ps=fitg(Xs,yrel,fm)(Xs); pm=fitg(Xm,ymean,fm)(Xm)
    for T in ('1000',):
        m=ok&(yr==Y)&(tt==T)
        for d in np.unique(dt[m]):
            ix=np.flatnonzero(m&(dt==d))
            order=ix[np.argsort(ps[ix])]
            mk=pm[ix[0]]
            for k in (10,50):
                bot=order[:k]
                res.setdefault(('all days',k),[]).append((d,sell[bot].mean(),yrel[bot].mean()))
                for mth in (10,20):
                    if mk<=-mth: res.setdefault((f'mkt<=-{mth}',k),[]).append((d,sell[bot].mean(),yrel[bot].mean()))
            res.setdefault(('mkt-only all stocks',0),[]).append((d,sell[ix].mean() if mk<=-20 else np.nan,0))
for key,v in res.items():
    a=np.array([(x[1],x[2]) for x in v if np.isfinite(x[1])]); ds=[x[0] for x in v if np.isfinite(x[1])]
    if not len(a): continue
    for part,cond in (('21-22',lambda d:d<'2023'),('23-24',lambda d:d>='2023')):
        mm=np.array([cond(d) for d in ds])
        if mm.sum()<5: continue
        b=a[mm,0]; t_=b.mean()/(b.std(ddof=1)/np.sqrt(len(b)))
        print(f'{key[0]:22s} k={key[1]:3d} {part}: days={mm.sum():4d} per_trip(day avg)={b.mean():+6.1f} bp t={t_:+.2f}  relative part={a[mm,1].mean():+.1f} bp')
