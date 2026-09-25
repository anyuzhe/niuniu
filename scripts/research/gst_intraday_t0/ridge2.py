from family import *
fees=5+stamp+0.2
i=T('14:00'); p=C[:,i]; M=mkt(i)
tot=cumB[:,i]+cumS[:,i]
X=np.column_stack([p/pc-1, p/first_open-1, p/VW[:,i]-1, np.where(tot>0,(cumB[:,i]-cumS[:,i])/np.maximum(tot,1),0),
   np.where(HI[:,i]>LO[:,i],(p-LO[:,i])/np.maximum(HI[:,i]-LO[:,i],1e-9),.5), M, first_open/pc-1])
names=['ret_pc','ret_open','vwap_dev','imb','range_pos','mkt','gap']
y=(C[:,-1]/C[:,i]-1)*1e4
ok=np.isfinite(X).all(1)&np.isfinite(y)&px8&(p>lim_dn+0.011)&(p<lim_up-0.011)
entry=Onext(i)-tick; g=(entry/C[:,-1]-1)*1e4-fees
def fit(mask):
    mu=X[mask].mean(0); sd=X[mask].std(0); Z=(X[mask]-mu)/sd
    w=np.linalg.solve(Z.T@Z+0.01*len(Z)*np.eye(Z.shape[1]),Z.T@(y[mask]-y[mask].mean()))
    return mu,sd,w,y[mask].mean()
def pred(model):
    mu,sd,w,b=model; return ((X-mu)/sd)@w+b
m1=fit(ok&(date<='2021-12-31')); pr=pred(m1)
val=ok&(date>='2022-01-01')&train
for thr in (15,20,25,30):
    for part,mm in (('fit',ok&(date<='2021-12-31')),('val2022',val)):
        s=mm&(pr<=-thr); mean,tt,n=clustered(g,s)
        print(thr,part,n,f'{mean:+.1f}',f't={tt:+.1f}', 'corr',round(np.corrcoef(pr[mm],y[mm])[0,1],3))
m2=fit(ok&train)
print('FULL-TRAIN MODEL'); print('mu',m2[0].tolist()); print('sd',m2[1].tolist()); print('w',m2[2].tolist()); print('b',m2[3])
pr2=pred(m2)
for thr in (20,30):
    s=ok&train&(pr2<=-thr); mean,tt,n=clustered(g,s)
    ys=' '.join(f"{yy}:{np.nanmean(g[s&(year==yy)]):+.0f}({(s&(year==yy)).sum()})" for yy in ('2019','2020','2021','2022'))
    print('in-sample full train thr',thr,n,f'{mean:+.1f} t={tt:+.1f}',ys)
