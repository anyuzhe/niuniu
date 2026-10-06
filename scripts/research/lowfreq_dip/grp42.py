"""Fixed-split version of the idle-cash question: f of capital in a defensive sleeve, (1-f) runs D (D positions scale with its own capital). Research only."""
exec(open('grp40.py').read().split("for uname")[0])
g, b = ret('sh.518880'), ret('sh.511260')
gb = 0.5 * np.nan_to_num(g) + 0.5 * np.nan_to_num(b); gb[~(np.isfinite(g) & np.isfinite(b))] = np.nan
tr5, _ = build(CORE, 'MA60'); ens5, _ = build(CORE, 'ENS'); bh5, _ = build(CORE, None, hold_always=True)
cash = np.full(nd, CY)
D2 = rD + idle * CY
sleeves = {'货币基金 2%': cash, '黄金 + 十年国债各 1/2': gb, '核心 5 资产趋势 MA60': tr5, '核心 5 资产趋势 ENS': ens5, '核心 5 资产买入持有': bh5}
v = np.isfinite(rD) & np.isfinite(ex) & np.isfinite(gb) & np.isfinite(tr5) & np.isfinite(ens5) & np.isfinite(bh5)
print(f'窗口 {dates[np.nonzero(v)[0][0]]} ~ {dates[np.nonzero(v)[0][-1]]}', flush=True)
for name, s in sleeves.items():
    print('---', name, flush=True)
    for f in (0.0, 0.2, 0.3, 0.4, 0.5):
        stat((1 - f) * D2 + f * s, v, f'防守仓位 {f*100:.0f}% + D {100-f*100:.0f}%')
