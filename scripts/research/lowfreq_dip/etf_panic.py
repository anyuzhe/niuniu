import numpy as np, warnings; warnings.filterwarnings('ignore')
from etfcore import *
M=np.load('mkreg.npz'); md=dict(zip(M['dates'],M['mk20'])); CUT=-0.036
mk=np.array([md.get(d,np.nan) for d in dates]); reg=mk<=CUT
T=np.arange(nd); jj=np.arange(nc)[None,:]; catarr=np.array([cat[s] for s in syms])
def ret_after(Hd):
    ei=np.tile(np.minimum(T+Hd,nd-1)[:,None],(1,nc)); okx=(T+Hd<nd)
    for _ in range(3):
        bad=~fin[ei,jj]|limdn_close[ei,jj]; ei=np.where(bad&(ei<nd-1),ei+1,ei)
    exC=C[ei,jj]; enO=np.full((nd,nc),np.nan); enO[:-1]=O[1:]
    buy_ok=np.zeros((nd,nc),bool); buy_ok[:-1]=fin[1:]&~limup_open[1:]
    winbad=(badc[np.minimum(ei,nd-1),jj]-badc[np.maximum(T-1,0)[:,None],jj])>0
    valid=uni&buy_ok&okx[:,None]&np.isfinite(exC)&np.isfinite(enO)&~winbad
    net=(exC-0.001)/(enO+0.001)-1-FEE
    return valid,net
mon=np.array([d[:7] for d in dates])
def tstat(x,m):
    um=np.unique(mon[m]); mm=np.array([x[m&(mon==u)].mean() for u in um]); return mm.mean()*1e4, mm.mean()/(mm.std(ddof=1)/np.sqrt(len(mm))+1e-12), len(um)
per={'2020-22':('2020-01-01','2022-12-31'),'2023-24':('2023-01-01','2024-12-31'),'2025-26':('2025-01-01','2026-12-31')}
px=C>=1.5
for nm,cm in (('宽基ETF（价格≥1.5元）',(catarr=='broad')[None,:]&px),('全部选中ETF（价格≥1.5元）',np.ones((1,nc),bool)&px)):
    print('###',nm)
    for Hd in (10,20):
        valid,net=ret_after(Hd); v=valid&cm
        dm=np.where(v.sum(1)>=1,np.nanmean(np.where(v,net,np.nan),1),np.nan)
        print(f'  持有{Hd}天（次日开盘买，含佣金2bp+每边1个价位）：恐慌日 vs 非恐慌日 的等权平均净收益')
        for pn,(a,b) in per.items():
            dmask=(dates>=a)&(dates<=b)&np.isfinite(dm)
            r=dmask&reg; n_=dmask&~reg&np.isfinite(mk)
            if r.sum()<10: print(f'    {pn}: 恐慌日 {r.sum()} 天，样本不足'); continue
            a1,t1,_=tstat(dm,r); a2,t2,_=tstat(dm,n_)
            print(f'    {pn}: 恐慌日{r.sum():3d}天 {a1:+5.0f}bp(t{t1:+.1f}) | 非恐慌日{n_.sum():3d}天 {a2:+5.0f}bp(t{t2:+.1f})')
