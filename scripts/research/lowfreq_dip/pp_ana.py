import numpy as np, warnings; warnings.filterwarnings('ignore')
Z=np.load('pp_feat.npz',allow_pickle=True); dates=Z['dates']; mk20=Z['mk20']; cand=Z['cand']; fn=list(Z['fnames'])
F={k:Z['F_'+k] for k in fn}; Dsel=Z['Dsel']
ep=np.zeros(len(Dsel),int)
for i in range(1,len(Dsel)): ep[i]=ep[i-1]+(1 if Dsel[i]-Dsel[i-1]>5 else 0)
PER={'2020-22':('2020-01-01','2022-12-31'),'2023-24':('2023-01-01','2024-12-31'),'2025-26':('2025-01-01','2026-12-31')}
pm={k:(dates>=a)&(dates<=b) for k,(a,b) in PER.items()}
def rank(x): return np.argsort(np.argsort(x)).astype(np.float64)
def daily(fv,net,sub=None):
    ic=np.full(len(Dsel),np.nan); sp=np.full(len(Dsel),np.nan)
    for i in range(len(Dsel)):
        m=cand[i]&np.isfinite(fv[i])&np.isfinite(net[i])
        if m.sum()<300: continue
        f=fv[i][m]; y=net[i][m]; rf=rank(f); ry=rank(y)
        ic[i]=np.corrcoef(rf,ry)[0,1]
        q=len(f)//5; o=np.argsort(f); sp[i]=y[o[-q:]].mean()-y[o[:q]].mean()
    return ic,sp
def by_ep(x,msk):
    ids=np.unique(ep[msk&np.isfinite(x)]); v=np.array([np.nanmean(x[msk&(ep==k)]) for k in ids]); return v
def stat(v):
    if len(v)<3: return (np.nan,np.nan,np.nan,len(v))
    return v.mean(), v.mean()/(v.std(ddof=1)/np.sqrt(len(v))+1e-12), (v>0).mean(), len(v)
res={}
for H in (20,10):
    net=Z[f'net{H}']
    print(f'\n######## H={H} 天  因子排名IC（Spearman，对未来{H}天净收益）与五分位差(最高20%-最低20%, bp)；按“段”聚合：均值 / t / 正段比例')
    print(f'{"因子":22s}'+''.join(f'| {p:^36s}' for p in PER))
    for f in fn:
        ic,sp=daily(F[f],net); res[(H,f)]=(ic,sp); cells=[]
        for p in PER:
            a=stat(by_ep(ic,pm[p])); b=by_ep(sp,pm[p])
            cells.append(f'IC{a[0]:+.3f} t{a[1]:+.1f} 正{a[2]*100:3.0f}%({a[3]}段) 差{b.mean()*1e4:+5.0f}')
        print(f'{f:22s}| '+' | '.join(cells))
np.save('pp_res.npy',res,allow_pickle=True)
