"""Gao et al. market intraday momentum on the 16-stock equal-weight average: first half hour (prev close -> 10:00)
and seventh half hour (14:00 -> 14:30) predicting the last half hour (14:30 -> close); also morning -> afternoon."""
from lib import *
ud,inv=np.unique(date,return_inverse=True)
def dm(x):
    s=np.bincount(inv,np.nan_to_num(x)*np.isfinite(x));n=np.bincount(inv,np.isfinite(x)); return s/np.maximum(n,1)
r1=dm(C[:,T('10:00')]/pc-1); r7=dm(C[:,T('14:30')]/C[:,T('14:00')]-1); r8=dm(C[:,-1]/C[:,T('14:30')]-1)
ram=dm(C[:,T('11:30')]/pc-1); rpm=dm(C[:,-1]/C[:,T('11:30')]-1)
yr=np.array([d[:4] for d in ud]); tr=ud<='2022-12-31'
def ols(y,X,m):
    X1=np.column_stack([np.ones(m.sum())]+[x[m] for x in X]); b=np.linalg.lstsq(X1,y[m],rcond=None)[0]
    res=y[m]-X1@b; r2=1-res.var()/y[m].var(); return b,r2
for lab,y,X in (('last half hour ~ r1',r8,[r1]),('last half hour ~ r7',r8,[r7]),('last half hour ~ r1+r7',r8,[r1,r7]),('afternoon ~ morning',rpm,[ram])):
    b,r2=ols(y,X,tr)
    # out of sample on test with train coefficients
    X1=np.column_stack([np.ones((~tr).sum())]+[x[~tr] for x in X]); pr=X1@b; yt=y[~tr]
    r2o=1-((yt-pr)**2).sum()/((yt-yt[tr.sum():].mean() if False else yt-y[tr].mean())**2).sum()
    hit=np.mean(np.sign(pr)==np.sign(yt))
    print(f'{lab:26s} train coef {np.round(b[1:],3)} R2 {r2*100:.2f}% | test OOS R2 {r2o*100:.2f}% sign hit {hit:.2f}  n_test {len(yt)}')
    for y_ in ('2023','2024'):
        m=yr[~tr]==y_; print('      ',y_, 'corr(pred,actual)',round(np.corrcoef(pr[m],yt[m])[0,1],3))
print('sd last half hour (bp)',round(r8.std()*1e4,1),' sd afternoon',round(rpm.std()*1e4,1))
