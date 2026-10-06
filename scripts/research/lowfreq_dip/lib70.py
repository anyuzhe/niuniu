"""Fast D account simulator with pluggable ranking and dynamic exits; loads from c70/*.npy. Research only."""
import numpy as np, os, json, time
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'c70') + '/'
L = lambda n, mm='r': np.load(D + n + '.npy', mmap_mode=mm)
dates = L('dates', None); nd = len(dates); O, C, F = L('O'), L('C'), L('F'); fee = L('fee', None); buyok = L('buyok')
GATE = {s: L('gate' + s) for s in 'ACB'}; POOL = {s: L('pool' + s) for s in 'ACB'}; R20 = L('r20A'); MZ = L('mz', None)
SIG = L('sig60'); DIST = L('distma20'); yr = np.array([int(d[:4]) for d in dates]); nc = C.shape[1]
W0 = {'A': .08, 'C': .08, 'B': .025}
_cache = {}
def get_rank(name, seed=0):
    key = (name, seed) if name == 'rand' else name
    if key in _cache: return _cache[key]
    if name == 'r20': a = R20
    elif name == 'r5': a = L('r5')
    elif name == 'zown': a = np.asarray(R20, np.float32) / (np.asarray(SIG, np.float32) * np.sqrt(20) + 1e-9)
    elif name == 'dd60': a = L('dd60')
    elif name == 'dma20': a = DIST
    elif name == 'volhi': a = -np.asarray(L('volratio'), np.float32)
    elif name == 'vollo': a = L('volratio')
    elif name == 'ret1': a = L('ret1')
    elif name == 'sighi': a = -np.asarray(SIG, np.float32)
    elif name == 'siglo': a = SIG
    elif name == 'rand': a = np.random.default_rng(seed).random((nd, nc), dtype=np.float32)
    elif name[0] == 'r' and name[1:].isdigit():
        k = int(name[1:]); a = np.full((nd, nc), np.nan, np.float32); a[k:] = np.asarray(C[k:], np.float32) / np.asarray(C[:-k], np.float32) - 1
    elif name == 'comb':
        def rk(x): return np.argsort(np.argsort(np.where(np.isfinite(x), x, np.inf), 1, kind='stable'), 1).astype(np.float32)
        a = rk(np.asarray(R20, np.float32)) + rk(np.asarray(DIST, np.float32))
    else: raise KeyError(name)
    _cache[key] = a; return a
def tradable_open(k, j, d):
    o = float(O[k, j]); return np.isfinite(o) and o > 0 and (not np.isfinite(C[d, j]) or o / float(C[d, j]) - 1 > -0.095)
def baseline_exit(j, t, H):
    x0 = t + H
    for k in range(4):
        i = x0 + k
        if i >= nd: return None
        if np.isfinite(C[i, j]): return i, float(C[i, j])
    for i in range(x0 - 1, -1, -1):
        if np.isfinite(C[i, j]): return x0, float(C[i, j])
    return None
PRED = {}
FE_PRED = ['r20', 'r5', 'zown', 'dd60', 'dma20', 'volratio', 'sig60', 'ret1', 'mz', 'sleeveA', 'sleeveC']
def feat_vec(t, j, s):
    sg = float(SIG[t, j]); r20 = float(R20[t, j])
    return np.array([r20, float(L('r5')[t, j]), r20 / (sg * np.sqrt(20) + 1e-9), float(L('dd60')[t, j]), float(DIST[t, j]), float(L('volratio')[t, j]), sg, float(L('ret1')[t, j]), float(MZ[t]), float(s == 'A'), float(s == 'C')])
def set_pred(X, col):
    """walk-forward ridge: year y uses all rows with year < y. col = -2 run-up, -3 net."""
    yrs = X[:, 1].astype(int); F = X[:, 2:2 + len(FE_PRED)]; y = X[:, col]
    for yy in range(2012, 2027):
        tr = yrs < yy
        mu, sd = F[tr].mean(0), F[tr].std(0) + 1e-9; Z = (F[tr] - mu) / sd
        b = np.linalg.solve(Z.T @ Z + 50.0 * np.eye(Z.shape[1]), Z.T @ (y[tr] - y[tr].mean())); PRED[yy] = (mu, sd, b, float(y[tr].mean()))
def pred_value(t, j, s):
    p = PRED.get(int(yr[t]))
    if p is None: return np.nan
    v = feat_vec(t, j, s)
    if not np.isfinite(v).all(): return np.nan
    mu, sd, b, m0 = p; return m0 + float(((v - mu) / sd) @ b)
