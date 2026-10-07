"""D account simulator v5: dynamic sleeve priority, unified ranking, confluence / depth weights, regime tilts, exclusive tiers, reserves, tranche entries. Research only.
Default arguments reproduce lib70.fused4 exactly."""
import numpy as np
import lib70 as L
import lib72 as M
from lib70 import O, C, F, fee, buyok, nd, dates, yr, W0, baseline_exit
GATE = L.GATE; POOL = L.POOL
# z depth (window 20), aligned to c70
zA = M.mkt_z(20); zI = M.grp_z(M.Ri, 20); zQ = M.grp_z(M.Rq, 20); l1 = M.l1; lab = M.lab
zmin = {'A': zA, 'B': np.where(np.isfinite(zI), zI, np.inf).min(1), 'C': np.where(np.isfinite(zQ), zQ, np.inf).min(1)}
EPS = {s: np.array([bool(GATE[s][t]) and not bool(np.any(GATE[s][max(0, t - 5):t])) for t in range(nd)]) for s in 'ACB'}
ENTRIES = []
_LOW = []
def _low():
    if not _LOW:
        z = np.load('c72/lowhigh.npz'); _LOW.append(np.asarray(z['lo'], np.float32)[:nd][:, M.cols])
    return _LOW[0]
def zstock(s, t, j):
    if s == 'A': return zA[t]
    if s == 'B': return zI[t, l1[j]]
    k = lab[t, j]; return zQ[t, k] if k >= 0 else np.nan
def fused5(rank='r20', N=20, H=20, W=None, G=1.0, cash_yield=0.02, start='2008-01-01', end=None, sleeves='ACB', order=None, unified=False, urank=None,
           confl=None, cpar=0.0, wfun=None, caps=None, gfun=None, excl=None, tr=None, log=None, seed=0, diag=None, lim=None, pyr=None, rank_s=None):
    W = dict(W or W0); rk = L.get_rank(rank, seed) if isinstance(rank, str) else rank; RS = {k: L.get_rank(v) for k, v in rank_s.items()} if rank_s else {}; ur = rk if urank is None else (L.get_rank(urank) if isinstance(urank, str) else urank)
    t0 = int(np.searchsorted(dates, start)); tend = nd - 1 if end is None else int(np.searchsorted(dates, end, side='right')) - 1
    cash = 1.0; active = []; eq = np.full(nd, np.nan); expo = np.zeros(nd); trades = []; nclip = 0; natt = 0
    for t in range(t0, tend + 1):
        # pending tranche entries
        for p in [p for p in active if p.get('pend') and p['e'] == t]:
            if not (buyok[t - 1][p['j']] and np.isfinite(O[t, p['j']])): cash += p['inv']; active.remove(p); continue
            if p.get('lim') is not None:
                x, fb = p['lim']; o = float(O[t, p['j']]); lw = float(_low()[t, p['j']])
                if np.isfinite(lw) and lw <= (1 - x) - 0.002: px = o * (1 - x)
                elif fb == 'close' and np.isfinite(C[t, p['j']]): px = float(C[t, p['j']])
                else: cash += p['inv']; active.remove(p); continue
                p['pend'] = False; p['o0'] = px; p['last'] = px; _fin(p, t); continue
            p['pend'] = False; p['o0'] = float(O[t, p['j']]); p['last'] = p['o0']; _fin(p, t)
        for p in [p for p in active if p['x'] == t and p['net'] is not None and not p.get('pend')]:
            cash += p['inv'] * (1 + p['net']); trades.append((p['s'], p['net'], p['x'] - p['e'] + 1)); active.remove(p)
        if t + 1 <= min(tend, nd - 1):
            held = {p['j'] for p in active}
            act = [s for s in sleeves if GATE[s][t]]
            if excl is not None: act = excl(t, act)
            if order is not None: act = order(t, act)
            cand = []   # (s, j) in allocation order
            mem = {}
            if unified or confl:
                for s in act:
                    n_s = sum(1 for p in active if p['s'] == s and not p.get('sub'))
                    if n_s >= N and not confl: continue
                    for j in np.nonzero(POOL[s][t] & buyok[t])[0]:
                        if int(j) in held: continue
                        mem.setdefault(int(j), []).append(s)
            if unified:
                lab_of = {j: ss[0] for j, ss in mem.items()}   # first sleeve in `act` order that contains it
                js = np.array(list(lab_of), dtype=int)
                if len(js):
                    v = np.asarray(ur[t, js], np.float64); v = np.where(np.isfinite(v), v, np.inf); js = js[np.argsort(v, kind='stable')]
                    cand = [(lab_of[int(j)], int(j)) for j in js]
            else:
                for s in act:
                    n_s = sum(1 for p in active if p['s'] == s and not p.get('sub'))
                    if n_s >= N: continue
                    pool = np.nonzero(POOL[s][t] & buyok[t])[0]; pool = np.array([j for j in pool if j not in held], dtype=int)
                    if not len(pool): continue
                    v = np.asarray(RS.get(s, rk)[t, pool], np.float64); v = np.where(np.isfinite(v), v, np.inf); pool = pool[np.argsort(v, kind='stable')]
                    cand.extend((s, int(j)) for j in pool[:N - n_s])
            if cand:
                invested = sum(p['v'] for p in active); equity = cash + invested; cnt = {s: sum(1 for p in active if p['s'] == s and not p.get('sub')) for s in 'ACB'}
                invs = {s: sum(p['v'] for p in active if p['s'] == s) for s in 'ACB'}
                for s, j in cand:
                    if j in held or cnt[s] >= N: continue
                    w = W[s]
                    if confl and j in mem:
                        ws = [W[x] for x in mem[j]]
                        w = sum(ws) if confl == 'sum' else max(ws) if confl == 'max' else W[s] * (1 + cpar * (len(ws) - 1))
                    if wfun is not None: w = w * wfun(s, t, j)
                    gc = G if gfun is None else gfun(t, s)
                    size = min(w * equity, gc * equity - invested)
                    if caps and s in caps: size = min(size, caps[s] * equity - invs[s])
                    natt += 1
                    if diag is not None and EPS[s][t]:
                        diag['des'][s] += w * equity; diag['got'][s] += max(size, 0.0); diag['n'][s] += 1
                    if size < w * equity - 1e-12: nclip += 1
                    if size <= 1e-9: continue
                    cash -= size; invested += size; invs[s] += size; cnt[s] += 1; held.add(j)
                    rf = _enter(active, s, j, t, size, H[s] if isinstance(H, dict) else H, tr, lim, pyr) or 0.0
                    if rf: cash += rf; invested -= rf; invs[s] -= rf
        if pyr is not None and t + 1 <= min(tend, nd - 1):
            for p in list(active):
                if p.get('pend') or p.get('added') or 'plan' not in p or p['e'] > t or t - p['e'] > pyr.get('maxd', 10): continue
                j = p['j']
                if pyr['mode'] == 'px': hit = np.isfinite(C[t, j]) and C[t, j] / p['o0'] - 1 <= -pyr['x']
                else: zz = zstock(p['s'], t, j); hit = np.isfinite(zz) and zz <= p['z0'] - pyr['delta']
                if not hit or not buyok[t][j]: continue
                invested = sum(q['v'] for q in active); equity = cash + invested; a = min(p['plan'], G * equity - invested)
                if a <= 1e-9: continue
                p['added'] = True; cash -= a
                active.append(dict(j=j, s=p['s'], e=t + 1, inv=a, v=a, net=None, H=p['H'], xsig=p['xsig'], x=t + 1 + p['H'], o0=1.0, last=1.0, cost_e=0.0, pend=True, sub=True))
        if cash > 0 and cash_yield > 0: cash += cash * cash_yield / 242.0
        vs = 0.0
        for p in active:
            if p['e'] <= t and not p.get('pend'):
                ct = C[t, p['j']]
                if np.isfinite(ct): p['last'] = float(ct)
                p['v'] = p['inv'] * (p['last'] / p['o0']) * (1 - p['cost_e'])
            vs += p['v']
        tot = cash + vs; eq[t] = tot; expo[t] = vs / max(tot, 1e-9)
    if log is not None: log.extend(trades)
    return eq, expo, trades, (nclip, natt)
