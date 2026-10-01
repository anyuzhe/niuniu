import numpy as np, warnings; warnings.filterwarnings('ignore')
import etfpanic_bt as B
from etfpanic_bt import *
M=np.load('mkreg.npz'); md2=dict(zip(M['dates'],M['mret'])); mretd=np.array([md2.get(d,0.0) for d in dates])
idx=np.cumprod(1+mretd)
def mkN(n):
    o=np.full(nd,np.nan); o[n:]=idx[n:]/idx[:-n]-1; o[~np.isfinite(B.mk)]=np.nan; return o
mk20=B.mk.copy(); mk10=mkN(10)
y=(dates>='2020-01-01')&(dates<='2022-12-31')
print('2020-22 mk10 分位 5/10/20/30%:',[round(np.nanpercentile(mk10[y],q)*100,1) for q in (5,10,20,30)],'  mk20 分位:',[round(np.nanpercentile(mk20[y],q)*100,1) for q in (5,10,20,30)])
def fwd(d,H):
    r=[]
    for j in bj:
        e=d+1; x=e+H-1
        if x>LASTMK or not buyable[d,j] or not np.isfinite(TRO[e,j]) or not np.isfinite(TRC[x,j]): continue
        r.append(TRC[x,j]*(1-TICK/C[x,j])*(1-FEE1)/(TRO[e,j]*(1+TICK/O[e,j])*(1+FEE1))-1)
    return np.mean(r) if r else np.nan
F={H:np.array([fwd(d,H) if d+1<nd else np.nan for d in range(nd)]) for H in (5,10,20)}
def ep(m): return 1+int((np.diff(np.nonzero(m)[0])>5).sum()) if m.sum() else 0
print('\n=== 事件研究：信号=全市场等权N日跌幅 <= 阈值；篮子次日开盘买，持有H天（扣成本）。平均bp / 胜率 / 天数(段数)；三段 2020-22 | 2023-24 | 2025-26 | 全期')
for N,mkk in ((10,mk10),(20,mk20)):
    for thr in (-0.03,-0.05,-0.07,-0.09,-0.12):
        for H in (10,20):
            fw=F[H]; cells=[]
            for pn,(a,b) in list(PER.items())+[('全期',('2019-06-01','2026-12-31'))]:
                m=(dates>=a)&(dates<=b)&np.isfinite(fw)&np.isfinite(mkk)&(mkk<=thr)
                cells.append('无' if m.sum()==0 else f'{fw[m].mean()*1e4:+5.0f}/{(fw[m]>0).mean()*100:3.0f}%/{m.sum():3d}天({ep(m)})')
            print(f'{N}日跌幅<={thr*100:.0f}% 持{H}天 | '+' | '.join(cells))
base_ref={H:np.nanmean(F[H][(np.isfinite(F[H]))&(dates>='2020-01-01')]) for H in (10,20)}
print('无条件平均(2020起): 持10天 %+.0fbp 持20天 %+.0fbp'%(base_ref[10]*1e4,base_ref[20]*1e4))
def line(tag,eq,ex,tr):
    cells=[]
    for pn,(a,b) in PER.items():
        tot,cagr,vol,sh,dd,e_=metrics(eq,ex,a,b); cells.append(f'{cagr*100:+5.1f}/{dd*100:5.1f}')
    tot,cagr,vol,sh,dd,e_=metrics(eq,ex,'2019-06-01','2026-12-31')
    print(f'{tag:26s} | {" | ".join(cells)} | 全期 年化{cagr*100:+5.1f}% 夏普{sh:+.2f} 回撤{dd*100:5.1f}% 仓位{e_*100:3.0f}% 笔数{len(tr)}')
print('\n=== 组合回测（一次性，闲置0息）年化%/最大回撤%：2020-22 | 2023-24 | 2025-26 | 全期')
for N,mkk in ((10,mk10),(20,mk20)):
    B.mk=mkk
    for thr in (-0.05,-0.07,-0.09,-0.12):
        for H in (10,20):
            eq,ex,tr=B.simulate(dict(H=H,thr=thr,tiers=[(None,1.0,False)],maxact=1)); line(f'{N}日<={thr*100:.0f}% 持{H}天',eq,ex,tr)
B.mk=mk10
print('\n2026 年交易(10日<=-7%/持10天 与 10日<=-9%/持10天)')
for thr in (-0.07,-0.09):
    eq,ex,tr=B.simulate(dict(H=10,thr=thr,tiers=[(None,1.0,False)],maxact=1))
    for t in tr:
        if dates[t['e']]>='2026': print(f"  thr{thr*100:.0f}% 买入{dates[t['e']]} mk10={mk10[t['e']-1]*100:.1f}% 净{(t.get('proc',0)/t['cost']-1)*100:+.1f}%")
