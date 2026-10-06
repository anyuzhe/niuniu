"""Calendar effects on the 50ETF (2008+): pre-holiday run-up, turn-of-month, pre-Spring-Festival; overlay on D idle cash. T+0 not needed (ETF buy/sell same day allowed, but we hold >=1 day). Research only."""
import os, numpy as np, pandas as pd
Z = np.load('grp30_streams.npz'); rD, ex = Z['rD'], Z['ex']
dates = np.load('panel_ext.npz', allow_pickle=True)['dates'].astype(str); nd = len(dates); di = {d: i for i, d in enumerate(dates)}
x = pd.read_parquet(os.path.expanduser('~/mnt/lake/bronze/provider=tdx/etf_kline_daily/sh_510050.parquet'), columns=['date', 'close']); x['date'] = x['date'].astype(str)
c = np.full(nd, np.nan)
for d, v in zip(x.date, x.close):
    if d in di: c[di[d]] = v
c = pd.Series(c).ffill().to_numpy(); r = np.full(nd, np.nan); r[1:] = c[1:] / c[:-1] - 1
dts = pd.to_datetime(dates); gap = np.r_[0, (dts[1:] - dts[:-1]).days]
# holiday: the next trading day comes >=4 calendar days after (excludes Fri->Mon = 3)
nxtgap = np.r_[gap[1:], 0]; hol = np.nonzero(nxtgap >= 4)[0]       # t = last trading day before a long break
CY = 0.02 / 245; COST = 0.0005
def mk(window_days):
    s = np.zeros(nd); on = np.zeros(nd, bool)
    for t in hol:
        a = t - window_days + 1                     # hold returns of days a..t (buy at close a-1)
        if a < 1: continue
        s[a:t + 1] = np.nan_to_num(r[a:t + 1]); on[a:t + 1] = True; s[a] -= COST; s[t] -= COST
    return s, on
def tom(before, after):
    s = np.zeros(nd); ym = dts.year * 100 + dts.month
    last = [t for t in range(nd - 1) if ym[t] != ym[t + 1]]
    for t in last:
        a, b = t - before + 1, t + after
        if a < 1 or b >= nd: continue
        s[a:b + 1] = np.nan_to_num(r[a:b + 1]); s[a] -= COST; s[b] -= COST
    return s
def stat(rr, valid, label):
    y = rr[valid]; cum = np.cumprod(1 + y); n = len(y); cagr = cum[-1] ** (245 / n) - 1; sh = y.mean() / y.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    print(f'{label:46s} 年化{cagr*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% 卡玛{cagr/abs(dd):4.2f}', flush=True)
idle = 1 - np.r_[0, ex[:-1]]
v = np.isfinite(rD) & np.isfinite(ex)
stat(rD + idle * CY, v, 'D 单独')
print('每个样本期里：持有天数 / 平均每次收益')
for name, s in (('节前 1 天', mk(1)[0]), ('节前 2 天', mk(2)[0]), ('节前 3 天', mk(3)[0]), ('节前 5 天', mk(5)[0]), ('月末 1 天 + 月初 3 天', tom(1, 3)), ('月末 2 天 + 月初 2 天', tom(2, 2))):
    nz = np.count_nonzero(s[v]); tot = (np.prod(1 + s[v]) - 1) * 100
    cor = np.corrcoef(rD[v], s[v])[0, 1]
    stat(s, v, f'[单独，仅窗口内持有] {name}（持仓日 {nz}，相关 {cor:+.2f}）')
    a = idle; tot_r = rD + np.where(s != 0, a * s, 0.0) + (idle - np.where(s != 0, a, 0.0)) * CY
    stat(tot_r, v, f'   D + {name}（用全部闲置资金）')
