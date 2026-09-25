from trend import *
px8=tick_bp<=12.5
r=np.arange(len(sym))
ret_d=C[:,-1]/pc-1
def roll_prev_sum(x,n):
    out=np.full(len(x),np.nan)
    for s in np.unique(sym):
        ix=np.flatnonzero(sym==s); v=np.nan_to_num(x[ix]); cs=np.r_[0,np.cumsum(v)]
        for k in range(len(ix)):
            if k>=n: out[ix[k]]=cs[k]-cs[k-n]
    return out
tr20=roll_prev_sum(ret_d,20); tr5=roll_prev_sum(ret_d,5)
for kind in ('or30','dc30','pday'):
    for side in (1,-1):
        hit=events(kind,side); net=trade(hit,side); ok=hit>=0; i=np.where(ok,hit,0)
        mk=side*mkt_pc[r,i]
        for lab,m in (('20d trend same side',side*tr20>0.05),('20d trend opposite',side*tr20<-0.05),('5d trend same',side*tr5>0.03),
                      ('20d same + mkt>0.5%',(side*tr20>0.05)&(mk>0.005)),('20d same + mkt>0.5% + vol',(side*tr20>0.05)&(mk>0.005)&filt(hit,side,'vol'))):
            rep(f'{kind} {"long" if side>0 else "short"} {lab}',net,train&px8&ok&m)
