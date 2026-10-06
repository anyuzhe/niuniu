"""Turn-of-month check: placebo windows of the same length at every start day of the month; sub-period stability; with 50ETF / 300ETF / EW stock universe. Research only."""
import os, numpy as np, pandas as pd
exec(open('grp37.py').read().split("def mk(")[0])      # reuse data loading (r, dts, rD, ex, nd, idle later)
ym = dts.year * 100 + dts.month
tdm = np.zeros(nd, int); tdm_rev = np.zeros(nd, int)
for m in np.unique(ym):
    ii = np.nonzero(ym == m)[0]; tdm[ii] = np.arange(1, len(ii) + 1); tdm_rev[ii] = np.arange(len(ii), 0, -1)
idle = 1 - np.r_[0, ex[:-1]]; v = np.isfinite(rD) & np.isfinite(ex); half = dts.year.to_numpy() <= 2016
def stat(rr, m):
    y = rr[m & v]; cum = np.cumprod(1 + y); n = len(y); return (cum[-1] ** (245 / n) - 1) * 100, y.mean() / y.std() * np.sqrt(245)
base_a, base_s = stat(rD + idle * CY, np.ones(nd, bool))
print(f'D 单独 {base_a:+.1f}% / {base_s:.2f}')
print('窗口 = 4 个交易日连续持有（按本月第几个交易日开始，负数 = 月末倒数第几天开始）；日均超额 = 窗口日平均收益 − 全部日平均收益（bp）；叠加 = D + 50ETF 用全部闲置资金')
allmean = np.nanmean(r[v])
starts = [-1, -2, -3] + list(range(1, 19))
for s0 in starts:
    on = np.zeros(nd, bool)
    for i in range(nd):
        if s0 > 0 and tdm[i] >= s0 and tdm[i] < s0 + 4: on[i] = True
        if s0 < 0:
            # start at tdm_rev == -s0 , continue into next month
            pass
    if s0 < 0:
        for t in np.nonzero(tdm_rev == -s0)[0]:
            on[t:t + 4] = True
    s = np.where(on, np.nan_to_num(r), 0.0)
    st = np.nonzero(on & ~np.r_[False, on[:-1]])[0]
    for t in st: s[t] -= COST; s[min(t + 3, nd - 1)] -= COST
    exc = (np.nanmean(r[on & v]) - allmean) * 1e4
    tot = rD + np.where(on, idle * s, 0.0) + (idle - np.where(on, idle, 0.0)) * CY
    a1, s1 = stat(tot, half); a2, s2 = stat(tot, ~half); a, sh = stat(tot, np.ones(nd, bool)); b1, _ = stat(rD + idle * CY, half); b2, _ = stat(rD + idle * CY, ~half)
    print(f'起点 {s0:+3d}: 日均超额 {exc:+5.1f}bp | D+窗口 {a:+5.1f}%/{sh:.2f}（08-16 {a1-b1:+.1f}pt，17-26 {a2-b2:+.1f}pt）', flush=True)