def dyn_exit(rules, j, e, t, o0, H, s=None):
    """first trigger (decision at close d, exit at next tradable open). returns (xi, px) or None."""
    dmax = t + H - 1; dmin = e + 1
    if dmax < dmin: return None
    path = np.asarray(C[dmin - 1:dmax + 1, j], np.float64); days = np.arange(dmin - 1, dmax + 1)   # includes close of day e (index 0)
    ret = path / o0 - 1; hit = np.zeros(len(path), bool)
    for kind, *p in rules:
        if kind == 'target': hit |= ret >= p[0]
        elif kind == 'volt':
            s = float(SIG[t, j]) if np.isfinite(SIG[t, j]) else np.nan
            if np.isfinite(s): hit |= ret >= p[0] * s * np.sqrt(20)
        elif kind == 'ma20':
            h = np.asarray(DIST[dmin - 1:dmax + 1, j], np.float64) >= p[0]; h[:max(p[1], 0)] = False; hit |= h
        elif kind == 'recover':
            pre = float(C[t - 20, j]) if t >= 20 else np.nan; ref = float(C[t, j])
            if np.isfinite(pre) and pre > ref > 0: hit |= (path - ref) / (pre - ref) >= p[0]
        elif kind == 'mz':
            h = MZ[dmin - 1:dmax + 1] >= p[0]; h[:max(p[1], 0)] = False; hit |= np.nan_to_num(h, nan=0).astype(bool)
        elif kind == 'trail':
            pk = np.maximum.accumulate(path); hit |= ((pk / o0 - 1) >= p[0]) & (path <= pk * (1 - p[1]))
        elif kind == 'stop': hit |= ret <= -p[0]
        elif kind == 'predt':
            pv = pred_value(t, j, s)
            if np.isfinite(pv): hit |= ret >= max(p[0] * pv, p[1])
    hit[0] = hit[0] and False if False else hit[0]
    for k in np.nonzero(hit)[0]:
        d = int(days[k])
        for kk in (d + 1, d + 2, d + 3):
            if kk <= min(t + H, nd - 1) and tradable_open(kk, j, d): return kk, float(O[kk, j])
        break
    return None
def fused4(rank='r20', rules=None, N=20, H=20, W=None, G=1.0, cash_yield=0.02, start='2008-01-01', end=None, quota=None, seed=0, sleeves='ACB', log=None):
    W = W or W0; rk = get_rank(rank, seed) if isinstance(rank, str) else rank
    t0 = int(np.searchsorted(dates, start)); tend = nd - 1 if end is None else int(np.searchsorted(dates, end, side='right')) - 1
    cash = 1.0; active = []; eq = np.full(nd, np.nan); expo = np.zeros(nd); ntr = 0; trades = []
    for t in range(t0, tend + 1):
        for p in [p for p in active if p['x'] == t and p['net'] is not None]:
            cash += p['inv'] * (1 + p['net']); trades.append((p['s'], p['net'], p['x'] - p['e'] + 1)); active.remove(p)
        if t + 1 <= min(tend, nd - 1):
            held = {p['j'] for p in active}
            for s in sleeves:
                if not GATE[s][t]: continue
                n_s = sum(1 for p in active if p['s'] == s)
                if n_s >= N: continue
                pool = np.nonzero(POOL[s][t] & buyok[t])[0]
                pool = np.array([j for j in pool if j not in held], dtype=int)
                if not len(pool): continue
                v = np.asarray(rk[t, pool], np.float64); v = np.where(np.isfinite(v), v, np.inf); pool = pool[np.argsort(v, kind='stable')]
                invested = sum(p['v'] for p in active); equity = cash + invested
                for j in pool[:min(N - n_s, quota or N)]:
                    size = min(W[s] * equity, G * equity - invested)
                    if size <= 1e-9: break
                    cash -= size; invested += size; e = t + 1; o0 = float(O[e, j]); raw_e = o0 / float(F[e, j])
                    ex = dyn_exit(rules, int(j), e, t, o0, H, s) if rules else None
                    if ex is None: ex = baseline_exit(int(j), t, H)
                    pos = dict(j=int(j), s=s, e=e, x=ex[0] if ex else t + H, inv=size, v=size, o0=o0, net=None, last=o0)
                    if ex is not None:
                        xi, px = ex; raw_x = px / float(F[xi, j])
                        pos['net'] = (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee[xi]; pos['cost_e'] = 0.01 / raw_e + fee[xi] / 2
                    else: pos['cost_e'] = 0.01 / raw_e + fee[min(t + H, nd - 1)] / 2
                    active.append(pos); held.add(int(j)); ntr += 1
        if cash > 0 and cash_yield > 0: cash += cash * cash_yield / 242.0
        vs = 0.0
        for p in active:
            if p['e'] <= t:
                ct = C[t, p['j']]
                if np.isfinite(ct): p['last'] = float(ct)
                p['v'] = p['inv'] * (p['last'] / p['o0']) * (1 - p['cost_e'])
            vs += p['v']
        tot = cash + vs; eq[t] = tot; expo[t] = vs / max(tot, 1e-9)
    if log is not None: log.extend(trades)
    return eq, expo, trades
def stats(eq, expo, trades=None, t0=None):
    r = np.full(nd, np.nan); r[1:] = eq[1:] / eq[:-1] - 1; m = np.isfinite(r); x = r[m]; cum = np.cumprod(1 + x); n = len(x)
    out = dict(cagr=float(cum[-1] ** (245 / n) - 1), sharpe=float(x.mean() / x.std() * np.sqrt(245)), dd=float((cum / np.maximum.accumulate(cum) - 1).min()), expo=float(np.nanmean(expo[m])), final=float(cum[-1]))
    for k, (a, b) in enumerate(((2008, 2016), (2017, 2026))):
        kk = (yr >= a) & (yr <= b) & m; y = r[kk]; out['h%d' % (k + 1)] = float(np.prod(1 + y) ** (245 / len(y)) - 1) if len(y) > 20 else None
    if trades:
        out['ntr'] = len(trades); out['hold'] = float(np.mean([t[2] for t in trades])); out['tret'] = float(np.mean([t[1] for t in trades]))
        for s in 'ACB':
            z = [t for t in trades if t[0] == s]; out['n' + s] = len(z); out['m' + s] = float(np.mean([t[1] for t in z])) if z else None
    return out
