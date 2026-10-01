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
def rstd(a,n):
    o=np.full(nd,np.nan)
    for i in range(n-1,nd): o[i]=np.nanstd(a[i-n+1:i+1],ddof=1)
    return o
def rmean(a,n):
    o=np.full(nd,np.nan)
    for i in range(n-1,nd): o[i]=np.nanmean(a[i-n+1:i+1])
    return o
sd60=rstd(mr,60); zvol=mk20/(sd60*np.sqrt(20))
pct=np.full(nd,np.nan)
for i in range(250,nd):
    w=mk20[max(0,i-750):i]; w=w[np.isfinite(w)]
    if len(w)>=200 and np.isfinite(mk20[i]): pct[i]=(w<=mk20[i]).mean()
ma20=rmean(idx,20); sdp=rstd(idx,20); zb=(idx-ma20)/sdp
def sh(a,k): o=np.full(nd,np.nan); o[k:]=a[:-k]; return o
below=zb<=-2
R1=(sh(zb,1)<-2)&(zb>=-2)&(idx>sh(idx,1))
minz5=np.array([np.nanmin(zb[max(0,i-5):i+1]) if i>=5 else np.nan for i in range(nd)])
R2=(minz5<-2)&(zb>=-2)&~(sh(zb,1)>=-2)|(R1)
minzv5=np.array([np.nanmin(zvol[max(0,i-5):i+1]) if i>=5 else np.nan for i in range(nd)])
minmk5=np.array([np.nanmin(mk20[max(0,i-5):i+1]) if i>=5 else np.nan for i in range(nd)])
SIG={'S0 固定 20日<=-9%':mk20<=-0.09,
 'S1 动态 20日跌幅/(60日波动×√20)<=-1.5':zvol<=-1.5,'S2 动态 <=-2':zvol<=-2,'S3 动态 <=-2.5':zvol<=-2.5,
 'S4 动态 20日跌幅在近3年最低3%分位':pct<=0.03,'S5 近3年最低5%分位':pct<=0.05,
 'S6 大盘收盘在布林下轨之下(20日,2σ)':below,
 'S7 超跌后收复下轨(昨在轨下,今收回且收阳)':R1,
 'S8 近5日曾破下轨,今收回(首次)':R1|((minz5<-2)&(zb>=-2)&(sh(zb,1)<-2)),
 'S9 收复下轨 且 近5日动态<=-1.5':R1&(minzv5<=-1.5),
 'S10 收复下轨 且 近5日动态<=-2':R1&(minzv5<=-2),
 'S11 收复下轨 且 近5日20日跌幅曾<=-6%':R1&(minmk5<=-0.06),
 'S12 收复下轨 且 近5日20日跌幅曾<=-9%':R1&(minmk5<=-0.09)}
ERA={'2008-11':('2008-01-01','2011-12-31'),'2012-16':('2012-01-01','2016-12-31'),'2017-19':('2017-01-01','2019-12-31'),'2020-26':('2020-01-01','2026-12-31'),'全期':('2008-01-01','2026-12-31')}
ok=np.isfinite(F)&(dates>='2008-01-01')
def ep(m): return 1+int((np.diff(np.nonzero(m)[0])>5).sum()) if m.sum() else 0
print('无条件(2008起)：20天均值 %+.0fbp 胜率 %.0f%%'%(F[ok].mean()*1e4,(F[ok]>0).mean()*100))
print('\n事件研究(所有信号日)：ETF篮子次日开盘买持有20天，扣成本。格式 均值bp/胜率/天(段)；列=%s'%' | '.join(ERA))
for nm,s in SIG.items():
    cells=[]
    for pn,(a,b) in ERA.items():
        m=ok&s&(dates>=a)&(dates<=b)
        cells.append('   无    ' if m.sum()<3 else f'{F[m].mean()*1e4:+5.0f}/{(F[m]>0).mean()*100:3.0f}%/{m.sum():3d}({ep(m):2d})')
    print(f'{nm:40s}| '+' | '.join(cells))
print('\n可执行规则(空仓时第一个信号日次日买、持有20天)：笔数/平均/胜率/最差；全期年化(总资金,闲置0息)')
for nm,s in SIG.items():
    cells=[]; pos_end=-1; tr=[]
    for d in np.nonzero(ok&s)[0]:
        if d>pos_end: tr.append((d,F[d])); pos_end=d+1+19
    for pn,(a,b) in ERA.items():
        t=[r for d,r in tr if a<=dates[d]<=b]
        cells.append('  无  ' if not t else f'{len(t):2d}笔{np.mean(t)*100:+5.1f}%/{np.mean(np.array(t)>0)*100:3.0f}%/{np.min(t)*100:+.0f}%')
    r=np.array([r for d,r in tr]); yrs=(len(dates[(dates>='2008-01-01')])/245)
    ann=(np.prod(1+r)**(1/yrs)-1)*100 if len(r) else np.nan
    cum=np.cumprod(1+r); mdd=(cum/np.maximum.accumulate(cum)-1).min()*100 if len(r) else np.nan
    print(f'{nm:40s}| '+' | '.join(cells)+f' | 全期年化{ann:+.1f}% 平仓净值回撤{mdd:.0f}%')
print('列：'+' | '.join(ERA))
np.savez('etfpanic_dyn_sig.npz',dates=dates,zvol=zvol,pct=pct,zb=zb,R1=R1,F=F)
