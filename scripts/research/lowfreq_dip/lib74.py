"""Extra ranking / filtering / weighting inputs for the D account (lib73.fused5). Research only."""
import numpy as np, pandas as pd
import lib70 as L, lib72 as M, lib73 as X
nd = L.nd; R20 = np.asarray(L.R20, np.float32)
def grp20(R):
    out = np.full(R.shape, np.nan)
    for g in range(R.shape[1]):
        s = pd.Series(R[:, g]); out[:, g] = (np.exp(np.log1p(s).rolling(20, min_periods=20).sum()) - 1).to_numpy()
    return out
gI20 = grp20(M.Ri); gQ20 = grp20(M.Rq)
idx = np.cumprod(1 + M.mret); mk20 = np.full(nd, np.nan); mk20[20:] = idx[20:] / idx[:-20] - 1
def stock_grp(s):
    """per-stock group value arrays for sleeve s: (z, r20)"""
    if s == 'A':
        return np.broadcast_to(X.zA[:, None], R20.shape), np.broadcast_to(mk20[:, None], R20.shape)
    if s == 'B':
        return X.zI[:, X.l1], gI20[:, X.l1]
    z = np.full(R20.shape, np.nan, np.float64); r = np.full(R20.shape, np.nan, np.float64)
    for k in range(5):
        m = X.lab == k; z = np.where(m, X.zQ[:, k:k + 1], z); r = np.where(m, gQ20[:, k:k + 1], r)
    return z, r
_cache = {}
def rel20(s):
    if ('rel', s) not in _cache:
        z, r = stock_grp(s); _cache[('rel', s)] = (R20 - np.asarray(r, np.float32)).astype(np.float32)
    return _cache[('rel', s)]
def zgrp_key(s):
    if ('zg', s) not in _cache:
        z, r = stock_grp(s); _cache[('zg', s)] = (np.asarray(z, np.float32) * 100 + R20).astype(np.float32)
    return _cache[('zg', s)]
RET1 = np.asarray(L.L('ret1'), np.float32); VR = np.asarray(L.L('volratio'), np.float32); DD60 = np.asarray(L.L('dd60'), np.float32); DMA = np.asarray(L.L('distma20'), np.float32); SIG = np.asarray(L.SIG, np.float32); R5 = np.asarray(L.L('r5'), np.float32)
C_ = L.C; O_ = L.O; F_ = L.F; fee = L.fee
FN = ['r20', 'r5', 'ret1', 'ret2', 'dd60', 'dma20', 'volratio', 'sig60', 'zgrp', 'rel20', 'posr20', 'mz']
def rows(topk=60, start='2007-06-01', sleeves='CBA'):
    """candidate rows on gate days: top-k by r20 per sleeve pool; label = realised net of buying next open and exiting at the baseline 20d exit."""
    t0 = int(np.searchsorted(L.dates, start)); out = []
    zc = {s: stock_grp(s) for s in sleeves}
    for t in range(max(t0, 70), nd - 25):
        seen = {}
        for s in sleeves:
            if not L.GATE[s][t]: continue
            pool = np.nonzero(L.POOL[s][t] & L.buyok[t])[0]
            if not len(pool): continue
            v = R20[t, pool]; ok = np.isfinite(v); pool = pool[ok]; v = v[ok]
            o = np.argsort(v, kind='stable')[:topk]
            for r, j in enumerate(pool[o]):
                seen.setdefault(int(j), dict(s={}, pos={}))['s'][s] = 1; seen[int(j)]['pos'][s] = r / max(len(o) - 1, 1)
        for j, d in seen.items():
            e = t + 1; o0 = float(O_[e, j]); ex = L.baseline_exit(j, t, 20)
            if not np.isfinite(o0) or ex is None: continue
            xi, px = ex; raw_e = o0 / float(F_[e, j]); raw_x = px / float(F_[xi, j]); y = (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee[xi]
            s0 = 'C' if 'C' in d['s'] else ('B' if 'B' in d['s'] else 'A'); z, rg = zc[s0][0][t, j], zc[s0][1][t, j]
            c = C_[t:t + 1, j][0]; c1 = C_[t - 1, j]; c2 = C_[t - 2, j]
            out.append((t, j, 'A' in d['s'], 'B' in d['s'], 'C' in d['s'], R20[t, j], R5[t, j], RET1[t, j], (c / c2 - 1) if np.isfinite(c) and np.isfinite(c2) else np.nan, DD60[t, j], DMA[t, j], VR[t, j], SIG[t, j], z, R20[t, j] - rg, d['pos'][s0], L.MZ[t], y))
    return np.array(out, dtype=np.float64)
def two_stage(s, K, feat):
    """key array: among top-K by r20 within the sleeve pool, order by feat ascending; others +inf."""
    key = np.full(R20.shape, np.inf, np.float32)
    for t in np.nonzero(np.asarray(L.GATE[s]))[0]:
        pool = np.nonzero(L.POOL[s][t] & L.buyok[t])[0]
        if not len(pool): continue
        v = R20[t, pool]; ok = np.isfinite(v); pool = pool[ok]; v = v[ok]; o = np.argsort(v, kind='stable')[:K]; sel = pool[o]
        f = np.asarray(feat[t, sel], np.float64); f = np.where(np.isfinite(f), f, np.inf); key[t, sel] = f
    return key
def rankn(a):
    """within-day rank (0..1) of an [nd,nc] array's finite entries is expensive; use per-row percentiles on demand"""
    return a
def learned(rows_, folds_from=2011, lam=30.0, extra=True, ycol='y', clipy=(-0.6, 1.5), feat_idx=None):
    cols = ['t','j','A','B','C'] + FN + ['y']; D = {c: rows_[:, i] for i, c in enumerate(cols)}
    t = D['t'].astype(int); j = D['j'].astype(int); y = np.clip(D['y'], *clipy)
    Xf = [D[f] for f in FN] + [D['A'], D['B'], D['C']]
    if extra: Xf += [D['ret1'] ** 2, np.abs(D['ret1']), D['dd60'] ** 2]
    Xf = np.nan_to_num(np.column_stack(Xf).astype(np.float64), nan=0.0)
    ys = np.array([dt[:4] for dt in L.dates[t]], dtype=int)
    SC = np.full(R20.shape, np.inf, np.float32)
    for yy in range(folds_from, 2027):
        tr = ys < yy; tr &= (t + 25 < int(np.searchsorted(L.dates, f'{yy}-01-01'))); te = ys == yy
        if tr.sum() < 5000 or te.sum() == 0: continue
        mu, sd = Xf[tr].mean(0), Xf[tr].std(0) + 1e-9; Z = (Xf[tr] - mu) / sd; b = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y[tr] - y[tr].mean()))
        SC[t[te], j[te]] = -(((Xf[te] - mu) / sd) @ b).astype(np.float32)
    return SC
