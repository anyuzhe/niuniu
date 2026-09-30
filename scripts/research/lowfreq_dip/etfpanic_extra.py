import numpy as np, warnings; warnings.filterwarnings('ignore')
import etfpanic_bt as B
from etfpanic_bt import *
cfg=dict(H=20,thr=-0.036,tiers=[(None,1/3,False)],maxact=3)
def line(tag,eq,ex):
    cells=[]
    for pn,(a,b) in PER.items():
        tot,cagr,vol,sh,dd,e_=metrics(eq,ex,a,b); cells.append(f'{cagr*100:+5.1f}/{dd*100:5.1f}')
    tot,cagr,vol,sh,dd,e_=metrics(eq,ex,'2019-06-01','2026-12-31')
    print(f'{tag:40s} | {" | ".join(cells)} | 全期 年化{cagr*100:+5.1f}% 夏普{sh:+.2f} 回撤{dd*100:5.1f}% 仓位{e_*100:3.0f}%')
eq,ex,tr=simulate(cfg); line('基准：分3批 H=20（现金收益0）',eq,ex)
for cy_ in (0.015,0.02,0.025):
    r=np.r_[0,eq[1:]/eq[:-1]-1]; r2=r+(1-np.r_[0,ex[:-1]])*(cy_/245); eq2=np.cumprod(1+r2)
    line(f'  闲置资金年化{cy_*100:.1f}%',eq2,ex)
# alternative signal: the ETF basket's own 20-day return (no stock universe needed)
rb=np.nanmean(rcc[:,bj],axis=1); idx=np.cumprod(1+rb); alt=idx/np.r_[np.full(20,np.nan),idx[:-20]]-1; alt[LASTMK+1:]=np.nan
tr_=(dates>='2020-01-01')&(dates<='2022-12-31'); cut=np.nanpercentile(alt[tr_&np.isfinite(alt)],20)
print(f'\n信号换成宽基ETF篮子自己的20日涨跌（2020–22年最低20%分位 = {cut*100:.1f}%）：')
B.mk=alt
c=dict(cfg); c['thr']=cut; eq3,ex3,_=B.simulate(c); line('  ETF篮子20日涨跌 ≤ 阈值，分3批',eq3,ex3)
B.mk=np.array([md.get(d,np.nan) for d in dates])
