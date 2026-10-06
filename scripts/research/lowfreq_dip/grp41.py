"""Trend per asset (MA200 / MA60 vs buy&hold, own history) and sub-period stability of the core-5 trend portfolio. Research only."""
exec(open('grp40.py').read().split("for uname")[0])
names = {'sh.510050': '上证50', 'sh.510300': '沪深300', 'sh.510500': '中证500', 'sz.159915': '创业板', 'sz.159941': '纳指', 'sh.518880': '黄金', 'sh.511260': '十年国债', 'sh.511220': '城投债', 'sh.512880': '证券', 'sh.512800': '银行', 'sh.512400': '有色', 'sh.512690': '酒', 'sh.512480': '半导体', 'sh.513050': '中概互联', 'sh.512100': '中证1000', 'sh.511030': '公司债'}
print('=== 单资产：买入持有 vs 趋势（MA200 / MA60 在均线上持有、否则货币 2%），各自上市以来')
for s in names:
    r = ret(s); a, b = build([s], 'MA200'); a60, _ = build([s], 'MA60'); bh, _ = build([s], None, hold_always=True)
    v = np.isfinite(a) & np.isfinite(a60) & np.isfinite(bh)
    def f(x):
        y = x[v]; cum = np.cumprod(1 + y); n = len(y); return (cum[-1] ** (245 / n) - 1) * 100, y.mean() / y.std() * np.sqrt(245), (cum / np.maximum.accumulate(cum) - 1).min() * 100
    h = f(bh); t2 = f(a); t6 = f(a60)
    print(f'{names[s]:8s}（{dates[np.nonzero(v)[0][0]][:7]} 起）买入持有 {h[0]:+5.1f}% / {h[1]:.2f} / {h[2]:.0f}%   MA200 {t2[0]:+5.1f}% / {t2[1]:.2f} / {t2[2]:.0f}%   MA60 {t6[0]:+5.1f}% / {t6[1]:.2f} / {t6[2]:.0f}%', flush=True)
print('=== 核心 5 资产，趋势 MA60 分段（与买入持有、D 比）')
bh, _ = build(CORE, None, hold_always=True); tr, _ = build(CORE, 'MA60')
for lab, a, b in (('2013-03 ~ 2019-12', '2013', '2019'), ('2020-01 ~ 2026-09', '2020', '2026')):
    m = np.array([a <= d[:4] <= b for d in dates]) & np.isfinite(rD) & np.isfinite(bh) & np.isfinite(tr)
    print(lab, flush=True); stat(rD + idle * CY, m, '  D 单独'); stat(bh, m, '  买入持有'); stat(tr, m, '  趋势 MA60'); stat(combo(tr, 1.0), m, '  D + 趋势 MA60 k=1'); stat(combo(bh, 1.0), m, '  D + 买入持有 k=1')
