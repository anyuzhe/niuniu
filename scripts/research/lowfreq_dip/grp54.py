"""D: when A fires, close C/B positions to make room. Robustness. Research only."""
import grp52 as h
from grp52 import *
yrs = np.array([int(d[:4]) for d in dates]); t0 = int(np.searchsorted(dates, '2008-01-01'))
def yearly(eq):
    out = {}
    for y in range(2008, 2027):
        k = np.nonzero(yrs == y)[0]
        if len(k) == 0: continue
        a = eq[k[0] - 1] if k[0] > t0 else eq[k[0]]; out[y] = eq[k[-1]] / a - 1
    return out
V = {}; L = {}
def run(label, **kw):
    lg = []; eq, ex, ev = fused2(evlog=lg, **kw); r = dr(eq); met(r, label, ex); print(f'{"":46s} 提前平仓 {ev} 笔', flush=True); V[label] = eq; L[label] = lg
run('基线 A>C>B')
run('A 平 C+B (最老先平)', evict={'A': 'BC'})
run('A 平 C+B (最新先平)', evict={'A': 'BC'}, ekey='new')
run('A 平 C+B (浮亏最大先平)', evict={'A': 'BC'}, ekey='worst')
run('A 只平 B', evict={'A': 'B'})
run('A 只平 C', evict={'A': 'C'})
print('\n=== 提前平仓成本敏感性（额外每次卖出冲击）')
for ec in (0.003, 0.006, 0.01):
    run(f'A 平 C+B, 额外卖出成本 {ec*1e4:.0f}bp', evict={'A': 'BC'}, ecost=ec)
print('\n=== 被平掉的仓位：若持有到期会怎样 vs 提前平掉时的盈亏')
lg = L['A 平 C+B (最老先平)']
d = pd.DataFrame(lg, columns=['t', 'by', 'sleeve', 'cur', 'net_hold', 'age'])
d = d[d.net_hold.notna()]
print(f'被平 {len(lg)} 笔（可算持有到期的 {len(d)} 笔）  被平时已持有天数均值 {d.age.mean():.1f}')
for sl in 'CB':
    x = d[d.sleeve == sl]
    print(f'  来自 {sl}: {len(x)} 笔  平仓时已浮盈亏 {x.cur.mean()*1e4:+.0f}bp  持有到期本应 {x.net_hold.mean()*1e4:+.0f}bp  (到期收益-当时浮盈 = {(x.net_hold-x.cur).mean()*1e4:+.0f}bp 被放弃的后续收益)')
ep = d.groupby(d.t).size()
print(f'触发平仓的 A 日 {len(ep)} 天，每天平均平 {ep.mean():.1f} 只，最多 {ep.max()} 只')
print('\n=== 分年度 基线 / A 平 C+B / A 只平 C')
yb, y1, y2 = yearly(V['基线 A>C>B']), yearly(V['A 平 C+B (最老先平)']), yearly(V['A 只平 C'])
for y in yb: print(y, f'{yb[y]*100:+6.1f}% {y1[y]*100:+6.1f}% {y2[y]*100:+6.1f}%   差 {100*(y1[y]-yb[y]):+5.1f}')
dif = np.array([y1[y] - yb[y] for y in yb]); print(f'赢的年份 {int((dif>0.0005).sum())} / 输的 {int((dif<-0.0005).sum())} / 平 {int((abs(dif)<=0.0005).sum())}')
# per-trade: A trades
print('\n=== 分段（每 A 触发段）：基线 vs 平仓方案，该段起 60 个交易日的净值变化')
gA = gateA; first = [t for t in range(t0 + 1, nd - 60) if gA[t] and not gA[t - 1]]
b = V['基线 A>C>B']; e1 = V['A 平 C+B (最老先平)']
rb = np.array([b[t + 60] / b[t] - 1 for t in first]); re_ = np.array([e1[t + 60] / e1[t] - 1 for t in first])
print(f'{len(first)} 段  平均 基线 {rb.mean()*100:+.1f}%  方案 {re_.mean()*100:+.1f}%  方案更好 {int((re_>rb).sum())} 段 / 更差 {int((re_<rb).sum())} 段')
print('差异最大的 5 段(方案-基线):', [(dates[t], f'{(x-y)*100:+.1f}') for t, x, y in sorted(zip(first, re_, rb), key=lambda a: -abs(a[1]-a[2]))[:5]])
