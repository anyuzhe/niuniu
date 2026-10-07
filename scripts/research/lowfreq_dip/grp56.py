"""D at 14:55: decide with the 14:55 price (SIG=c55) and trade at the closing auction (true close). Research only.
SIG=true: decide with the true close (infeasible reference).  Window: 2020-03 on (5-minute data starts 2020-01)."""
import os, sys, json
import numpy as np
import grp_lib
SIG = os.environ.get('SIG', 'c55')
_orig = grp_lib.load_panel
def _lp():
    p = _orig(); z = np.load(os.environ.get('C55FILE', 'c55.npz'), allow_pickle=True)
    c55 = z['c55']
    if os.environ.get('DROPDEL') == '1': c55 = c55[:, ~np.load(os.environ['PANEL_NPZ'], allow_pickle=True)['isdel'].astype(bool)]
    assert p.shape == c55.shape, (p.shape, c55.shape)
    p.meta['c_true'] = p.c.copy()
    if SIG == 'c55':
        a = c55.astype(np.float64) * p.f.astype(np.float64)
        p.c = np.where(np.isfinite(a), a, p.c.astype(np.float64)).astype(np.float32)
        p.meta['c55ok'] = np.isfinite(a)
    return p
grp_lib.load_panel = _lp
import grp11 as g
from grp11 import *
from quantlab.dipbuy.engine import _exit_index
Ct = panel.meta['c_true'].astype(np.float64); ok55 = panel.meta.get('c55ok', np.isfinite(Ct))
Cs = panel.c.astype(np.float64)                     # signal-time price (14:55 or true close)
prevC = np.vstack([np.full((1, nc), np.nan), Ct[:-1]])
chg = Cs / prevC - 1
canbuy = ok55 & np.isfinite(Ct) & (chg < 0.095)      # not at limit-up at decision time
cansell = ok55 & np.isfinite(Ct) & (chg > -0.095)    # not locked at limit-down
if os.environ.get('BAN'):
    for _j in os.environ['BAN'].split(','): canbuy[:, int(_j)] = False
