"""Can we filter out 'blow-up' stocks (idiosyncratic crash days, limit-downs unrelated to the market, far-worse-than-market drops) from D's candidates? Event-level comparison + fused D with filters. Research only."""
import sys, gc, grp11 as g
from grp11 import *
c = panel.c.astype(np.float32); nd_, nc_ = c.shape
r1 = np.full((nd_, nc_), np.nan, np.float32); r1[1:] = c[1:] / c[:-1] - 1
mr = np.nan_to_num(market.mret).astype(np.float32)[:, None]
idio = r1 - mr
roll_min = lambda a, L: pd.DataFrame(a).rolling(L, min_periods=5).min().to_numpy().astype(np.float32)
roll_sum = lambda a, L: pd.DataFrame(a).rolling(L, min_periods=5).sum().to_numpy().astype(np.float32)
imin = roll_min(idio, 20)
ld = ((r1 <= -0.095) & (mr > -0.03)).astype(np.float32); ldn = roll_sum(ld, 20)
rel20 = cand.ret20 - market.mk20[:, None]
F = {'F1 20 日内有单日 idio ≤ −8%': imin <= -0.08, 'F2 20 日内有单日 idio ≤ −12%': imin <= -0.12, 'F3 20 日内有 ≥1 个“大盘没跌的跌停”': ldn >= 1, 'F4 20 日跌幅比大盘多 25 个点以上': rel20 <= -0.25}
# --- event-level: D's own picks (top 20 by r20 among pool each gate day), 20-day hold, simple net
H = 20; COST = 0.003
O, C = panel.o.astype(np.float64), panel.c.astype(np.float64)
rows = []
for s, (gate, e6, r20) in g.SL.items():
    for t in np.nonzero(gate)[0]:
        if t + 1 + H >= nd_ or dates[t] < '2008-01-01': continue
        pool = np.nonzero(e6[t] & buyok[t])[0]
        if not len(pool): continue
        pick = pool[np.argsort(r20[t, pool], kind='stable')[:20]]
        for j in pick:
            if not (np.isfinite(O[t + 1, j]) and np.isfinite(C[t + H, j])): continue
            rows.append((s, t, j, C[t + H, j] / O[t + 1, j] - 1 - COST, *[bool(v[t, j]) for v in F.values()]))
E = pd.DataFrame(rows, columns=['s', 't', 'j', 'net'] + list(F)); E['yr'] = [dates[t][:4] for t in E.t]
print(f'D 候选选股事件 {len(E)} 笔（A / B / C 合并，每个闸门日取最弱 20 只；同一只在不同闸门日重复计）', flush=True)
def line(m, label):
    x = E.net[m]
    if len(x) < 30: print(f'  {label}: n={len(x)}'); return
    print(f'  {label:44s} n={len(x):6d} 均值 {x.mean()*100:+6.2f}% 中位 {x.median()*100:+6.2f}% 胜率 {np.mean(x>0)*100:3.0f}% ≤−30% 占比 {np.mean(x<=-0.3)*100:4.1f}% ≥+30% 占比 {np.mean(x>=0.3)*100:4.1f}%', flush=True)
line(np.ones(len(E), bool), '全部')
for k in F:
    line(E[k].to_numpy(), k + ' 命中'); line(~E[k].to_numpy(), k + ' 未命中')
print('--- 命中占比与分年份（F3 / F1，均值差 = 未命中 − 命中）', flush=True)
for k in ('F1 20 日内有单日 idio ≤ −8%', 'F3 20 日内有 ≥1 个“大盘没跌的跌停”'):
    print(k, '命中占比', f'{E[k].mean()*100:.1f}%', flush=True)
    for a, b in (('2008', '2012'), ('2013', '2017'), ('2018', '2022'), ('2023', '2026')):
        m = (E.yr >= a) & (E.yr <= b); h = E.net[m & E[k]]; n = E.net[m & ~E[k]]
        print(f'   {a}-{b}: 命中 n={len(h)} 均值 {h.mean()*100:+.2f}%；未命中 n={len(n)} 均值 {n.mean()*100:+.2f}%；差 {(n.mean()-h.mean())*100:+.2f} 个点', flush=True)
# --- fused D with filters applied to every sleeve's pool
base_SL = dict(g.SL); W0 = {'A': .08, 'C': .08, 'B': .025}
for name, flag in [('基线', None)] + list(F.items()):
    g.SL = {s: (v[0], (v[1] & ~flag) if flag is not None else v[1], v[2]) for s, v in base_SL.items()}
    show(f'D 剔除：{name}', order='ACB', w=W0, G=1.0, caps={}, cash_yield=0.02)
