from wf import *
times=['10:00','10:30']
def with_exit(periods,years,stop=None,take=None,label=''):
    n=len(sym); taken=np.zeros(n,bool); net=np.full(n,np.nan)
    cache={}
    for t in times:
        i=T(t); X,_=feats(i); p=C[:,i]; o=np.where(np.isnan(O[:,i+1]),p,O[:,i+1]); y=(C[:,-1]/o-1)*1e4
        ok=np.isfinite(X).all(1)&np.isfinite(y)&px8&(p>lim_dn+0.011)&(p<lim_up-0.011); cache[t]=(X,y,ok,o,i)
    for fitmask,trade in periods:
        for t in times:
            X,y,ok,o,i=cache[t]; mo=fit(X,y,ok&fitmask); pr=pred(mo,X)
            s=np.flatnonzero(ok&trade&~taken&(pr<=-20))
            for k in s:
                entry=o[k]-tick; exitp=C[k,-1]
                for j in range(i+2,len(slots)-1):
                    c=C[k,j]
                    if stop and c>=entry*(1+stop): exitp=(O[k,j+1] if np.isfinite(O[k,j+1]) else c)+tick; break
                    if take and c<=entry*(1-take): exitp=(O[k,j+1] if np.isfinite(O[k,j+1]) else c)+tick; break
                extra=0 if exitp==C[k,-1] else 0  # taker exit already has +1 tick
                net[k]=(entry/exitp-1)*1e4-fees[k]
            taken[s]=True
    mean,tt,nn=clustered(net,taken)
    ys=' '.join(f"{y[2:]}:{np.nanmean(net[taken&(year==y)]):+.0f}({(taken&(year==y)).sum()})" for y in years)
    print(f'{label:28s} n={nn} trip={mean:+.1f} t={tt:+.1f} {ys}',flush=True)
WF=[(date<'2021-01-01',year=='2021'),(date<'2022-01-01',year=='2022')]
FT=[(train,train)]
for stop,take in ((None,None),(0.01,None),(0.02,None),(0.03,None),(None,0.02),(None,0.03),(0.02,0.03)):
    lab=f'stop={stop} take={take}'
    with_exit(WF,('2021','2022'),stop,take,'WF '+lab)
    with_exit(FT,('2019','2020','2021','2022'),stop,take,'FT '+lab)
