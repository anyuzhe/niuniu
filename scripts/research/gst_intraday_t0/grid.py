"""Passive grid T with limit orders on 1-minute bars (train only by default).
Sell-first leg: limit sell at ref*(1+s); after it fills, limit buy at sell*(1-tp); if not filled, buy in the closing auction.
Buy-first leg: limit buy at ref*(1-s); then limit sell (base shares) at buy*(1+tp); else sell in the closing auction.
Limit fills need a trade-through by one tick in a LATER minute than the order was placed (no same-minute round trips)."""
from lib import *
import sys
Hn=z['H'];Ln=z['L']
fee_sell=2.5+stamp+0.1; fee_buy=2.5+0.1   # bp of notional (commission 万2.5 assuming >= 5 yuan min, transfer)
def rnd(x): return np.round(x/tick)*tick
def leg(side,ref,s,tp,start='09:31',stop_new='14:30',stop_loss=None):
    n=len(ref); S=len(slots)
    p_in=rnd(ref*(1+s)) if side<0 else rnd(ref*(1-s))
    state=np.zeros(n,int)   # 0 waiting, 1 open, 2 done
    entry=np.full(n,np.nan); exitp=np.full(n,np.nan); reason=np.zeros(n,int)
    p_out=np.full(n,np.nan)
    i0=T(start); i1=T(stop_new)
    for i in range(S):
        h=Hn[:,i]; l=Ln[:,i]; traded=np.isfinite(h)
        # exits first (orders placed in earlier minutes)
        op=(state==1)&traded
        if side<0: hit=op&(l<=p_out-tick+1e-9)
        else: hit=op&(h>=p_out+tick-1e-9)
        exitp[hit]=p_out[hit]; state[hit]=2; reason[hit]=1
        if stop_loss is not None:
            c=C[:,i]
            sl=(state==1)&traded&((side<0)&(c>=entry*(1+stop_loss))|(side>0)&(c<=entry*(1-stop_loss)))
            # stop out at the next minute's close approx: use this close +/- 1 tick
            exitp[sl]=c[sl]-side*tick; state[sl]=2; reason[sl]=2
        if i0<=i<=i1:
            w=(state==0)&traded
            if side<0: f=w&(h>=p_in+tick-1e-9)&(p_in<lim_up)
            else: f=w&(l<=p_in-tick+1e-9)&(p_in>lim_dn)
            entry[f]=p_in[f]; state[f]=1
            p_out[f]=rnd(p_in[f]*(1-tp)) if side<0 else rnd(p_in[f]*(1+tp))
        if i==i1: state[state==0]=3
    last=state==1
    exitp[last]=C[last,-1]; reason[last]=3   # closing auction
    done=np.isfinite(entry)
    if side<0: gross=(entry/exitp-1)*1e4; fees=fee_sell+fee_buy
    else: gross=(exitp/entry-1)*1e4; fees=fee_buy+fee_sell
    net=np.where(done,gross-fees,np.nan)
    return net,reason,done
def report(tag,net,done,m):
    mm=m&done
    mean,tt,n=clustered(net,mm)
    days=m.sum()
    per_day=np.nansum(net[mm])/max(days,1)
    ys=' '.join(f"{y[2:]}:{np.nanmean(net[mm&(year==y)]):+.0f}({(mm&(year==y)).sum()})" for y in np.unique(year[m]))
    print(f'{tag:40s} trips={n:5d} per_trip={mean:+6.1f} t={tt:+.1f} per_stockday={per_day:+.2f}bp  {ys}',flush=True)
if __name__=='__main__':
    period=train if len(sys.argv)<2 else test
    for refname,ref in (('pc',pc),('open',first_open)):
        for s in (.01,.02,.03):
            for tp in (.005,.01,.02):
                for side in (-1,1):
                    net,reason,done=leg(side,ref,s,tp)
                    report(f'{refname} s={s:.0%} tp={tp:.1%} {"sell" if side<0 else "buy"}-first',net,done,period)
