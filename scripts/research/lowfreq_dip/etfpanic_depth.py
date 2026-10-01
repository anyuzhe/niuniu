import numpy as np, warnings; warnings.filterwarnings('ignore')
from etfpanic_bt import *
def line(tag,eq,ex,tr=None):
    cells=[]
    for pn,(a,b) in PER.items():
        tot,cagr,vol,sh,dd,e_=metrics(eq,ex,a,b); cells.append(f'{cagr*100:+5.1f}/{dd*100:5.1f}')
    tot,cagr,vol,sh,dd,e_=metrics(eq,ex,'2019-06-01','2026-12-31')
    print(f'{tag:30s} | {" | ".join(cells)} | 全期 年化{cagr*100:+5.1f}% 夏普{sh:+.2f} 回撤{dd*100:5.1f}% 仓位{e_*100:3.0f}% 批数{len(tr)}')
# ---- event study: basket EW, buy open d+1, hold 20 days close, costs
H=20; cost=2*(FEE1+TICK/1.0*0)  # use per-ETF tick
def basket_fwd(d,H=20):
    r=[]
    for j in bj:
        e=d+1; x=e+H-1
        if x>LASTMK or not(buyable[d,j]) or not np.isfinite(TRO[e,j]) or not np.isfinite(TRC[x,j]): continue
        buy=TRO[e,j]*(1+TICK/O[e,j])*(1+FEE1); sell=TRC[x,j]*(1-TICK/C[x,j])*(1-FEE1); r.append(sell/buy-1)
    return np.mean(r) if r else np.nan
fw=np.array([basket_fwd(d) if d+1<nd else np.nan for d in range(nd)])
valid=np.isfinite(fw)&np.isfinite(mk)
print('事件研究：宽基篮子（6只等权）恐慌日次日开盘买、持有20天收盘卖，扣佣金1bp+每边1个价位（0.001元）')
bk=[('浅 (-6%,-3.6%]',-0.06,-0.036),('中 (-9%,-6%]',-0.09,-0.06),('深 <=-9%',-0.5,-0.09),('极深 <=-12%',-0.5,-0.12),('全部 <=-3.6%',-0.5,-0.036),('非恐慌',-0.036,9)]
for pn,(a,b) in list(PER.items())+[('全期',('2019-06-01','2026-12-31'))]:
    mp=(dates>=a)&(dates<=b)&valid
    print('\n'+pn)
    for nm,lo,hi in bk:
        m=mp&(mk>lo)&(mk<=hi) if nm!='非恐慌' else mp&(mk>-0.036)
        if m.sum()==0: print(f'   {nm:14s} 无'); continue
        x=fw[m]; ep=1+int((np.diff(np.nonzero(m)[0])>5).sum())
        print(f'   {nm:14s} n={m.sum():3d}天/约{ep}段 平均{x.mean()*1e4:+5.0f}bp 中位{np.median(x)*1e4:+5.0f} 胜率{(x>0).mean()*100:3.0f}% 最差{x.min()*100:+.1f}% 最好{x.max()*100:+.1f}%')
print('\n=== 2026 年各恐慌段（信号日首日、最深日）篮子20天收益（扣成本；未满20天标*） ===')
d26=np.nonzero(np.char.startswith(dates,'2026')&(mk<=-0.036))[0]
segs=[[d26[0]]]
for i in d26[1:]: (segs[-1].append(i) if i-segs[-1][-1]<=5 else segs.append([i]))
for s in segs:
    deep=s[int(np.argmin(mk[s]))]; f=lambda d: fw[d] if np.isfinite(fw[d]) else np.nan
    allf=np.array([fw[d] for d in s]); print(f'{dates[s[0]]}~{dates[s[-1]]} 首日买{f(s[0])*1e4:+.0f}bp 最深日({dates[deep]},{mk[deep]*100:.1f}%)买{f(deep)*1e4:+.0f}bp 全段信号日平均{np.nanmean(allf)*1e4:+.0f}bp（可算{int(np.isfinite(allf).sum())}/{len(s)}天）')
# ---- portfolios by threshold
print('\n格式：年化% / 最大回撤%；2020-22 | 2023-24 | 2025-26 | 全期；现金0息')
for th in (-0.036,-0.06,-0.09,-0.12):
    for H in (20,40):
        for N in (1,3):
            c=dict(H=H,thr=th,tiers=[(None,1.0/N,False)],maxact=N); eq,ex,tr=simulate(c); line(f'thr{th*100:.1f}% H{H} 分{N}批',eq,ex,tr)
# deep-only tiered: add on deeper
c=dict(H=20,tiers=[(-0.09,1/3,True),(-0.12,1/3,True),(-0.15,1/3,True)]); eq,ex,tr=simulate(c); line('深度加仓 -9/-12/-15%',eq,ex,tr)
rb=np.nanmean(rcc[:,bj],axis=1); bh=np.cumprod(1+np.r_[0,rb[1:]]); line('参照 篮子买入持有(不计成本)',bh,np.ones(nd),[])
