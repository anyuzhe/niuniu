"""Which 10:30 features predict the market's move from 10:30 to the close? (research only)"""
import numpy as np, os
H=os.environ['HOME']; Z={}
for y in range(2020,2027):
    z=np.load(f'{H}/research/brk/mf_{y}.npz',allow_pickle=True)
    for k in z.files: Z.setdefault(k,[]).append(z[k])
Z={k:np.concatenate(v) for k,v in Z.items()}
d=Z['date']; y=Z['y']; crash=y<=-0.01; yr=np.array([x[:4] for x in d]).astype(int)
feats=[k for k in Z if k not in ('date','y','day')]
def auc(s,lab):
    ok=np.isfinite(s); s=s[ok]; lab=lab[ok]; o=np.argsort(s); r=np.empty(len(s)); r[o]=np.arange(1,len(s)+1)
    n1=lab.sum(); n0=len(lab)-n1; return (r[lab].sum()-n1*(n1+1)/2)/(n1*n0) if n1 and n0 else np.nan
print(f'交易日 {len(d)}；10:30 后大盘又跌 1% 以上 {crash.sum()} 天（{crash.mean()*100:.0f}%）；各年: '+' '.join(f"{Y}:{crash[yr==Y].mean()*100:.0f}%" for Y in range(2020,2027)))
print('\n单个因子：与“10:30 到收盘大盘涨跌”的相关（逐年）| 判断“又跌1%以上”的 AUC（0.5=没用，越偏离0.5越好）')
rows=[]
for f in feats:
    x=Z[f]; cs=[np.corrcoef(x[(yr==Y)&np.isfinite(x)],y[(yr==Y)&np.isfinite(x)])[0,1] for Y in range(2020,2027)]
    rows.append((np.mean(np.abs(cs))*np.sign(np.mean(cs)),f,cs,auc(x,crash)))
rows.sort(key=lambda r:-abs(r[0]))
for m,f,cs,a in rows: print(f'  {f:11s} 平均{m:+.2f} | '+' '.join(f'{c:+.2f}' for c in cs)+f' | AUC {a:.2f} 同号年数 {sum(np.sign(c)==np.sign(np.mean(cs)) for c in cs)}/7')
# walk-forward ridge and logistic
from numpy.linalg import solve
def zs(X,mu,sd): return (X-mu)/sd
use=[f for f in feats if f!='wd']
X=np.column_stack([Z[f] for f in use]); X=np.where(np.isfinite(X),X,np.nan)
pred=np.full(len(y),np.nan); prob=np.full(len(y),np.nan)
for Y in range(2021,2027):
    tr=(yr<Y)&np.all(np.isfinite(X),1); te=(yr==Y)&np.all(np.isfinite(X),1)
    mu=X[tr].mean(0); sd=X[tr].std(0)+1e-12; A=zs(X[tr],mu,sd); lam=len(A)*1.0
    w=solve(A.T@A+lam*np.eye(A.shape[1]),A.T@(y[tr]-y[tr].mean())); pred[te]=zs(X[te],mu,sd)@w+y[tr].mean()
    # logistic (crash) with L2, few Newton steps
    b=np.zeros(A.shape[1]+1); Ab=np.c_[np.ones(len(A)),A]; t=crash[tr].astype(float)
    for _ in range(25):
        p=1/(1+np.exp(-Ab@b)); g=Ab.T@(p-t)+np.r_[0,b[1:]]*len(A)*0.05; Hs=(Ab*(p*(1-p))[:,None]).T@Ab+np.diag(np.r_[0,np.ones(len(b)-1)])*len(A)*0.05
        b-=np.linalg.solve(Hs,g)
    prob[te]=1/(1+np.exp(-np.c_[np.ones(te.sum()),zs(X[te],mu,sd)]@b))
print('\n逐年滚动（只用之前年份拟合）：')
for Y in range(2021,2027):
    m=(yr==Y)&np.isfinite(pred); c=np.corrcoef(pred[m],y[m])[0,1]; a=auc(prob[m],crash[m])
    top=m&(prob>=np.nanpercentile(prob[m],80))
    print(f'  {Y}: 预测与实际相关 {c:+.2f} | 大跌判断 AUC {a:.2f} | 风险最高的 20% 日子里真大跌的比例 {crash[top].mean()*100:3.0f}%（全年 {crash[m].mean()*100:.0f}%），抓到全年大跌日的 {crash[top].sum()/max(crash[m].sum(),1)*100:3.0f}%')
np.savez(f'{H}/research/brk/mfpred.npz',date=d,pred=pred,prob=prob,y=y)
