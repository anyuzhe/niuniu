"""How much of D is market beta? Regression on the equal-weight market and a hypothetical index-futures hedge (basis cost sweep). Research only."""
import numpy as np, pandas as pd
from grp_lib import *
panel = load_panel(); nd, nc = panel.shape; market, cand = compute_features(panel, 5e7, 3.0)
Z = np.load('grp30_streams.npz'); rD, ex = Z['rD'], Z['ex']
mk = np.nan_to_num(market.mret)                      # EW market daily return (product definition)
v = np.isfinite(rD) & np.isfinite(ex)
CY = 0.02 / 245; idle = 1 - np.r_[0, ex[:-1]]
y = rD[v]; x = mk[v]; X = np.c_[np.ones(len(x)), x]; b = np.linalg.lstsq(X, y, rcond=None)[0]
res = y - X @ b; se = np.sqrt(res.var() / (len(x) * x.var()))
print(f'日收益回归 rD = a + b·大盘：β = {b[1]:.3f}（t {b[1]/se:.1f}），α = {b[0]*245*100:+.1f}%/年；相关 {np.corrcoef(x, y)[0,1]:.2f}', flush=True)
exl = np.r_[0, ex[:-1]]
def stat(rr, label):
    z = rr[v]; cum = np.cumprod(1 + z); n = len(z); cagr = cum[-1] ** (245 / n) - 1; sh = z.mean() / z.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    print(f'{label:46s} 年化{cagr*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% 卡玛{cagr/abs(dd):4.2f}', flush=True)
stat(rD + idle * CY, 'D 单独')
for h in (0.5, 1.0):
    for basis in (0.0, 0.04, 0.08):
        hedged = rD + idle * CY - h * exl * mk - h * exl * basis / 245
        stat(hedged, f'D 对冲 h={h:g}×仓位×大盘，贴水成本 {basis*100:.0f}%/年')
