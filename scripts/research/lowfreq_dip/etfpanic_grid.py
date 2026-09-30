import numpy as np, warnings; warnings.filterwarnings('ignore')
from etfpanic_bt import *
def line(tag,eq,ex,tr=None):
    cells=[]
    for pn,(a,b) in PER.items():
        tot,cagr,vol,sh,dd,e_=metrics(eq,ex,a,b); cells.append(f'{cagr*100:+5.1f}/{dd*100:5.1f}')
    tot,cagr,vol,sh,dd,e_=metrics(eq,ex,'2019-06-01','2026-12-31')
    n=sum(1 for t in tr) if tr is not None else 0
    print(f'{tag:34s} | {" | ".join(cells)} | 全期 年化{cagr*100:+5.1f}% 夏普{sh:+.2f} 回撤{dd*100:5.1f}% 仓位{e_*100:3.0f}% 批数{n}')
print('格式：年化收益% / 最大回撤%；顺序 2020-22 | 2023-24 | 2025-26 | 全期（现金收益按0计）')
base=dict(H=20,thr=-0.036,tiers=[(None,1/3,False)],maxact=3)
def cfg(**kw): c=dict(base); c.update(kw); return c
def run(tag,c,**kw): eq,ex,tr=simulate(c,**kw); line(tag,eq,ex,tr); return eq,ex,tr
print('\n-- 基准配置：分3批、阈值-3.6%、持有20天 --'); run('分3批 H=20 thr=-3.6%',cfg())
print('\n-- 阈值（分3批，H=20）--')
for th in (-0.025,-0.03,-0.036,-0.045,-0.06): run(f'阈值 {th*100:.1f}%',cfg(thr=th))
print('\n-- 持有天数（分3批，thr=-3.6%）--')
for H in (10,15,20,30,40): run(f'持有 {H} 天',cfg(H=H))
print('\n-- 批数（H=20）--')
run('一次性(1批)',cfg(tiers=[(None,1.0,False)],maxact=1))
for N in (2,3,5,8): run(f'分{N}批',cfg(tiers=[(None,1.0/N,False)],maxact=N))
print('\n-- 退出方式（分3批，H=30 上限）--')
run('只按时间 H=30',cfg(H=30))
for rc in (0.0,0.02): run(f'大盘20日涨跌回到≥{rc*100:.0f}%就走(H=30上限)',cfg(H=30,rec=rc))
for st in (0.06,0.08,0.12): run(f'单批亏{st*100:.0f}%止损(H=20)',cfg(stop=st))
print('\n-- 仓位上限（分3批）--')
for me in (1.0,0.7,0.5): run(f'最大仓位 {me*100:.0f}%',cfg(maxexp=me))
print('\n-- 标的（分3批）--')
for nm,bk in (('仅沪深300 510300',['sh.510300']),('仅中证500 510500',['sh.510500']),('仅创业板 159915',['sz.159915']),('仅中证1000 512100',['sh.512100']),('仅50ETF 510050',['sh.510050'])): run(nm,cfg(),basket=bk)
print('\n-- 阈值随时间滚动（只用当时已有的数据：过去所有日子的20%分位，前一年用-3.6%）--')
ths=np.full(nd,-0.036)
for d in range(260,nd):
    h=mk[:d][np.isfinite(mk[:d])]; ths[d]=np.percentile(h,20)
run('滚动20%分位阈值',cfg(),thr_series=ths)
print('  滚动阈值区间:',f'{np.nanmin(ths[260:LASTMK])*100:.1f}% ~ {np.nanmax(ths[260:LASTMK])*100:.1f}%')
