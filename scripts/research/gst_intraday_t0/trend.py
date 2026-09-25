"""Trend breakout research on the 1-minute grid (train only unless told otherwise).
Event = first minute (in [start, last_entry]) whose close breaks a level; enter at the next minute's open ±1 tick;
exit per rule. Filters are evaluated at the breakout minute (no look-ahead)."""
from lib import *
import sys
fees=5+stamp+0.2
S=len(slots)
ud,inv=np.unique(date,return_inverse=True)
def dmean(x):
    s=np.bincount(inv,np.nan_to_num(x)*np.isfinite(x));n=np.bincount(inv,np.isfinite(x)); return (s/np.maximum(n,1))[inv]
MKT=dmean_all=None
mkt_pc=np.column_stack([dmean(C[:,i]/pc-1) for i in range(S)])
Hn=np.where(np.isnan(z['H']),C,z['H']); Ln=np.where(np.isnan(z['L']),C,z['L'])
prevrow=lambda x: np.where(same,np.r_[np.nan,x[:-1]],np.nan)
scale=pc/prevrow(C[:,-1])                         # dividend adjustment of yesterday's raw prices
p_hi=prevrow(HI[:,-1])*scale; p_lo=prevrow(LO[:,-1])*scale
avgv=np.where(cumV[:,-1]>0,cumV[:,-1]/S,np.nan)
vol_avg_prev=prevrow(avgv)                        # yesterday's average volume per minute
def levels(kind):
    """returns (up_level[n,S], down_level[n,S]) valid at each minute (nan = not defined yet)"""
    n=len(sym); up=np.full((n,S),np.nan); dn=np.full((n,S),np.nan)
    if kind.startswith('or'):
        k=int(kind[2:]); e=k-1
        up[:,k:]=HI[:,e][:,None]; dn[:,k:]=LO[:,e][:,None]
    elif kind=='pday':
        up[:]=p_hi[:,None]; dn[:]=p_lo[:,None]
    elif kind.startswith('dc'):
        w=int(kind[2:])
        for i in range(w,S):
            up[:,i]=np.max(Hn[:,i-w:i],1); dn[:,i]=np.min(Ln[:,i-w:i],1)
    return up,dn
def events(kind,side,start='09:46',last='14:00'):
    up,dn=levels(kind); lvl=up if side>0 else dn
    i0,i1=T(start),T(last)
    hit=np.full(len(sym),-1)
    for i in range(i0,i1+1):
        c=C[:,i]; prev_ok=C[:,i-1]<=lvl[:,i] if side>0 else C[:,i-1]>=lvl[:,i]
        new=(hit<0)&np.isfinite(lvl[:,i])&((c>lvl[:,i]) if side>0 else (c<lvl[:,i]))&prev_ok
        hit[new]=i
    return hit
def trade(hit,side,exit_rule='close',trail=None):
    n=len(sym); net=np.full(n,np.nan)
    ok=hit>=0
    idx=np.flatnonzero(ok)
    j=hit[idx]+1
    o=O[idx,j]; o=np.where(np.isnan(o),C[idx,j-1],o)
    entry=o+side*tick
    good=(entry<lim_up[idx]-0.005) if side>0 else (entry>lim_dn[idx]+0.005)
    exitp=C[idx,-1].copy()
    if exit_rule!='close':
        for r,k in enumerate(idx):
            best=entry[r]
            for m in range(j[r],S-1):
                c=C[k,m]
                if exit_rule=='trail':
                    best=max(best,c) if side>0 else min(best,c)
                    if (side>0 and c<=best*(1-trail)) or (side<0 and c>=best*(1+trail)):
                        nxt=O[k,m+1] if np.isfinite(O[k,m+1]) else c; exitp[r]=nxt-side*tick; break
                elif exit_rule=='vwap':
                    if (side>0 and c<VW[k,m]) or (side<0 and c>VW[k,m]):
                        nxt=O[k,m+1] if np.isfinite(O[k,m+1]) else c; exitp[r]=nxt-side*tick; break
    g=side*(exitp/entry-1)*1e4-fees[idx]
    net[idx[good]]=g[good]
    return net
def filt(hit,side,name):
    ok=hit>=0; i=np.where(ok,hit,0); r=np.arange(len(sym))
    if name=='none': return ok
    if name=='mkt': return ok&(side*mkt_pc[r,i]>0.003)
    if name=='vwap': return ok&(side*(C[r,i]-VW[r,i])>0)
    if name=='vol':  # breakout minute volume >= 3x yesterday's average minute volume
        return ok&(z['V'][r,i]>=3*vol_avg_prev)
    if name=='imb':
        tot=cumB[r,i]+cumS[r,i]; return ok&(side*(cumB[r,i]-cumS[r,i])>0.1*tot)
    if name=='mkt+vol': return filt(hit,side,'mkt')&filt(hit,side,'vol')
    if name=='mkt+vwap': return filt(hit,side,'mkt')&filt(hit,side,'vwap')
def rep(tag,net,m,years=('2019','2020','2021','2022')):
    mm=m&np.isfinite(net); mean,tt,n=clustered(net,mm)
    per=np.isin(year,years)
    ys=' '.join(f"{y[2:]}:{np.nanmean(net[mm&(year==y)]):+.0f}({(mm&(year==y)).sum()})" for y in years)
    print(f'{tag:44s} n={n:5d} trip={mean:+6.1f} t={tt:+.1f} per_sd={np.nansum(net[mm])/per.sum():+.2f}  {ys}',flush=True)
    return mean,tt,n
if __name__=='__main__':
    px8=tick_bp<=12.5
    for kind in ('or15','or30','pday','dc30','dc60'):
        for side in (1,-1):
            hit=events(kind,side)
            net=trade(hit,side)
            for f in ('none','mkt','vol','vwap','imb','mkt+vol'):
                rep(f'{kind} {"long" if side>0 else "short"} {f}',net,train&px8&filt(hit,side,f))
