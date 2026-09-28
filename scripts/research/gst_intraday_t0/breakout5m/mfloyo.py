"""Leave-one-year-out version of the 10:30 market model (sensitivity check only; not a real forecast):
for each year, fit on all other years and predict it, so 2020 can be scored too. Research only."""
import numpy as np, os
H=os.environ['HOME']; Z={}
for y in range(2020,2027):
    z=np.load(f'{H}/research/brk/mf_{y}.npz',allow_pickle=True)
    for k in z.files: Z.setdefault(k,[]).append(z[k])
Z={k:np.concatenate(v) for k,v in Z.items()}
d=Z['date']; y=Z['y']; crash=y<=-0.01; yr=np.array([x[:4] for x in d]).astype(int)
use=[k for k in Z if k not in ('date','y','day','wd')]
X=np.column_stack([Z[f] for f in use]); good=np.all(np.isfinite(X),1)
prob=np.full(len(y),np.nan)
for Y in range(2020,2027):
    tr=(yr!=Y)&good; te=(yr==Y)&good
    mu=X[tr].mean(0); sd=X[tr].std(0)+1e-12; A=(X[tr]-mu)/sd
    b=np.zeros(A.shape[1]+1); Ab=np.c_[np.ones(len(A)),A]; t=crash[tr].astype(float)
    for _ in range(25):
        p=1/(1+np.exp(-Ab@b)); g=Ab.T@(p-t)+np.r_[0,b[1:]]*len(A)*0.05; Hs=(Ab*(p*(1-p))[:,None]).T@Ab+np.diag(np.r_[0,np.ones(len(b)-1)])*len(A)*0.05
        b-=np.linalg.solve(Hs,g)
    prob[te]=1/(1+np.exp(-np.c_[np.ones(te.sum()),(X[te]-mu)/sd]@b))
np.savez(f'{H}/research/brk/mfpred_loyo.npz',date=d,prob=prob,y=y); print('ok',np.isfinite(prob).sum())
