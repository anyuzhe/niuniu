"""D equity curve: nav csv + png + yearly table. Research only."""
import grp11 as g
from grp11 import *
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
eq, ex, ntr, pnl, wsum, minr = g.fused(order='ACB', w={'A': .08, 'C': .08, 'B': .025}, G=1.0, caps={}, cash_yield=0.02)
d = pd.to_datetime(panel.dates); m = np.isfinite(eq)
nav = pd.Series(eq[m] / eq[m][0], index=d[m]); mk = np.nan_to_num(market.mret)[m]; bm = pd.Series(np.cumprod(1 + mk), index=d[m]); bm /= bm.iloc[0]
exs = pd.Series(ex[m], index=d[m]); dd = nav / nav.cummax() - 1
pd.DataFrame({'nav': nav, 'ew_market': bm, 'exposure': exs, 'drawdown': dd}).to_csv('D_nav.csv')
yr = nav.resample('YE').last().pct_change(); yr.iloc[0] = nav.resample('YE').last().iloc[0] / 1 - 1
ym = bm.resample('YE').last().pct_change(); ym.iloc[0] = bm.resample('YE').last().iloc[0] - 1
print('年度收益 D vs 全市场等权 | 年末平均仓位')
for y in yr.index: print(y.year, f'{yr[y]*100:+7.1f}% {ym[y]*100:+7.1f}%  仓位 {exs[exs.index.year==y.year].mean()*100:3.0f}%')
print('终值', nav.iloc[-1], '区间', nav.index[0].date(), nav.index[-1].date(), '最大回撤', dd.min(), dd.idxmin().date())
from matplotlib import font_manager as fm
import glob
fm.fontManager.addfont('/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf')
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Droid Sans Fallback', 'Noto Sans CJK SC', 'Noto Serif CJK SC', 'PingFang SC', 'Arial Unicode MS', 'DejaVu Sans']; plt.rcParams['axes.unicode_minus'] = False
f, ax = plt.subplots(3, 1, figsize=(12, 9), sharex=True, gridspec_kw={'height_ratios': [3, 1.2, 1]})
ax[0].plot(nav, label=f'Strategy D ({nav.iloc[-1]:.1f}x)', lw=1.6); ax[0].plot(bm, label=f'Equal-weight market ({bm.iloc[-1]:.1f}x)', lw=1, color='gray'); ax[0].set_yscale('log'); ax[0].legend(); ax[0].grid(alpha=.3); ax[0].set_title('Strategy D equity curve (1x shared capital, 2008-2026, log scale)')
ax[1].fill_between(dd.index, dd.values * 100, 0, color='tab:red', alpha=.4); ax[1].set_ylabel('Drawdown %'); ax[1].grid(alpha=.3)
ax[2].fill_between(exs.index, exs.values * 100, 0, color='tab:blue', alpha=.4); ax[2].set_ylabel('Exposure %'); ax[2].grid(alpha=.3)
plt.tight_layout(); plt.savefig('D_curve.png', dpi=110)
