import numpy as np, warnings; warnings.filterwarnings('ignore')
import etfpanic_bt_ext as B
from etfpanic_bt_ext import *
M=np.load('mkreg_ext_liq.npz'); md=dict(zip(M['dates'],M['mret'])); mr=np.array([md.get(d,0.0) for d in dates]); idx=np.cumprod(1+mr)
mk20=B.mk
def fwd(d,H=20):
    r=[]
    for j in bj:
        e=d+1; x=e+H-1
        if x>LASTMK or e>=nd or not buyable[d,j] or not np.isfinite(TRO[e,j]) or not np.isfinite(TRC[x,j]): continue
        r.append(TRC[x,j]*(1-TICK/C[x,j])*(1-FEE1)/(TRO[e,j]*(1+TICK/O[e,j])*(1+FEE1))-1)
    return np.mean(r) if r else np.nan
F=np.array([fwd(d) if d+1<nd else np.nan for d in range(nd)])
def rmean(a,n):
    c=np.cumsum(np.nan_to_num(a)); o=np.full(nd,np.nan); o[n-1:]=(c[n-1:]-np.r_[0,c[:-n]])/n; return o
ma250=rmean(idx,250); trend=idx/ma250-1
mx250=np.array([idx[max(0,i-249):i+1].max() for i in range(nd)]); dd250=idx/mx250-1
ret120=np.full(nd,np.nan); ret120[120:]=idx[120:]/idx[:-120]-1
deepcnt=np.array([((mk20[max(0,i-60):i]<=-0.09)).sum() for i in range(nd)])  # deep days in previous 60 days
vol20=np.full(nd,np.nan)
for i in range(20,nd): vol20[i]=mr[i-19:i+1].std()*np.sqrt(245)
yrs=np.array([d[:4] for d in dates]); base=np.isfinite(F)&np.isfinite(mk20)&np.isfinite(ma250)
deep=base&(mk20<=-0.09)
def seg(m): return 1+int((np.diff(np.nonzero(m)[0])>5).sum()) if m.sum() else 0
def row(tag,m):
    if m.sum()<3: print(f'  {tag:34s} 无'); return
    x=F[m]; print(f'  {tag:34s} n={m.sum():3d}天/{seg(m):2d}段 20天均值{x.mean()*1e4:+5.0f}bp 中位{np.median(x)*1e4:+5.0f} 胜率{(x>0).mean()*100:3.0f}% 最差{x.min()*100:+.0f}%')
print('=== 每年：大盘(等权)年度涨跌、年末相对250日均线、深度恐慌天数及其后20天ETF篮子均值')
for y in sorted(set(yrs)):
    m=(yrs==y); i0=np.nonzero(m)[0][0]; i1=np.nonzero(m)[0][-1]
    yr=idx[i1]/idx[max(i0-1,0)]-1; md_=deep&m
    s=f'{y}: 大盘{yr*100:+6.1f}% 年内最大回撤{(idx[m]/np.maximum.accumulate(idx[m])-1).min()*100:6.1f}% 深度恐慌{md_.sum():3d}天'
    if md_.sum()>=3: s+=f' 其后20天均值{F[md_].mean()*1e4:+5.0f}bp 胜率{(F[md_]>0).mean()*100:3.0f}%'
    print(s)
print('\n=== 深度恐慌日(20日<=-9%)按“大盘所处的位置”分层（全期2008-2026）')
for nm,m in (('大盘在250日均线之上',trend>0),('大盘在250日均线之下',trend<=0),('离250日高点跌幅<20%',dd250>-0.20),('离250日高点跌幅20%-35%',(dd250<=-0.20)&(dd250>-0.35)),('离250日高点跌幅>35%',dd250<=-0.35),
   ('前120日大盘涨幅>+20%(牛市中)',ret120>0.20),('前120日大盘涨幅-10%~+20%',(ret120<=0.20)&(ret120>-0.10)),('前120日大盘跌幅>10%',ret120<=-0.10),
   ('前60天内已有>=20个深度恐慌日(连环下跌)',deepcnt>=20),('前60天内深度恐慌日<20',deepcnt<20)):
    row(nm,deep&m)
print('\n=== 同样分层，分两个时期：2007-2011 | 2012-2026')
for nm,m in (('250日均线之上',trend>0),('250日均线之下',trend<=0),('离高点跌幅>35%',dd250<=-0.35),('离高点跌幅<20%',dd250>-0.20),('前60天已有>=20个深度恐慌日',deepcnt>=20),('前60天<20个',deepcnt<20)):
    for pn,(a,b) in (('2007-11',('2007-01-01','2011-12-31')),('2012-26',('2012-01-01','2026-12-31'))):
        row(f'{nm} | {pn}',deep&m&(dates>=a)&(dates<=b))
print('\n=== 2007-11 与 2012-26 的深度恐慌日特征均值')
for pn,(a,b) in (('2007-11',('2007-01-01','2011-12-31')),('2012-26',('2012-01-01','2026-12-31')),('2020-26',('2020-01-01','2026-12-31'))):
    m=deep&(dates>=a)&(dates<=b); print(f'  {pn}: n={m.sum()}  相对250日均线{trend[m].mean()*100:+.1f}%  距250日高点{dd250[m].mean()*100:.1f}%  前120日涨幅{np.nanmean(ret120[m])*100:+.1f}%  已有深度日数(前60天){deepcnt[m].mean():.1f}  20日实现波动{np.nanmean(vol20[m])*100:.0f}%  事后20天大盘EW涨跌{np.nanmean([idx[min(i+20,nd-1)]/idx[i]-1 for i in np.nonzero(m)[0]])*100:+.1f}%')
# next-20d: continuation: after deep day, how often did market make a further >=5% decline within the following 20 days
print('\n=== 深度恐慌日之后20天内，大盘等权是否还会再跌>=5%（最大回撤）')
for pn,(a,b) in (('2007-11',('2007-01-01','2011-12-31')),('2012-19',('2012-01-01','2019-12-31')),('2020-26',('2020-01-01','2026-12-31'))):
    m=deep&(dates>=a)&(dates<=b); ii=np.nonzero(m)[0]; mdd=[]; 
    for i in ii:
        w=idx[i+1:i+21]/idx[i]-1; mdd.append(w.min() if len(w) else np.nan)
    mdd=np.array(mdd); print(f'  {pn}: 平均最大再下跌{np.nanmean(mdd)*100:.1f}% 再跌>=5%的比例{np.nanmean(mdd<=-0.05)*100:.0f}% 再跌>=10%的比例{np.nanmean(mdd<=-0.10)*100:.0f}%')
