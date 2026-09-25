"""Ridge on a handful of features at several decision times; fit 2019-2021, check 2022 (all inside train)."""
from family import *
fees=5+stamp+0.2
def features(i):
    p=C[:,i]; M=mkt(i)
    tot=cumB[:,i]+cumS[:,i]; j=max(0,i-30); t30=(cumB[:,i]-cumB[:,j])+(cumS[:,i]-cumS[:,j])
    f=[p/pc-1, p/first_open-1, p/C[:,j]-1, p/VW[:,i]-1,
       np.where(tot>0,(cumB[:,i]-cumS[:,i])/np.maximum(tot,1),0),
       np.where(t30>0,((cumB[:,i]-cumB[:,j])-(cumS[:,i]-cumS[:,j]))/np.maximum(t30,1),0),
       np.log(np.maximum(cumV[:,i],1)/np.maximum(volu20,1)),
       np.where(HI[:,i]>LO[:,i],(p-LO[:,i])/np.maximum(HI[:,i]-LO[:,i],1e-9),.5),
       M, first_open/pc-1, np.nan_to_num(prev_ret)]
    X=np.column_stack(f)
    return X
names=['ret_pc','ret_open','ret_30','vwap_dev','imb','imb30','logrelvol','range_pos','mkt','gap','prev_ret']
for t in ['10:30','13:30','14:00']:
    i=T(t); X=features(i)
    y=(C[:,-1]/C[:,i]-1)*1e4
    ok=np.isfinite(X).all(1)&np.isfinite(y)&np.isfinite(volu20)&px8&(C[:,i]>lim_dn+0.011)&(C[:,i]<lim_up-0.011)
    fit=ok&(date<='2021-12-31'); val=ok&(date>='2022-01-01')&(date<='2022-12-31')
    mu=X[fit].mean(0); sd=X[fit].std(0); Z=(X-mu)/sd
    lam=len(Z[fit])*0.01
    A=Z[fit].T@Z[fit]+lam*np.eye(Z.shape[1]); w=np.linalg.solve(A,Z[fit].T@(y[fit]-y[fit].mean()))
    pred=Z@w+y[fit].mean()
    print(t,'weights', ' '.join(f'{n}:{v:+.1f}' for n,v in zip(names,w)))
    for part,m in (('fit 2019-21',fit),('val 2022',val)):
        c=np.corrcoef(pred[m],y[m])[0,1]
        for thr in (20,30,40):
            sel_s=m&(pred<=-thr); sel_b=m&(pred>=thr)
            entry_s=Onext(i)-tick; g_s=(entry_s/C[:,-1]-1)*1e4-fees
            entry_b=Onext(i)+tick; g_b=(C[:,-1]/entry_b-1)*1e4-fees
            ms,ts,ns=clustered(g_s,sel_s); mb,tb,nb=clustered(g_b,sel_b)
            print(f'  {part} corr={c:+.3f} |pred|>={thr}: sell-first n={ns} net={ms:+.1f} t={ts:+.1f} | buy-first n={nb} net={mb:+.1f} t={tb:+.1f}')
