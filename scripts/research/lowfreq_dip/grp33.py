"""Industry rotation (SW L1 equal-weight industry baskets, monthly): momentum / reversal; stream + overlay on D idle cash. Research only."""
import numpy as np, pandas as pd, os
Z = np.load('grp30_streams.npz'); rD, ex = Z['rD'], Z['ex']
dates = np.load('panel_ext.npz', allow_pickle=True)['dates'].astype(str); nd = len(dates)
# per-industry EW daily returns come from grp7.ind_series; cache them once
if not os.path.exists('ind_ret.npz'):
    from grp7 import *
    R, A = ind_series(l1); np.savez('ind_ret.npz', R=R)
R = np.load('ind_ret.npz')['R']; ng = R.shape[1]
CY = 0.02 / 245; COST = 0.0005 * 4   # industry baskets via ETFs/stocks: 20bp one-way proxy per unit turnover
dts = pd.to_datetime(dates); ym = dts.year * 100 + dts.month
reb = [t for t in range(nd - 1) if ym[t] != ym[t + 1]]
Rz = np.nan_to_num(R); logc = np.cumsum(np.log1p(Rz), 0)
def rot(lookback, k, rev=False, skip=0):
    out = np.full(nd, np.nan); cur = np.zeros(ng); pend = {}
    for t in reb:
        if t - lookback - skip < 0: continue
        sc = logc[t - skip] - logc[t - skip - lookback]; ok = np.isfinite(R[t]) & (np.abs(Rz[t - 60:t]).sum(0) > 0)
        s = np.where(ok, sc, np.nan); idx = np.nonzero(np.isfinite(s))[0]
        if len(idx) < 10: continue
        o = idx[np.argsort(s[idx] if rev else -s[idx])[:k]]; w = np.zeros(ng); w[o] = 1.0 / k; pend[t + 2] = w
    first = min(pend) if pend else nd
    for t in range(first, nd):
        tov = 0.0
        if t in pend: new = pend[t]; tov = np.abs(new - cur).sum(); cur = new
        out[t] = float(np.nansum(Rz[t] * cur)) - COST * tov / 2
    return out
def stat(r, valid, label):
    x = r[valid]; cum = np.cumprod(1 + x); n = len(x); cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    print(f'{label:46s} 年化{cagr*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% 卡玛{cagr/abs(dd):4.2f}', flush=True)
idle = 1 - np.r_[0, ex[:-1]]
def combo(s, k):
    a = k * idle; da = np.abs(np.diff(np.r_[0, a])); return rD + a * np.nan_to_num(s) - 0.002 * da + (idle - a) * CY
ew = np.nanmean(np.where(np.isfinite(R), R, np.nan), 1); ew = np.nan_to_num(ew)
cfgs = [('动量 3 月 top3', 60, 3, False), ('动量 6 月 top3', 120, 3, False), ('动量 12 月 top3', 245, 3, False), ('动量 6 月 top6', 120, 6, False), ('反转 1 月 bottom3', 20, 3, True), ('反转 3 月 bottom3', 60, 3, True), ('反转 12 月 bottom3', 245, 3, True), ('动量 12-1 月 top3', 225, 3, False)]
print('=== 申万一级行业轮动（月度，3~6 个行业等权）', flush=True)
for name, lb, k, rev in cfgs:
    s = rot(lb, k, rev, skip=20 if '12-1' in name else 0)
    v = np.isfinite(rD) & np.isfinite(s) & np.isfinite(ex); cor = np.corrcoef(rD[v], s[v])[0, 1]
    stat(s, v, f'[单独] {name}（与 D 相关 {cor:+.2f}）'); 
    stat(rD + idle * CY, v, '   D 单独')
    for kk in (0.5, 1.0): stat(combo(s, kk), v, f'   D + {name} k={kk:g}')
v = np.isfinite(rD) & np.isfinite(R).any(1) & np.isfinite(ex); stat(ew, v, '[参照] 31 行业等权')
