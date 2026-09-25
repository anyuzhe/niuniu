from lib import *
cost=cost_bp()
px8=tick_bp<=12.5
# market proxy: equal-weight average of the 16 stocks' return since prev close at time i, same date
ud,inv=np.unique(date,return_inverse=True)
def mkt(i):
    x=C[:,i]/pc-1
    s=np.bincount(inv,np.nan_to_num(x));n=np.bincount(inv,np.isfinite(x))
    return (s/n)[inv]
def show(tag,m,g):
    mean,tt,n=clustered(g,m)
    if not n: print(tag,'none'); return
    ys=' '.join(f"{y}:{np.nanmean(g[m&(year==y)]):+.0f}({(m&(year==y)).sum()})" for y in ('2019','2020','2021','2022'))
    print(f'{tag:55s} n={n:4d} gross={mean:+6.1f} t={tt:+.1f} net1tick={mean-np.nanmean(cost[m]):+6.1f}  {ys}')
for t in ['13:30','14:00','14:30']:
    i=T(t); x=C[:,i]/pc-1; M=mkt(i)
    tradable=(C[:,i]>lim_dn+0.011)&(C[:,i]<lim_up-0.011)
    tot=cumB[:,i]+cumS[:,i]; imb=np.where(tot>0,(cumB[:,i]-cumS[:,i])/np.maximum(tot,1),0)
    for ex in ('14:50','15:00'):
        e=T(ex); r=fwd(i,e)
        base=train&tradable&px8
        show(f'{t}->{ex} down<=-3%',base&(x<=-.03),-r)
        show(f'{t}->{ex} down<=-4%',base&(x<=-.04),-r)
        show(f'{t}->{ex} up>=+3% (buy first)',base&(x>=.03),r)
        show(f'{t}->{ex} up>=+4% (buy first)',base&(x>=.04),r)
    e=T('14:50'); r=fwd(i,e)
    base=train&tradable&px8
    show(f'{t} down<=-3% & imb<0',base&(x<=-.03)&(imb<0),-r)
    show(f'{t} down<=-3% & mkt<=-1%',base&(x<=-.03)&(M<=-.01),-r)
    show(f'{t} down<=-3% & mkt>-1%',base&(x<=-.03)&(M>-.01),-r)
    show(f'{t} mkt<=-1.5% all stocks',base&(M<=-.015),-r)
    show(f'{t} mkt>=+1.5% all stocks',base&(M>=.015),r)
    show(f'{t} rel (x-M)<=-3%',base&(x-M<=-.03),-r)
