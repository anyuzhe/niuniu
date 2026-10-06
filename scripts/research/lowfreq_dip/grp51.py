"""Data for the D dashboard (fresh panel through the latest lake day): gates, signal state, nav, metrics, yearly, sleeve stats, trigger episodes. Research only."""
import json, grp11 as g
from grp11 import *
import quantlab.dipbuy.industry as I
W = {'A': .08, 'C': .08, 'B': .025}
zC = inputs(panel, cfg1, lab, 'any')[2][0]          # (nd,5) quintile z
Rn, _a = ind_series(l1); Zn = zscore(Rn)
names = I.SW_L1
t_last = nd - 1
def f(x, d=3): return None if (x is None or not np.isfinite(x)) else round(float(x), d)
# --- gate history (last 90 trading days)
hist = []
for t in range(nd - 90, nd):
    zi = Zn[t]; ii = int(np.nanargmin(np.where(np.isfinite(zi), zi, 9))) if np.isfinite(zi).any() else None
    zc = zC[t]; ci = int(np.nanargmin(np.where(np.isfinite(zc), zc, 9))) if np.isfinite(zc).any() else None
    hist.append(dict(d=dates[t], zA=f(market.z[t]), zB=f(zi[ii]) if ii is not None else None, nB=names.get(u[ii], u[ii]) if ii is not None else None, zC=f(zc[ci]) if ci is not None else None, qC=ci, gA=bool(gateA[t]), gB=bool(gateB[t]), gC=bool(gateC[t])))
# --- latest detail
ind_rows = []
for i in np.argsort(np.where(np.isfinite(Zn[t_last]), Zn[t_last], 9))[:10]:
    r20 = float(np.expm1(np.log1p(np.nan_to_num(Rn[max(0, t_last - 19):t_last + 1, i])).sum()))
    ind_rows.append(dict(name=names.get(u[i], u[i]), z=f(Zn[t_last, i]), r20=f(r20, 4)))
q_rows = [dict(q=int(k), z=f(zC[t_last, k])) for k in range(5)]
pools = {s: int((e6[t_last] & buyok[t_last]).sum()) for s, (gate, e6, r20) in g.SL.items()}
# --- fused backtest
eq, ex, ntr, pnl, wsum, minr = g.fused(order='ACB', w=W, G=1.0, caps={}, cash_yield=0.02)
r = dr(eq); m = np.isfinite(r); x = r[m]; cum = np.cumprod(1 + x); n = len(x)
cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = cum / np.maximum.accumulate(cum) - 1
d_ = np.array(dates)[m]
mk = np.nan_to_num(market.mret)[m]; bm = np.cumprod(1 + mk)
yrs = np.array([int(s[:4]) for s in d_]); yret = {}
for y in sorted(set(yrs)): yy = x[yrs == y]; by = mk[yrs == y]; yret[int(y)] = dict(d=f(np.prod(1 + yy) - 1, 4), m=f(np.prod(1 + by) - 1, 4), expo=f(np.nanmean(ex[m][yrs == y]), 3))
step = 2
nav = dict(d=[s for s in d_[::step]] + ([d_[-1]] if (len(d_) - 1) % step else []), v=[f(v, 4) for v in list(cum[::step]) + ([cum[-1]] if (len(d_) - 1) % step else [])],
           bm=[f(v / bm[0], 4) for v in list(bm[::step]) + ([bm[-1]] if (len(d_) - 1) % step else [])],
           dd=[f(v, 4) for v in list(dd[::step]) + ([dd[-1]] if (len(d_) - 1) % step else [])], ex=[f(v, 3) for v in list(ex[m][::step]) + ([ex[m][-1]] if (len(d_) - 1) % step else [])])
# --- trigger episodes (union of gates), with first-day top-20 candidate 20d net return
O, C = panel.o.astype(np.float64), panel.c.astype(np.float64); H = 20; COST = 0.003
t0 = int(np.searchsorted(dates, '2008-01-01'))
anyg = (gateA | gateB | gateC); days = [t for t in range(t0, nd) if anyg[t]]
eps = []; cur = [days[0]]
for t in days[1:]:
    if t - cur[-1] > 5: eps.append(cur); cur = [t]
    else: cur.append(t)
eps.append(cur)
def ev(t, s):
    gate, e6, r20 = g.SL[s]
    pool = np.nonzero(e6[t] & buyok[t])[0]
    if not len(pool): return None, 0
    pick = pool[np.argsort(r20[t, pool], kind='stable')[:20]]
    if t + 1 + H >= nd: return None, len(pick)
    xs = [C[t + H, j] / O[t + 1, j] - 1 - COST for j in pick if np.isfinite(O[t + 1, j]) and np.isfinite(C[t + H, j])]
    return (float(np.mean(xs)) if xs else None), len(pick)
E = []
for e in eps:
    a = {s: bool(g.SL[s][0][e].any()) for s in 'ABC'}
    res = {}
    for s in 'ABC':
        if a[s]:
            td = [t for t in e if g.SL[s][0][t]][0]; v, k = ev(td, s); res[s] = dict(first=dates[td], ret=f(v, 4), n=k)
    E.append(dict(start=dates[e[0]], end=dates[e[-1]], days=len(e), fired=''.join(s for s in 'ABC' if a[s]), res=res))
last_fire = {s: (dates[max(np.nonzero(g.SL[s][0])[0])]) for s in 'ABC'}

# --- candidates for the latest day (only filled when a gate is open)
cands = {}
for s_, (gate, e6, r20) in g.SL.items():
    if gate[t_last]:
        pool = np.nonzero(e6[t_last] & buyok[t_last])[0]
        pick = pool[np.argsort(r20[t_last, pool], kind='stable')[:20]]
        cands[s_] = [dict(code=str(panel.codes[j]), r20=f(r20[t_last, j], 4), close=f(float(panel.c[t_last, j]) / float(panel.f[t_last, j]), 2)) for j in pick]
sl = {s: dict(n=int(ntr[s]), avg_bp=f(pnl[s] / max(ntr[s], 1) * 1e4, 0), w=W[s]) for s in 'ABC'}
out = dict(asof=dates[t_last], n_days=int(nd), thr=-1.5, nav=nav, yearly=yret, hist=hist, ind=ind_rows, q=q_rows, pools=pools, sleeves=sl, episodes=E, cands=cands, last_fire=last_fire,
           metrics=dict(cagr=f(cagr, 4), sharpe=f(sh, 2), maxdd=f(dd.min(), 4), mdd_date=str(d_[int(np.argmin(dd))]), expo=f(np.nanmean(ex[m]), 3), start=str(d_[0]), end=str(d_[-1]), final=f(cum[-1], 2), bm_final=f(bm[-1] / bm[0], 2)),
           gate_days=dict(A=int(gateA[t0:].sum()), B=int(gateB[t0:].sum()), C=int(gateC[t0:].sum())))
json.dump(out, open('D_dash.json', 'w'), ensure_ascii=False, separators=(',', ':'))
met(r, 'D (fresh panel)', ex)
print('asof', out['asof'], 'episodes', len(E), 'json bytes', os.path.getsize('D_dash.json'), flush=True)
print(out['metrics'], sl, pools, last_fire, flush=True)
print('最近 5 段:', [(e['start'], e['end'], e['fired'], {k: v['ret'] for k, v in e['res'].items()}) for e in E[-5:]], flush=True)
