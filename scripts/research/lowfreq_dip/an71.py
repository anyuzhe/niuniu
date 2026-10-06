"""Can entry-time factors predict the rebound height (20d max run-up) or the final 20d return of D's candidates? Research only."""
import numpy as np, json
import lib70 as L
nd = L.nd; t0 = int(np.searchsorted(L.dates, '2008-01-01'))
FE = ['r20', 'r5', 'zown', 'dd60', 'dma20', 'volratio', 'sig60', 'ret1', 'mz', 'sleeveA', 'sleeveC', 'rankpos']
r5, dd60, vr, ret1 = L.L('r5'), L.L('dd60'), L.L('volratio'), L.L('ret1')
rows = []; H = 20
for t in range(t0, nd - 22):
    for si, s in enumerate('ACB'):
        if not L.GATE[s][t]: continue
        pool = np.nonzero(L.POOL[s][t] & L.buyok[t])[0]
        if not len(pool): continue
        v = np.asarray(L.R20[t, pool], np.float64); v = np.where(np.isfinite(v), v, np.inf); order = np.argsort(v, kind='stable')[:20]
        for rp, j in enumerate(pool[order]):
            e = t + 1; o0 = float(L.O[e, j]); path = np.asarray(L.C[e:t + H, j], np.float64)
            if len(path) < 10 or not np.isfinite(o0): continue
            ex = L.baseline_exit(int(j), t, H)
            if ex is None: continue
            xi, px = ex; raw_e = o0 / float(L.F[e, j]); raw_x = px / float(L.F[xi, j])
            net = (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - L.fee[xi]
            ru = np.nanmax(path) / o0 - 1; dmax = int(np.nanargmax(path))
            sg = float(L.SIG[t, j]); r20 = float(L.R20[t, j])
            f = [r20, float(r5[t, j]), r20 / (sg * np.sqrt(20) + 1e-9), float(dd60[t, j]), float(L.DIST[t, j]), float(vr[t, j]), sg, float(ret1[t, j]), float(L.MZ[t]), float(s == 'A'), float(s == 'C'), rp]
            rows.append([t, int(L.yr[t])] + f + [net, ru, dmax])
X = np.array(rows, float); X = X[np.isfinite(X).all(1)]; np.save('X71.npy', X)
print('样本', len(X), '行；候选-信号日', flush=True)
yrs = X[:, 1].astype(int); F = X[:, 2:2 + len(FE)]; net = X[:, -3]; ru = X[:, -2]; dmax = X[:, -1]
def rank(a): return np.argsort(np.argsort(a)).astype(float)
def ic(a, b): 
    if len(a) < 30: return np.nan
    return float(np.corrcoef(rank(a), rank(b))[0, 1])
print('\n=== 各因子与 20 日最高涨幅(反弹高度) / 20 日期末净收益的秩相关(IC)；前半 2008-2016 / 后半 2017-2026 ===')
print(f'{"因子":10s} 高度IC(前/后)    期末IC(前/后)')
h1 = yrs <= 2016
for i, nm in enumerate(FE):
    print(f'{nm:10s} {ic(F[h1,i],ru[h1]):+.3f}/{ic(F[~h1,i],ru[~h1]):+.3f}      {ic(F[h1,i],net[h1]):+.3f}/{ic(F[~h1,i],net[~h1]):+.3f}')
print('\n=== 反弹高度的分布：最高涨幅 / 期末收益 / 最高点出现在第几天 ===')
print('最高涨幅分位 10/25/50/75/90%:', np.percentile(ru, [10, 25, 50, 75, 90]).round(3), ' 期末收益分位:', np.percentile(net, [10, 25, 50, 75, 90]).round(3))
print('最高点出现天数 分位 10/25/50/75/90%:', np.percentile(dmax, [10, 25, 50, 75, 90]), ' 期末收益 / 最高涨幅 中位数', float(np.median(net / np.maximum(ru, 1e-3))).__round__(2))
# walk-forward ridge on (standardised) factors, target = run-up and net
def fit(Xtr, ytr, lam=50.0):
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9; Z = (Xtr - mu) / sd
    b = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (ytr - ytr.mean())); return mu, sd, b, ytr.mean()
print('\n=== 滚动训练（用此前所有年份拟合岭回归，预测当年）：预测值与实际的秩相关 / R² 以及按预测高低分组的实际值 ===')
for tgt, nm in ((ru, '反弹高度(20日最高涨幅)'), (net, '20日期末净收益')):
    pr = np.full(len(X), np.nan)
    for y in range(2012, 2027):
        tr = yrs < y; te = yrs == y
        if tr.sum() < 500 or te.sum() == 0: continue
        mu, sd, b, m0 = fit(F[tr], tgt[tr]); pr[te] = m0 + ((F[te] - mu) / sd) @ b
    ok = np.isfinite(pr); r2 = 1 - np.sum((tgt[ok] - pr[ok]) ** 2) / np.sum((tgt[ok] - tgt[ok].mean()) ** 2)
    q = np.percentile(pr[ok], [20, 40, 60, 80]); g = np.digitize(pr[ok], q)
    print(f'{nm}: 样本外 IC {ic(pr[ok], tgt[ok]):+.3f}  R² {r2:+.3f}  按预测值分 5 组的实际均值(低→高): ' + ' '.join(f'{tgt[ok][g==k].mean()*100:+.1f}%' for k in range(5)))
    for lab, msk in (('前半(2012-2016)', yrs[ok] <= 2016), ('后半(2017-2026)', yrs[ok] > 2016)):
        print(f'     {lab}: IC {ic(pr[ok][msk], tgt[ok][msk]):+.3f}')
