import numpy as np, warnings; warnings.filterwarnings('ignore')
import etfpanic_bt_ext as B
from etfpanic_bt_ext import *
M=np.load('mkreg_ext_liq.npz'); md=dict(zip(M['dates'],M['mret'])); mr=np.array([md.get(d,0.0) for d in dates]); idx=np.cumprod(1+mr)
def mkN(n): o=np.full(nd,np.nan); o[n:]=idx[n:]/idx[:-n]-1; return o
mk20=B.mk; mk3=mkN(3); mk5=mkN(5)
def fwd(d,H=20):
    r=[]
    for j in bj:
        e=d+1; x=e+H-1
        if x>LASTMK or e>=nd or not buyable[d,j] or not np.isfinite(TRO[e,j]) or not np.isfinite(TRC[x,j]): continue
        r.append(TRC[x,j]*(1-TICK/C[x,j])*(1-FEE1)/(TRO[e,j]*(1+TICK/O[e,j])*(1+FEE1))-1)
    return np.mean(r) if r else np.nan
F=np.array([fwd(d) if d+1<nd else np.nan for d in range(nd)])
ERA={'2007-11':('2007-01-01','2011-12-31'),'2012-16':('2012-01-01','2016-12-31'),'2017-19':('2017-01-01','2019-12-31'),'2020-26':('2020-01-01','2026-12-31'),'全期':('2007-01-01','2026-12-31')}
base=np.isfinite(F)&np.isfinite(mk20)
first=np.zeros(nd,bool); last=-99
for d in np.nonzero(base&(mk20<=-0.09))[0]:
    if d-last>10: first[d]=True
    last=d
conds={'A 20日<=-9%(所有天)':mk20<=-0.09,'B 每段第一天':first,
 'C <=-9% 且 3日反弹>=+1%':(mk20<=-0.09)&(mk3>=0.01),'D <=-9% 且 3日仍在跌<=-1%':(mk20<=-0.09)&(mk3<=-0.01),
 'E <=-12% 且 3日反弹>=+1%':(mk20<=-0.12)&(mk3>=0.01),'F <=-9% 且 5日反弹>=+2%':(mk20<=-0.09)&(mk5>=0.02),
 'G <=-15%(所有天)':mk20<=-0.15,'H 非恐慌':mk20>-0.036}
print('宽基ETF篮子 次日开盘买持有20天(扣成本)：平均bp / 胜率 / 天数(段数) / 最差')
for cn,cm in conds.items():
    cells=[]
    for pn,(a,b) in ERA.items():
        m=base&cm&(dates>=a)&(dates<=b)
        if m.sum()<3: cells.append('   无   '); continue
        x=F[m]; ep=1+int((np.diff(np.nonzero(m)[0])>5).sum()); cells.append(f'{x.mean()*1e4:+5.0f}/{(x>0).mean()*100:3.0f}%/{m.sum():3d}({ep:2d})/{x.min()*100:+.0f}%')
    print(f'{cn:24s}| '+' | '.join(cells))
print('列：'+' | '.join(ERA))
