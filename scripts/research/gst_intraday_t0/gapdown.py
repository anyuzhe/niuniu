"""Gap-down: decide on the 09:25 auction price (known at 09:25), buy at the first continuous trade (09:30) + 1 tick,
sell the same number of base shares in the closing auction. Train only unless argv[1]=='all'."""
import sys
from auction import *
period = train
o1=np.where(np.isnan(O[:,0]),C[:,0],O[:,0])
ok0=period&has&(o1<lim_up-0.011)&(o1>lim_dn+0.011)
def res(tag,m,entry_ticks=1.0,side=+1,show_years=True):
    entry=o1+side*entry_ticks*tick
    g=side*(C[:,-1]/entry-1)*1e4; net=g-fees
    mean,tt,n=clustered(net,m)
    if n<30: print(tag,'n',n); return
    ys=' '.join(f"{y[2:]}:{np.nanmean(net[m&(year==y)]):+.0f}({(m&(year==y)).sum()})" for y in np.unique(year[m]))
    print(f'{tag:46s} n={n:5d} gross={np.nanmean(g[m]):+6.1f} net={mean:+6.1f} t={tt:+.1f} win={np.mean(net[m]>0):.2f} {ys}')
for thr in (-.005,-.01,-.015,-.02,-.03,-.05):
    res(f'gap<={thr:.1%}',ok0&(gap<=thr))
for thr in (-.01,-.02):
    res(f'gap<={thr:.1%} px>=8',ok0&(gap<=thr)&(tick_bp<=12.5))
    res(f'gap<={thr:.1%} & mgap<=-0.5%',ok0&(gap<=thr)&(mgap<=-.005))
    res(f'gap<={thr:.1%} & mgap>-0.5%',ok0&(gap<=thr)&(mgap>-.005))
    res(f'gap-mgap<={thr:.1%}',ok0&(gap-mgap<=thr))
    res(f'gap<={thr:.1%} & p_ret<0',ok0&(gap<=thr)&(p_ret<0))
    res(f'gap<={thr:.1%} & p_ret>=0',ok0&(gap<=thr)&(p_ret>=0))
    res(f'gap<={thr:.1%} & open drop continues: first bar down',ok0&(gap<=thr)&(C[:,0]<o1))
# enter a bit later (after the first 5 minutes) to follow the article's rule
o5=np.where(np.isnan(O[:,T('09:35')+1]),C[:,T('09:35')],O[:,T('09:35')+1])
for thr in (-.01,-.02):
    m=ok0&(gap<=thr)
    g=(C[:,-1]/(o5+tick)-1)*1e4-fees; mean,tt,n=clustered(g,m); print(f'gap<={thr:.1%} enter 09:36',n,round(mean,1),round(tt,1))
    # still below prev close at 09:35?
    m2=m&(C[:,T('09:35')]<pc); mean,tt,n=clustered(g,m2); print(f'   ...and still below prev close at 09:35',n,round(mean,1),round(tt,1))
