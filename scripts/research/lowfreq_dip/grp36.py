"""Intraday calm-period test with the first 5-min bar (2020+): buy at 09:35 on extreme gap/first-bar movers, sell same-day close or next open. Cross-sectional deciles, net of costs. Research only."""
import numpy as np, pandas as pd
from grp_lib import *
panel = load_panel(); nd, nc = panel.shape; market, cand = compute_features(panel, 5e7, 3.0)
Zf = np.load('fb.npz'); fo, fc = Zf['fo'].astype(np.float64), Zf['fc'].astype(np.float64)
O = panel.o.astype(np.float64); C = panel.c.astype(np.float64); Fq = panel.f.astype(np.float64)
t0 = int(np.searchsorted(panel.dates, '2020-02-01')); yr = np.array([d[:4] for d in panel.dates])
uni = cand.uni; buyok = cand.buyok
prevC = np.full((nd, nc), np.nan); prevC[1:] = C[:-1]
ratio = np.where(np.isfinite(fo) & np.isfinite(fc) & (fo > 0), fc / fo, np.nan)
p935 = O * ratio                      # approx 09:35 price on adjusted basis
r935 = p935 / prevC - 1               # gap + first 5 min vs prev close
rawp = p935 / Fq                      # approx raw price for tick cost
tick = 0.01 / np.maximum(rawp, 1e-6)
STAMP = 0.0005; COMM = 0.00025 * 2 + 0.00001
nxtO = np.full((nd, nc), np.nan); nxtO[:-1] = O[1:]
def run(sel_name, mask, exit_kind, nmax=20):
    rows = []
    for t in range(t0, nd - 1):
        m = mask[t] & uni[t - 1] & buyok[t] & np.isfinite(r935[t])
        if m.sum() < 5: continue
        idx = np.nonzero(m)[0]; sc = r935[t, idx]
        o = idx[np.argsort(sc if 'low' in sel_name else -sc)[:nmax]]
        px_e = p935[t, o]; px_x = C[t, o] if exit_kind == 'close' else nxtO[t, o]
        g = px_x / px_e - 1 - STAMP - COMM - 2 * tick[t, o]
        mk = np.nanmean((C[t, idx] / p935[t, idx] - 1) if exit_kind == 'close' else (nxtO[t, idx] / p935[t, idx] - 1))
        rows.append((t, np.nanmean(g), mk, len(o)))
    r = pd.DataFrame(rows, columns=['t', 'net', 'mk', 'n'])
    r['exc'] = r['net'] - r['mk']; r['yr'] = [yr[t] for t in r['t']]
    cum = np.prod(1 + r['net'].to_numpy()); n = len(r)
    print(f'{sel_name:28s} 退出={exit_kind:5s} 交易日 {n:4d} 日均净收益 {r.net.mean()*1e4:+6.1f}bp 超额 {r.exc.mean()*1e4:+6.1f}bp 胜率 {np.mean(r.net>0)*100:.0f}% 满仓年化 {(cum**(245/n)-1)*100:+7.1f}%', flush=True)
    return r
allm = np.ones((nd, nc), bool)
for name in ('low 首根 5 分钟后最弱 20（含跳空）', 'high 首根 5 分钟后最强 20'):
    for ek in ('close', 'nopen'):
        run(name, allm, ek)
# extreme drop only (<= -5%) but not limit-down region
ext = (r935 <= -0.05) & (r935 > -0.095)
for ek in ('close', 'nopen'):
    run('low 跌 5%~9.5%（最弱 20）', ext, ek)
# market-state split for the weak-reversal rule
r = run('low 首根 5 分钟后最弱 20（含跳空）', allm, 'close'); zd = market.z
r['z'] = [zd[t - 1] for t in r['t']]
for lab, lo, hi in (('恐慌 z≤-1.5', -9, -1.5), ('偏弱', -1.5, -0.5), ('中性', -0.5, 0.5), ('偏强/强势', 0.5, 9)):
    m = (r.z > lo) & (r.z <= hi); print(f'   {lab}: 天数 {m.sum()} 日均净 {r.net[m].mean()*1e4:+.1f}bp 超额 {r.exc[m].mean()*1e4:+.1f}bp', flush=True)
