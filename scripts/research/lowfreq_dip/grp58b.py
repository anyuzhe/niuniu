"""Step 3 (research only): gold/bond-half overlay, ETF sleeve turnover, good-market vs bad-market split, D1 variant."""
import sys, numpy as np, pandas as pd
sys.argv = [sys.argv[0], sys.argv[1] if len(sys.argv) > 1 else 'D']
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(open('grp58.py', encoding='utf-8').read())
VARN = sys.argv[1]
S['黄金/国债 各1/2'] = (R['GOLD'] + R['BOND']) / 2
print(f'######## {VARN}')
v3 = base & np.isfinite(S['黄金/国债 各1/2']) & (np.arange(nd) >= int(np.searchsorted(dates, '2017-08-07')))
print(f'窗口 {dates[np.nonzero(v3)[0][0]]} ~ {dates[np.nonzero(v3)[0][-1]]}')
stat(rD + idle * CY, v3, f'{VARN} 单独（闲置2%）')
stat(S['黄金/国债 各1/2'], v3, '[纯持有] 黄金/国债 各1/2')
stat(combo(S['黄金/国债 各1/2']), v3, f'{VARN} + 闲置放 黄金/国债 各1/2')
# ETF sleeve turnover (per year, one-way, in units of total equity)
a = idle; tov = np.abs(np.diff(np.r_[0, a]))
m = v3; yrs = m.sum() / 245
print(f'闲置仓位（占净值）平均 {a[m].mean()*100:.0f}%；每年单边换手 {tov[m].sum()/yrs*100:.0f}% 净值；5bp 单边成本拖累约 {tov[m].sum()/yrs*COST*1e4:.0f}bp/年')
# regime split on window one: HS300 above MA200 (known at prior close)
idx = np.cumprod(1 + np.nan_to_num(R['HS300'])); ma = pd.Series(idx).rolling(200, min_periods=200).mean().to_numpy()
good = np.r_[False, idx[:-1] > ma[:-1]] & np.r_[False, np.isfinite(ma[:-1])]
v1 = base & np.isfinite(R['HS300']) & (np.arange(nd) >= int(np.searchsorted(dates, '2014-01-02'))) & np.isfinite(ma)
def ann(r, m): x = r[m]; return (np.prod(1 + x) ** (245 / len(x)) - 1) * 100
print(f'\n--- 沪深300 在 200 日线上方 = "市场好"（2014 起；好 {np.sum(v1&good)} 天 / 差 {np.sum(v1&~good)} 天）年化收益 %')
rows = {'D 单独（闲置2%）': rD + idle * CY, '纯持有沪深300': R['HS300'], 'D + 沪深300': combo(R['HS300']), 'D + 沪深300趋势': combo(S['沪深300 趋势(MA200)'])}
for k, r in rows.items(): print(f'{k:20s} 市场好 {ann(r, v1&good):+7.1f}   市场差 {ann(r, v1&~good):+7.1f}')
print(f'{VARN} 平均仓位：市场好 {np.r_[0,ex[:-1]][v1&good].mean()*100:.0f}% / 市场差 {np.r_[0,ex[:-1]][v1&~good].mean()*100:.0f}%')
