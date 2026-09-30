import numpy as np, warnings; warnings.filterwarnings('ignore')
from etfpanic_bt import *
cfg=dict(H=20,thr=-0.036,tiers=[(None,1/3,False)],maxact=3)
eq,ex,tr=simulate(cfg)
tr=[t for t in tr if t.get('proc') is not None and t['closed']]
tr.sort(key=lambda t:t['e']); eps=[]; cur=[tr[0]]
for t in tr[1:]:
    if t['e']-cur[-1]['e']>10: eps.append(cur); cur=[t]
    else: cur.append(t)
eps.append(cur)
rows=[]
for e in eps:
    cost=sum(t['cost'] for t in e); proc=sum(t['proc'] for t in e)
    # market move: mk20 at first entry signal day, and stock-market rebound is implicit
    rows.append((dates[e[0]['e']],dates[e[-1]['x']] if e[-1]['x']<nd else '',len(e),proc/cost-1,(proc-cost)))
print(f'共 {len(rows)} 段行情（相隔>10个交易日的建仓算新的一段），{len(tr)} 批')
print('起始日        批数   该段收益(相对投入)  对总资金贡献(初始资金=1，按各批投入额粗算)')
for r in rows: print(f'{r[0]}  {r[2]:2d}   {r[3]*100:+6.1f}%   {r[4]*100:+5.1f}%')
rr=np.array([r[3] for r in rows]); print(f'\n盈利段 {np.sum(rr>0)}/{len(rr)}，平均 {rr.mean()*100:+.1f}%，中位 {np.median(rr)*100:+.1f}%，最好 {rr.max()*100:+.1f}%，最差 {rr.min()*100:+.1f}%')
# yearly returns and worst drawdown window
print('\n分年收益（策略 vs 宽基篮子买入持有）：')
rb=np.nanmean(rcc[:,bj],axis=1); bh=np.cumprod(1+np.r_[0,rb[1:]])
for Y in range(2019,2027):
    m=np.array([d[:4]==str(Y) for d in dates])&(np.arange(nd)<=LASTMK); i=np.nonzero(m)[0]
    if len(i)<50: continue
    a=eq[i[0]-1]; b=eq[i[-1]]; a2=bh[i[0]-1]; b2=bh[i[-1]]
    print(f'  {Y}: 策略 {(b/a-1)*100:+6.1f}%   买入持有 {(b2/a2-1)*100:+6.1f}%')
e=eq[:LASTMK+1]; pk=np.maximum.accumulate(e); dd=e/pk-1; j=int(np.argmin(dd)); i0=int(np.argmax(e[:j+1]))
print(f'\n最大回撤 {dd[j]*100:.1f}%：从 {dates[i0]} 的高点到 {dates[j]} 的低点')
# dependence on best episodes: recompute annualised return excluding the best 1/2/3 episodes' P&L
contrib=sorted(rows,key=lambda r:-r[4]); tot=sum(r[4] for r in rows)
print(f'\n总盈亏（按批投入额粗算）{tot*100:+.1f}%；最好的3段贡献 {sum(r[4] for r in contrib[:3])*100:+.1f}%，去掉后剩 {(tot-sum(r[4] for r in contrib[:3]))*100:+.1f}%')
