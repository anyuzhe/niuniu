from lib import *
import sys
px8=tick_bp<=12.5
ud,inv=np.unique(date,return_inverse=True)
def mkt(i):
    x=C[:,i]/pc-1
    s=np.bincount(inv,np.nan_to_num(x));n=np.bincount(inv,np.isfinite(x))
    return (s/n)[inv]
Onext=lambda i: np.where(np.isnan(O[:,i+1]),C[:,i],O[:,i+1])
def run(t,thr,mcond=None,period=train,filt=px8,show=True,commission=2.5):
    i=T(t); x=C[:,i]/pc-1
    tradable=(C[:,i]>lim_dn+0.011)&(C[:,i]<lim_up-0.011)
    m=period&tradable&filt&(x<=thr)
    if mcond is not None: m&=mkt(i)<=mcond
    entry=Onext(i)-tick            # sell 1 tick below the next bar's open
    exitp=C[:,-1]                  # buy back in the closing auction at the close
    gross=(entry/exitp-1)*1e4      # sell-first gain in bp of the sold value
    fees=2*commission+stamp+0.2
    net=gross-fees
    mean,tt,n=clustered(net,m)
    if show:
        ys=' '.join(f"{y}:{np.nanmean(net[m&(year==y)]):+.0f}({(m&(year==y)).sum()})" for y in np.unique(year[m]))
        print(f'{t} ret<={thr*100:.0f}% mkt<={mcond} n={n:4d} net={mean:+6.1f} t={tt:+.1f} win={np.mean(net[m]>0):.2f}  {ys}')
    return m,net
if __name__=='__main__':
    for t in ['10:00','10:30','11:00','13:30','14:00']:
        for thr in (-.03,-.04,-.05):
            run(t,thr)
    for t in ['10:30','13:30','14:00']:
        for thr in (-.02,-.03):
            run(t,thr,-.01)