T0 = int(np.searchsorted(dates, '2020-03-02'))
W0 = {'A': .08, 'C': .08, 'B': .025}
def fused3(order='ACB', w=W0, G=1.0, N=20, H=20, cash_yield=0.02, evict=None, ecost=0.0, entry='close', evlog=None, tlog=None, minage=0):
    evict = evict or {}; cash = 1.0; active = []; eq = np.full(nd, np.nan); expo = np.zeros(nd); ev = 0; ntr = 0
    for t in range(T0, nd):
        for p in [p for p in active if p['x'] == t and p['net'] is not None]:
            cash += p['inv'] * (1 + p['net']); active.remove(p)
            if tlog is not None: tlog.append((p['s'], p['net'], p['x'] - p['e'], p['j'], p['e']))
        held = {p['j'] for p in active}
        for s in order:
            gate, e6, r20 = SL[s]
            if not gate[t]: continue
            n_s = sum(1 for p in active if p['s'] == s)
            if n_s >= N: continue
            pool = np.nonzero(e6[t] & canbuy[t])[0]
            pool = np.array([j for j in pool if j not in held], dtype=int)
            if not len(pool): continue
            pool = pool[np.argsort(r20[t, pool], kind='stable')]
            invested = sum(p['v'] for p in active); equity = cash + invested
            want = min(N - n_s, len(pool)); ideal = want * w[s] * equity; room = G * equity - invested
            if evict.get(s) and room < ideal - 1e-9:
                need = ideal - room
                for p in sorted([p for p in active if p['s'] in evict[s] and p['e'] <= t - minage and cansell[t, p['j']]], key=lambda p: p['e']):
                    if need <= 1e-9: break
                    j = p['j']; rx = Ct[t, j] / float(F_[t, j])
                    cash += p['v'] * (1 - 0.01 / rx - fee[t] / 2 - ecost); need -= p['v']
                    if evlog is not None: evlog.append((t, s, p['s'], t - p['e'], p['v'] / p['inv'] - 1, p['net'], p['v'] / p['inv'] - 1 - 0.01 / rx - fee[t] / 2))
                    active.remove(p); held.discard(j); ev += 1
                invested = sum(p['v'] for p in active); equity = cash + invested
            for j in pool[:N - n_s]:
                size = min(w[s] * equity, G * equity - invested)
                if size <= 1e-9: break
                cash -= size; invested += size
                if entry == 'close':
                    e = t; o0 = Ct[t, j]
                else:                                   # reference: next-open entry
                    if t + 1 >= nd: cash += size; invested -= size; continue
                    e = t + 1; o0 = float(O_[e, j])
                raw_e = o0 / float(F_[e, j]); ex = _exit_index(Ct.astype(np.float32), j, e + H - (1 if entry != 'close' else 0), nd)
                pos = dict(j=int(j), s=s, e=e, x=ex[0] if ex else e + H, inv=size, v=size, o0=o0, net=None, last=o0)
                if ex is not None:
                    xi, px = ex; raw_x = px / float(F_[xi, j])
                    pos['net'] = (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee[xi]; pos['cost_e'] = 0.01 / raw_e + fee[xi] / 2
                else: pos['cost_e'] = 0.01 / raw_e + fee[min(e + H, nd - 1)] / 2
                active.append(pos); held.add(int(j)); ntr += 1
        if cash > 0 and cash_yield > 0: cash += cash * cash_yield / 242.0
        vs = 0.0
        for p in active:
            if p['e'] <= t:
                ct = Ct[t, p['j']]
                if np.isfinite(ct): p['last'] = float(ct)
                p['v'] = p['inv'] * (p['last'] / p['o0']) * (1 - p['cost_e'])
            vs += p['v']
        tot = cash + vs; eq[t] = tot; expo[t] = vs / max(tot, 1e-9)
    return eq, expo, ev, ntr
def stats(eq, ex):
    r = np.full(nd, np.nan); r[1:] = eq[1:] / eq[:-1] - 1; m = np.isfinite(r); m[:T0 + 1] = False; x = r[m]; cum = np.cumprod(1 + x); n = len(x)
    return dict(cagr=float(cum[-1] ** (245 / n) - 1), sharpe=float(x.mean() / x.std() * np.sqrt(245)), dd=float((cum / np.maximum.accumulate(cum) - 1).min()), expo=float(np.nanmean(ex[m])), n=n, final=float(cum[-1]))
def one(a):
    label, kw = a; eq, ex, ev, ntr = fused3(**kw); r = stats(eq, ex); r.update(ev=ev, ntr=ntr); return label, r
if __name__ == '__main__':
    import multiprocessing as mp
    np.savez_compressed(f'gates_{SIG}.npz', A=gateA, B=gateB, C=gateC)
    print('SIG', SIG, 'window', dates[T0], dates[-1], 'gate days A/C/B', int(gateA[T0:].sum()), int(gateC[T0:].sum()), int(gateB[T0:].sum()), flush=True)
    jobs = [('次日开盘买(原规则)', dict(entry='open')), ('收盘买(14:55 判断)', dict())]
    cons, rest = [], []
    for ea in ('', 'B', 'C', 'BC'):
        for ec in ('', 'A', 'B', 'AB'):
            for eb in ('', 'A', 'C', 'AC'):
                if not (ea or ec or eb): continue
                ev = {k: v for k, v in (('A', ea), ('C', ec), ('B', eb)) if v}
                lab = f'收盘买 + 让位 A:{ea or "-"} C:{ec or "-"} B:{eb or "-"}'
                (cons if (not eb and 'A' not in ec and 'C' not in ea) else rest).append((lab, dict(evict=ev)))
    fn = os.environ.get('OUTJSON', f'grp56_{SIG}.json'); res = json.load(open(fn)) if os.path.exists(fn) else {}
    todo = [j for j in jobs + cons + rest if j[0] not in res]; KEEP = {'次日开盘买(原规则)', '收盘买(14:55 判断)', '收盘买 + 让位 A:BC C:- B:-', '收盘买 + 让位 A:B C:- B:-', '收盘买 + 让位 A:C C:- B:-', '收盘买 + 让位 A:BC C:B B:-', '收盘买 + 让位 A:B C:B B:AC'}
    if os.environ.get('ONLY'): todo = [j for j in todo if j[0] in os.environ['ONLY'].split('|')]
    if os.environ.get('LIM'): todo = [j for j in todo if j[0] in KEEP]
    print('todo', len(todo), flush=True)
    with mp.get_context('fork').Pool(2) as p:
        for lab, r in p.imap_unordered(one, todo):
            res[lab] = r
            print(f'{lab:34s} 年化{r["cagr"]*100:+6.1f}% 夏普{r["sharpe"]:.2f} 回撤{r["dd"]*100:4.0f}% 仓位{r["expo"]*100:3.0f}% 终值{r["final"]:.2f} 开仓{r["ntr"]} 提前平仓{r["ev"]}', flush=True)
            json.dump(res, open(fn, 'w'), ensure_ascii=False)
    print('ALLDONE', flush=True)
