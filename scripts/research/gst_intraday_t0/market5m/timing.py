"""Market-timing 底仓做T on the 500-stock universe: at 10:00 the market model (whole-market return vs prev close,
vs open, opening gap; walk-forward from 2020) predicts the rest-of-day average move. On days it predicts <= -thr bp,
sell first in every eligible stock (think: every stock you hold), buy back at the close. Also the 10:00 + 10:30 version."""
exec(open('wf500b.py').read().split("for Y in ('2021','2022','2023','2024'):\n    fm=ok&(yr<Y)&(yr>='2020'); ps=")[0])
out=[]
for Y in ('2021','2022','2023','2024'):
    fm=ok&(yr<Y)&(yr>='2020'); pm=fitg(Xm,ymean,fm)(Xm)
    for d in np.unique(dt[ok&(yr==Y)]):
        taken=None
        for T in ('1000','1030'):
            ix=np.flatnonzero(ok&(dt==d)&(tt==T))
            if not len(ix): continue
            out.append((d,T,pm[ix[0]],sell[ix].mean(),np.mean(sell[ix]>0),len(ix)))
import collections
for T in ('1000','either'):
    for thr in (5,10,15,20,30):
        rows=[]
        byday={}
        for d,t_,pmv,s,w,n in out:
            if T=='1000' and t_!='1000': continue
            if pmv<=-thr and d not in byday: byday[d]=(s,w)
        for part,cond in (('2021-22',lambda d:d<'2023'),('2023-24',lambda d:d>='2023')):
            v=np.array([byday[d][0] for d in byday if cond(d)]); wr=np.array([byday[d][1] for d in byday if cond(d)])
            if len(v)<3: print(f'{T:6s} thr{thr:2d} {part}: days={len(v)}'); continue
            t_=v.mean()/(v.std(ddof=1)/np.sqrt(len(v)))
            print(f'{T:6s} thr{thr:2d} {part}: days={len(v):3d} ({len(v)/2:.0f}/yr) avg per trip={v.mean():+6.1f} bp  day win={np.mean(v>0):.2f}  stock win={wr.mean():.2f}  t={t_:+.2f}')