def _fin(p, t):
    j = p['j']; e = p['e']; o0 = p['o0']; raw_e = o0 / float(F[e, j]); ex = baseline_exit(j, p['xsig'], p['H']); H = p['H']
    p['x'] = ex[0] if ex else p['xsig'] + H
    if ex is not None:
        xi, px = ex; raw_x = px / float(F[xi, j]); p['net'] = (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee[xi]; p['cost_e'] = 0.01 / raw_e + fee[xi] / 2
    else: p['cost_e'] = 0.01 / raw_e + fee[min(p['xsig'] + H, nd - 1)] / 2
def _enter(active, s, j, t, size, H, tr, lim, pyr):
    ENTRIES.append((s, j, t + 1))
    if lim is not None and s in lim.get('sleeves', 'ACB'):
        fr = lim['frac']; e = t + 1
        if e >= nd: return
        for i, part in enumerate((1 - fr, fr)):
            if part <= 0: continue
            p = dict(j=j, s=s, e=e, inv=size * part, v=size * part, net=None, H=H, xsig=t, x=e + H, o0=float(O[e, j]) if np.isfinite(O[e, j]) else 1.0, last=1.0, cost_e=0.0, pend=(i == 1), sub=(i == 1), lim=(lim['x'], lim.get('fb', 'skip')) if i == 1 else None)
            if i == 0: p['last'] = p['o0']; _fin(p, t)
            active.append(p)
        return
    if pyr is not None and s in pyr.get('sleeves', 'ACB'):
        fr = pyr['frac']; e = t + 1
        if e >= nd: return
        p = dict(j=j, s=s, e=e, inv=size * (1 - fr), v=size * (1 - fr), net=None, H=H, xsig=t, x=e + H, o0=float(O[e, j]) if np.isfinite(O[e, j]) else 1.0, last=1.0, cost_e=0.0, pend=False, plan=size * fr, z0=zstock(s, t, j))
        p['last'] = p['o0']; _fin(p, t); active.append(p); return size * fr
    k = 1 if tr is None or s not in tr.get('sleeves', 'ACB') else int(tr['k']); gap = 1 if tr is None else int(tr.get('gap', 1)); own = tr is not None and tr.get('exit', 'common') == 'own'
    fr = [1.0 / k] * k if tr is None or 'fr' not in tr or k == 1 else list(tr['fr'])
    for i in range(k):
        e = t + 1 + i * gap
        if e >= nd: break
        p = dict(j=j, s=s, e=e, inv=size * fr[i], v=size * fr[i], net=None, H=H, xsig=(e - 1 if own else t), x=e + H, o0=float(O[e, j]) if np.isfinite(O[e, j]) else 1.0, last=1.0, cost_e=0.0, pend=(i > 0), sub=(i > 0))
        if i == 0:
            p['last'] = p['o0']; _fin(p, t)
        active.append(p)
def run(label=None, **kw):
    eq, ex, trades, cl = fused5(**kw); st = L.stats(eq, ex, trades); st['clip'] = cl[0] / max(cl[1], 1); return st
