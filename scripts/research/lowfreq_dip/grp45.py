"""Convertible-bond ETF as D idle-cash holding (2020-05+), alone and mixed with gold / 10y bond. Research only."""
exec(open('grp40.py').read().split("for uname")[0])
cb, g, b = ret('sh.511380'), ret('sh.518880'), ret('sh.511260')
mixes = {'转债 ETF': cb, '黄金 + 十年国债各 1/2': 0.5 * g + 0.5 * b, '转债 + 黄金 + 十年国债各 1/3': (cb + g + b) / 3, '转债 + 十年国债各 1/2': 0.5 * cb + 0.5 * b}
v = np.isfinite(rD) & np.isfinite(ex) & np.all([np.isfinite(m) for m in mixes.values()], 0)
print(f'窗口 {dates[np.nonzero(v)[0][0]]} ~ {dates[np.nonzero(v)[0][-1]]}', flush=True)
stat(rD + idle * CY, v, 'D 单独（闲置 2%）')
for n, s in mixes.items():
    cor = np.corrcoef(rD[v], s[v])[0, 1]; stat(s, v, f'[单独] {n}（与 D 相关 {cor:+.2f}）')
    for k in (0.5, 1.0): stat(combo(s, k), v, f'   D + {n} k={k:g}')
