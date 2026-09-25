"""Walk-forward inside the training period: fit on all earlier years, trade the next year (2020, 2021, 2022).
Used to compare model variants without touching the 2023-2024 test period."""
from lib import *
import sys
fees=5+stamp+0.2
px8=tick_bp<=12.5
ud,inv=np.unique(date,return_inverse=True)
def dmean(x):
    s=np.bincount(inv,np.nan_to_num(x)*np.isfinite(x));n=np.bincount(inv,np.isfinite(x)); return (s/np.maximum(n,1))[inv]
gap=first_open/pc-1; mgap=dmean(gap)
prev=lambda x: np.where(same,np.r_[np.nan,x[:-1]],np.nan)
p_ret=np.nan_to_num(prev(C[:,-1]/pc-1)); p_last30=np.nan_to_num(prev(C[:,-1]/C[:,T('14:30')]-1))
p_oc=np.nan_to_num(prev(C[:,-1]/first_open-1))
v20=np.nan_to_num(vol20,nan=np.nanmean(vol20))
BASE=['ret_pc','ret_open','ret_30','vwap_dev','imb','range_pos','mkt','mkt_open','gap','mgap']
def feats(i,extra=()):
    p=C[:,i]; j=max(0,i-30); tot=cumB[:,i]+cumS[:,i]
    cols={'ret_pc':p/pc-1,'ret_open':p/first_open-1,'ret_30':p/C[:,j]-1,'vwap_dev':p/VW[:,i]-1,
      'imb':np.where(tot>0,(cumB[:,i]-cumS[:,i])/np.maximum(tot,1),0),
      'range_pos':np.where(HI[:,i]>LO[:,i],(p-LO[:,i])/np.maximum(HI[:,i]-LO[:,i],1e-9),.5),
      'mkt':dmean(p/pc-1),'mkt_open':dmean(p/first_open-1),'gap':gap,'mgap':mgap,
      'p_ret':p_ret,'p_last30':p_last30,'p_oc':p_oc,'vol20':v20,
      'relvol':np.log(np.maximum(cumV[:,i],1)/np.maximum(np.nan_to_num(volu20,nan=1),1)),
      'range_now':(HI[:,i]-LO[:,i])/pc,'mkt_rel':(p/pc-1)-dmean(p/pc-1),
      'mkt_30':dmean(p/C[:,j]-1),'mkt_vwap':dmean(p/VW[:,i]-1)}
    names=BASE+list(extra)
    return np.column_stack([cols[n] for n in names]),names
def fit(X,y,m,lam=0.01):
    mu=X[m].mean(0);sd=X[m].std(0);sd=np.where(sd>0,sd,1);Z=(X[m]-mu)/sd
    w=np.linalg.solve(Z.T@Z+lam*len(Z)*np.eye(Z.shape[1]),Z.T@(y[m]-y[m].mean())); return mu,sd,w,y[m].mean()
def pred(mo,X): mu,sd,w,b=mo; return ((X-mu)/sd)@w+b
def run(times,thr,extra=(),buy_thr=None,lam=0.01,years=('2020','2021','2022'),periods=None,sizing=False,target='close'):
    n=len(sym); net=np.full(n,np.nan); taken=np.zeros(n,bool); wgt=np.ones(n)
    cache={}
    for t in times:
        i=T(t); X,_=feats(i,extra); p=C[:,i]; o=np.where(np.isnan(O[:,i+1]),p,O[:,i+1])
        y=(C[:,-1]/o-1)*1e4
        ok=np.isfinite(X).all(1)&np.isfinite(y)&px8&(p>lim_dn+0.011)&(p<lim_up-0.011)
        cache[t]=(X,y,ok,o)
    for yr in (periods or years):
        if isinstance(yr,tuple): fitmask,trade=yr
        else: fitmask=date<f'{yr}-01-01'; trade=year==yr
        for t in times:
            X,y,ok,o=cache[t]
            mo=fit(X,y,ok&fitmask,lam); pr=pred(mo,X)
            s=ok&trade&~taken&(pr<=-thr)
            net[s]=((o[s]-tick)/C[s,-1]-1)*1e4-fees[s]; taken|=s
            if sizing: wgt[s]=np.clip(-pr[s]/thr,1,3)
            if buy_thr:
                b=ok&trade&~taken&(pr>=buy_thr)
                net[b]=(C[b,-1]/(o[b]+tick)-1)*1e4-fees[b]; taken|=b
    return net,taken,wgt
def show(tag,net,taken,wgt=None,years=('2020','2021','2022')):
    per=np.isin(year,years)
    mean,tt,n=clustered(net,taken)
    w=np.ones(len(net)) if wgt is None else wgt
    ys=' '.join(f"{y[2:]}:{np.nanmean(net[taken&(year==y)]):+.0f}({(taken&(year==y)).sum()})" for y in years)
    print(f'{tag:52s} n={n:4d} trip={mean:+5.1f} t={tt:+.1f} per_sd={np.nansum(net[taken]*w[taken])/per.sum():+.2f} {ys}',flush=True)
T5=['10:00','10:30','13:30','14:00','14:30']
if __name__=='__main__':
    show('base 5 times thr20',*run(T5,20)[:2])
    show('base thr15',*run(T5,15)[:2]); show('base thr25',*run(T5,25)[:2]); show('base thr30',*run(T5,30)[:2])
    show('base lam0.1',*run(T5,20,lam=0.1)[:2])
    T7=['09:45','10:00','10:30','11:00','13:30','14:00','14:30']
    show('7 times',*run(T7,20)[:2])
    show('+prev day',*run(T5,20,extra=('p_ret','p_last30','p_oc'))[:2])
    show('+vol',*run(T5,20,extra=('vol20','relvol','range_now'))[:2])
    show('+mkt extra',*run(T5,20,extra=('mkt_rel','mkt_30','mkt_vwap'))[:2])
    show('+all extra',*run(T5,20,extra=('p_ret','p_last30','p_oc','vol20','relvol','range_now','mkt_30','mkt_vwap'))[:2])
    show('with buy side thr20',*run(T5,20,buy_thr=20)[:2])
    show('with buy side thr40',*run(T5,20,buy_thr=40)[:2])
    net,tk,w=run(T5,20,sizing=True); show('score sizing 1-3x',net,tk,w)
