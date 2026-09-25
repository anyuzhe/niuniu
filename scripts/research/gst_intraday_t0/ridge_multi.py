"""Per-decision-time ridge models for the return from the next minute's open to the closing auction.
Fit 2019-2021, validate 2022 (both inside the training period). Features use only data up to the decision minute."""
from lib import *
import json, sys
fees=5+stamp+0.2
px8=tick_bp<=12.5
ud,inv=np.unique(date,return_inverse=True)
def dmean(x):
    s=np.bincount(inv,np.nan_to_num(x)*np.isfinite(x));n=np.bincount(inv,np.isfinite(x)); return (s/np.maximum(n,1))[inv]
gap=first_open/pc-1; mgap=dmean(gap)
NAMES=['ret_pc','ret_open','ret_30','vwap_dev','imb','range_pos','mkt','mkt_open','gap','mgap']
def feats(i):
    p=C[:,i]; j=max(0,i-30); tot=cumB[:,i]+cumS[:,i]
    return np.column_stack([p/pc-1,p/first_open-1,p/C[:,j]-1,p/VW[:,i]-1,
        np.where(tot>0,(cumB[:,i]-cumS[:,i])/np.maximum(tot,1),0),
        np.where(HI[:,i]>LO[:,i],(p-LO[:,i])/np.maximum(HI[:,i]-LO[:,i],1e-9),.5),
        dmean(p/pc-1),dmean(p/first_open-1),gap,mgap])
def fit(X,y,m,lam=0.01):
    mu=X[m].mean(0);sd=X[m].std(0);sd=np.where(sd>0,sd,1.0);Z=(X[m]-mu)/sd
    w=np.linalg.solve(Z.T@Z+lam*len(Z)*np.eye(Z.shape[1]),Z.T@(y[m]-y[m].mean()))
    return mu,sd,w,y[m].mean()
def pred(model,X):
    mu,sd,w,b=model; return ((X-mu)/sd)@w+b
TIMES=['09:31','10:00','10:30','11:00','13:30','14:00','14:30']
out={}
for t in TIMES:
    i=T(t); X=feats(i); p=C[:,i]
    o=np.where(np.isnan(O[:,i+1]),p,O[:,i+1])
    y=(C[:,-1]/o-1)*1e4
    ok=np.isfinite(X).all(1)&np.isfinite(y)&px8&(p>lim_dn+0.011)&(p<lim_up-0.011)
    f1=ok&(date<='2021-12-31'); v=ok&train&(date>='2022-01-01')
    m1=fit(X,y,f1); pr=pred(m1,X)
    buy=(C[:,-1]/(o+tick)-1)*1e4-fees; sell=((o-tick)/C[:,-1]-1)*1e4-fees
    line=[t,f'corr fit {np.corrcoef(pr[f1],y[f1])[0,1]:+.3f} val {np.corrcoef(pr[v],y[v])[0,1]:+.3f}']
    for thr in (20,30,40):
        for part,mm in (('val',v),):
            ms,ts,ns=clustered(sell,mm&(pr<=-thr)); mb,tb,nb=clustered(buy,mm&(pr>=thr))
            line.append(f'thr{thr}: sell n={ns} {ms:+.0f}(t{ts:+.1f}) buy n={nb} {mb:+.0f}(t{tb:+.1f})')
    print(' | '.join(line),flush=True)
    full=fit(X,y,ok&train)
    out[t]={'mu':full[0].tolist(),'sd':full[1].tolist(),'w':full[2].tolist(),'b':float(full[3])}
json.dump({'names':NAMES,'models':out},open('ridge_multi.json','w'))
