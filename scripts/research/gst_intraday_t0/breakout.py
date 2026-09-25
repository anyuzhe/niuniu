"""Taker momentum: first minute (after start) whose close crosses ref*(1±s); enter at the next minute's open ±1 tick;
exit in the closing auction. Buy-first on the up cross, sell-first on the down cross."""
from lib import *
import sys
fees=5+stamp+0.2
S=len(slots)
def cross(ref,s,side,start='09:35',stop='14:30',filt=None):
    i0,i1=T(start),T(stop)
    lvl=ref*(1+side*s)
    hit=np.full(len(ref),-1)
    for i in range(i0,i1+1):
        c=C[:,i]
        new=(hit<0)&((c>=lvl) if side>0 else (c<=lvl))
        # must not already be beyond the level at start (fresh cross)
        hit[new]=i
    already=((C[:,i0-1]>=lvl) if side>0 else (C[:,i0-1]<=lvl))
    hit[already]=-1
    ok=hit>=0
    idx=np.where(ok,hit+1,0)
    o=O[np.arange(len(ref)),idx]; o=np.where(np.isnan(o),C[np.arange(len(ref)),np.minimum(idx,S-1)],o)
    entry=o+side*tick
    # cannot buy at limit up / sell at limit down
    ok&=(entry<lim_up-0.005) if side>0 else (entry>lim_dn+0.005)
    g=side*(C[:,-1]/entry-1)*1e4
    return ok,g-fees,hit
def rep(tag,ok,net,m):
    mm=m&ok; mean,tt,n=clustered(net,mm)
    ys=' '.join(f"{y[2:]}:{np.nanmean(net[mm&(year==y)]):+.0f}({(mm&(year==y)).sum()})" for y in np.unique(year[m]))
    print(f'{tag:42s} n={n:5d} net={mean:+6.1f} t={tt:+.1f} per_stockday={np.nansum(net[mm])/m.sum():+.2f}  {ys}',flush=True)
if __name__=='__main__':
    period=train
    for refname,ref in (('pc',pc),('open',first_open)):
        for s in (.01,.02,.03,.04):
            for side in (1,-1):
                ok,net,_=cross(ref,s,side)
                rep(f'{refname} s={s:.0%} {"buy" if side>0 else "sell"}-first',ok,net,period)
