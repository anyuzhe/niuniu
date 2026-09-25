from trend import *
px8=tick_bp<=12.5
r=np.arange(len(sym))
def mk(hit,side,thr):
    ok=hit>=0; i=np.where(ok,hit,0); return ok&(side*mkt_pc[r,i]>thr)
for kind in ('or30','dc30','pday'):
    for side in (1,-1):
        hit=events(kind,side)
        base=trade(hit,side)
        for thr in (0.005,0.01,0.015):
            m=train&px8&mk(hit,side,thr)
            rep(f'{kind} {"long" if side>0 else "short"} mkt>{thr:.1%} close',base,m)
            rep(f'{kind} {"long" if side>0 else "short"} mkt>{thr:.1%}+vol close',base,m&filt(hit,side,'vol'))
        m=train&px8&mk(hit,side,0.005)
        for ex,tr in (('trail',0.01),('trail',0.02),('vwap',None)):
            rep(f'{kind} {"long" if side>0 else "short"} mkt>0.5% {ex}{tr or ""}',trade(hit,side,ex,tr),m)
