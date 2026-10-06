"""Earnings-forecast drift (PEAD-style): buy day after a new forecast notice (positive / negative / neutral), hold 20d; event study + daily stream + overlay on D idle cash. Research only."""
import numpy as np, pandas as pd
from grp_lib import *
panel = load_panel(); nd, nc = panel.shape; market, cand = compute_features(panel, 5e7, 3.0)
Z = np.load('grp30_streams.npz'); rD, ex = Z['rD'], Z['ex']
F = np.load('fund_fin.npz'); fcat = F['fc_cat']; fn = F['fc_notice']; del F
O = panel.o.astype(np.float64); C = panel.c.astype(np.float64)
H = 20; COSTRT = 0.0025
new = np.zeros((nd, nc), bool); new[1:] = np.isfinite(fn[1:]) & (fn[1:] != fn[:-1]) & np.isfinite(fcat[1:])
r1 = np.full((nd, nc), np.nan); r1[1:] = C[1:] / C[:-1] - 1
uni = cand.uni; buyok = cand.buyok
ewu = np.array([np.nanmean(np.where(uni[t - 1], r1[t], np.nan)) if t > 0 else np.nan for t in range(nd)])
cumew = np.cumsum(np.nan_to_num(np.log1p(ewu)))
res = {}
for cat, name in ((1, '预增 / 利好'), (-1, '预减 / 利空'), (0, '中性')):
    ev = np.argwhere(new & (fcat == cat) & uni)  # signal day t (close), entry t+1 open
    rets = []; exc = []; yrs = []
    pos = np.zeros((nd, nc), bool)
    for t, j in ev:
        e = t + 1; x = e + H - 1
        if x >= nd or not buyok[e, j] or not np.isfinite(O[e, j]) or not np.isfinite(C[x, j]): continue
        g = C[x, j] / O[e, j] - 1 - COSTRT; mk = np.exp(cumew[x] - cumew[e - 1]) - 1
        rets.append(g); exc.append(g - mk); yrs.append(panel.dates[t][:4]); pos[e:x + 1, j] = True
    rets = np.array(rets); exc = np.array(exc); yrs = np.array(yrs)
    print(f'=== {name}：事件 {len(rets)}，净收益均值 {rets.mean()*100:+.2f}%，超额（对全市场等权）{exc.mean()*100:+.2f}%，胜率 {np.mean(rets>0)*100:.0f}%', flush=True)
    for a, b in (('2008', '2012'), ('2013', '2017'), ('2018', '2022'), ('2023', '2026')):
        m = (yrs >= a) & (yrs <= b); print(f'    {a}-{b}: n={m.sum()} 超额 {exc[m].mean()*100:+.2f}%', flush=True)
    npos = pos.sum(1)
    with np.errstate(invalid='ignore', divide='ignore'):
        s = np.where(npos > 0, np.nansum(np.where(pos, r1, 0.0), 1) / np.maximum(npos, 1), 0.0)
    res[cat] = s
def stat(r, valid, label):
    x = r[valid]; cum = np.cumprod(1 + x); n = len(x); cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    print(f'{label:46s} 年化{cagr*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% 卡玛{cagr/abs(dd):4.2f}', flush=True)
idle = 1 - np.r_[0, ex[:-1]]; CY = 0.02 / 245
v = np.isfinite(rD) & np.isfinite(ex); v[:300] = False
stat(rD + idle * CY, v, 'D 单独')
for cat, s in res.items():
    cor = np.corrcoef(rD[v], s[v])[0, 1]; stat(s, v, f'[单独，满仓持有事件篮子] 类别 {cat}（与 D 相关 {cor:+.2f}）')
    for k in (0.5, 1.0):
        a = k * idle; da = np.abs(np.diff(np.r_[0, a])); tot = rD + a * s - 0.002 * da + (idle - a) * CY; stat(tot, v, f'   D + 类别 {cat} k={k:g}')
# long positive / short-free: only report long. 
