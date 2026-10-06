import grp52 as h
from grp52 import *
hist = []
eq, ex, _ = fused2(hist=hist); base = eq
print('=== A 触发段的“第一天”：账户里已有多少仓位、谁占着、A 最终买到多少（权重 8%，名额 20；理想=按候选数 × 8%）')
gA_ = gateA; t0 = int(np.searchsorted(dates, '2008-01-01'))
first = [t for t in range(t0 + 1, nd) if gA_[t] and not gA_[t - 1]]
byt = {(t, s): (n_s, d, c, room, want) for (t, s, n_s, d, c, room, want) in hist}
tot_pre = []; rows = []
for t in first:
    if (t, 'A') not in byt: continue
    n_s, d, c, room, want = byt[(t, 'A')]
    nxt_inv = None
    rows.append((dates[t], d['A'] + d['B'] + d['C'], d['B'], d['C'], d['A'], room, want))
print(f'共 {len(rows)} 段 A 触发（有候选的）；开买前总仓位均值 {np.mean([r[1] for r in rows])*100:.0f}%  其中 B {np.mean([r[2] for r in rows])*100:.0f}% C {np.mean([r[3] for r in rows])*100:.0f}% A自己(上一段遗留) {np.mean([r[4] for r in rows])*100:.0f}%')
need = [min(r[6] * .08, 1.0) for r in rows]; room = [r[5] for r in rows]
print(f'第一天 A 想买 {np.mean(need)*100:.0f}% 仓位（20 只×8% 封顶 100%），账户剩余空间均值 {np.mean(room)*100:.0f}%，实际能买 {np.mean([min(n,max(r,0)) for n,r in zip(need,room)])*100:.0f}%')
print('空间不足（能买不到想买的一半）的段数:', sum(1 for n, r in zip(need, room) if r < n * .5), '/', len(rows))
print('最挤的 8 段: 日期 开买前仓位 B占 C占 剩余空间')
for r in sorted(rows, key=lambda r: r[5])[:8]: print(f'  {r[0]} 总{r[1]*100:3.0f}% B{r[2]*100:3.0f}% C{r[3]*100:3.0f}% A{r[4]*100:3.0f}% 剩{r[5]*100:3.0f}% 想买{min(r[6]*.08,1)*100:.0f}%')
print('\n=== 让位方案 年度收益对比 与 提前平仓排序方式')
yrs = np.array([int(d[:4]) for d in dates])
def yearly(eq):
    out = {}
    for y in range(2008, 2027):
        k = np.nonzero(yrs == y)[0]
        if len(k) == 0 or not np.isfinite(eq[k[0] - 1] if k[0] > 0 else eq[k[0]]): continue
        a = eq[k[0] - 1] if k[0] > t0 else eq[k[0]]; out[y] = eq[k[-1]] / a - 1
    return out
V = {}
def run(label, **kw):
    eq, ex, ev = fused2(**kw); r = dr(eq); met(r, label, ex); print(f'{"":46s} 提前平仓 {ev} 笔', flush=True); V[label] = eq
run('基线', )
run('C 平 B(最老先平)', evict={'C': 'B'})
run('C 平 B(最新先平)', evict={'C': 'B'}, ekey='new')
run('C 平 B(浮亏最大先平)', evict={'C': 'B'}, ekey='worst')
run('A 平 BC; C 平 B(最老)', evict={'A': 'BC', 'C': 'B'})
run('A 平 BC; C 平 B(最新)', evict={'A': 'BC', 'C': 'B'}, ekey='new')
run('A 平 BC; C 平 B(浮亏最大)', evict={'A': 'BC', 'C': 'B'}, ekey='worst')
run('只有 A 平 C (A 不挤 B)', evict={'A': 'C'})
print('\n年度收益 基线 / C平B / A平BC;C平B')
yb, y1, y2 = yearly(V['基线']), yearly(V['C 平 B(最老先平)']), yearly(V['A 平 BC; C 平 B(最老)'])
for y in yb: print(y, f'{yb[y]*100:+6.1f}% {y1.get(y,np.nan)*100:+6.1f}% {y2.get(y,np.nan)*100:+6.1f}%')
