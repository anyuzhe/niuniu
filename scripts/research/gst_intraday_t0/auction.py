"""Open auction -> close auction: sell (or buy) in the 09:25 auction, reverse in the 15:00 auction. Train only."""
from lib import *
fees=5+stamp+0.2
has=np.isfinite(auc)
oc=(C[:,-1]/auc-1)*1e4          # open-auction to close-auction return, bp
ud,inv=np.unique(date,return_inverse=True)
def dmean(x):
    s=np.bincount(inv,np.nan_to_num(x)*np.isfinite(x));n=np.bincount(inv,np.isfinite(x))
    return (s/np.maximum(n,1))[inv]
gap=auc/pc-1
mgap=dmean(gap)
# previous-day features (rows sorted by sym,date)
prev=lambda x: np.where(same,np.r_[np.nan,x[:-1]],np.nan)
p_oc=prev(C[:,-1]/first_open-1)          # yesterday open->close
p_ret=prev(C[:,-1]/pc-1)                 # yesterday close/prevclose
p_last30=prev(C[:,-1]/C[:,T('14:30')]-1) # yesterday last 30 min
p_loc=prev(np.where(HI[:,-1]>LO[:,-1],(C[:,-1]-LO[:,-1])/(HI[:,-1]-LO[:,-1]),.5))
p_limup=prev((C[:,-1]>=lim_up-0.005).astype(float))
p_mret=prev(dmean(C[:,-1]/pc-1))
tradable_open=has&(auc>lim_dn+0.011)&(auc<lim_up-0.011)
base=train&tradable_open
print('train rows',base.sum(),'mean oc',np.nanmean(oc[base]).round(2),'sd',np.nanstd(oc[base]).round(1),'fees',np.nanmean(fees[base]).round(1))
def show(tag,m,side):
    g=side*oc; net=g-fees
    mean,tt,n=clustered(net,m)
    if n<30: print(f'{tag:44s} n={n}'); return
    ys=' '.join(f"{y[2:]}:{np.nanmean(net[m&(year==y)]):+.0f}({(m&(year==y)).sum()})" for y in ('2019','2020','2021','2022'))
    print(f'{tag:44s} n={n:5d} gross={np.nanmean(g[m]):+6.1f} net={mean:+6.1f} t={tt:+.1f}  {ys}')
for name,x in (('gap',gap),('mgap',mgap),('gap-mgap',gap-mgap),('p_oc',p_oc),('p_ret',p_ret),('p_last30',p_last30),('p_loc',p_loc),('p_mret',p_mret)):
    ok=base&np.isfinite(x)
    q=np.nanquantile(x[ok],[.1,.9])
    show(f'{name} <=p10 ({q[0]:+.4f}) buy-first',ok&(x<=q[0]),+1)
    show(f'{name} <=p10 sell-first',ok&(x<=q[0]),-1)
    show(f'{name} >=p90 ({q[1]:+.4f}) buy-first',ok&(x>=q[1]),+1)
    show(f'{name} >=p90 sell-first',ok&(x>=q[1]),-1)
show('prev limit-up sell-first',base&(p_limup==1),-1)
show('prev limit-up buy-first',base&(p_limup==1),+1)
