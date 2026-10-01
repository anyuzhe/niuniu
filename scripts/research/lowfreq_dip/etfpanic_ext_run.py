import numpy as np, warnings; warnings.filterwarnings('ignore')
import etfpanic_bt_ext as B
from etfpanic_bt_ext import *
print('ETF日历',dates[0],dates[-1],nd,'LASTMK',dates[LASTMK])
ERA={'2007-11':('2007-01-01','2011-12-31'),'2012-16':('2012-01-01','2016-12-31'),'2017-19':('2017-01-01','2019-12-31'),'2020-22':('2020-01-01','2022-12-31'),'2023-24':('2023-01-01','2024-12-31'),'2025-26':('2025-01-01','2026-12-31')}
def fwd(d,H):
    r=[]
    for j in bj:
        e=d+1; x=e+H-1
        if x>LASTMK or e>=nd or not buyable[d,j] or not np.isfinite(TRO[e,j]) or not np.isfinite(TRC[x,j]): continue
        r.append(TRC[x,j]*(1-TICK/C[x,j])*(1-FEE1)/(TRO[e,j]*(1+TICK/O[e,j])*(1+FEE1))-1)
    return np.mean(r) if r else np.nan
F={H:np.array([fwd(d,H) if d+1<nd else np.nan for d in range(nd)]) for H in (10,20)}
nb=np.array([sum(1 for j in bj if buyable[d,j]) for d in range(nd)])
print('可买入的篮子成分数(年初):',{y:int(nb[np.nonzero(np.char.startswith(dates,y))[0][0]]) for y in ('2007','2009','2011','2012','2013','2015','2017','2019')})
mk=B.mk
def ep(m): return 1+int((np.diff(np.nonzero(m)[0])>5).sum()) if m.sum() else 0
print('\n事件研究：等权20日跌幅分层，宽基ETF篮子(可买的成分)次日开盘买持有20天，扣成本；平均bp/胜率/天(段)')
bk=[('浅(-6,-3.6]',-0.06,-0.036),('中(-9,-6]',-0.09,-0.06),('深<=-9%',-0.5,-0.09),('极深<=-12%',-0.5,-0.12),('非恐慌',-0.036,9)]
for pn,(a,b) in list(ERA.items())+[('全期',('2007-01-01','2026-12-31'))]:
    print('\n'+pn)
    mp=(dates>=a)&(dates<=b)&np.isfinite(F[20])&np.isfinite(mk)&(nb>0)
    for nm,lo,hi in bk:
        m=mp&(mk>lo)&(mk<=hi) if nm!='非恐慌' else mp&(mk>-0.036)
        if m.sum()==0: print(f'   {nm:12s} 无'); continue
        x=F[20][m]; print(f'   {nm:12s} n={m.sum():3d}天/约{ep(m):2d}段 20天均值{x.mean()*1e4:+5.0f}bp 中位{np.median(x)*1e4:+5.0f} 胜率{(x>0).mean()*100:3.0f}% 最差{x.min()*100:+.1f}% 最好{x.max()*100:+.1f}%')
print('\n=== 一次性建仓逐笔(20日<=-9%，空仓时买入，持有20天)')
for th,H in ((-0.09,20),(-0.12,40),(-0.09,10)):
    eq,ex,tr=B.simulate(dict(H=H,thr=th,tiers=[(None,1.0,False)],maxact=1))
    rows=[(dates[t['e']],mk[t['e']-1],(t.get('proc',0)/t['cost']-1) if t.get('closed') else np.nan) for t in tr]
    v=np.array([r[2] for r in rows]); ok=np.isfinite(v)
    print(f'\n阈值{th*100:.0f}% 持{H}天：{len(rows)}笔 平均{np.nanmean(v)*100:+.1f}% 胜率{(v[ok]>0).mean()*100:.0f}% 最差{np.nanmin(v)*100:+.1f}% 最好{np.nanmax(v)*100:+.1f}%')
    if th==-0.09 and H==20:
        for r in rows: print(f'  {r[0]} 大盘20日{r[1]*100:.1f}% 净{r[2]*100:+.1f}%')
    for pn,(a,b) in ERA.items():
        s=[r[2] for r in rows if a<=r[0]<=b and np.isfinite(r[2])]
        if s: print(f'   {pn}: {len(s)}笔 平均{np.mean(s)*100:+.1f}% 胜率{np.mean(np.array(s)>0)*100:.0f}%')
    # portfolio metrics full & eras
    out=[]
    for pn,(a,b) in list(ERA.items())+[('全期',('2007-01-01','2026-12-31'))]:
        try:
            tot,cagr,vol,sh,dd,e_=metrics(eq,ex,a,b); out.append(f'{pn}: 年化{cagr*100:+5.1f}% 夏普{sh:+.2f} 回撤{dd*100:5.1f}% 仓位{e_*100:3.0f}%')
        except Exception as e_: out.append(f'{pn}: n/a')
    print('   '+'\n   '.join(out))
rb=np.nanmean(rcc[:,bj],axis=1)
cum=np.cumprod(1+np.nan_to_num(rb)); 
print('\n参照 篮子买入持有(不计成本，成分随时间增加)：')
for pn,(a,b) in list(ERA.items())+[('全期',('2007-01-01','2026-12-31'))]:
    m=(dates>=a)&(dates<=b); x=rb[m]; x=np.nan_to_num(x); c=np.cumprod(1+x); yrs=m.sum()/245
    print(f'   {pn}: 年化{(c[-1]**(1/yrs)-1)*100:+5.1f}% 回撤{(c/np.maximum.accumulate(c)-1).min()*100:5.1f}%')
