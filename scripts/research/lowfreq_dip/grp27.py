"""D with 09:35 buy and split exits (sell half / thirds on consecutive days at 09:30), 2020+. Research only."""
import sys
import grp11 as g
from grp11 import *
from quantlab.dipbuy.engine import _exit_index
from grp26 import ratio, O0, C0, stat, S0
def fused_split(Hs, buy935=True, exit_open=True, w=None, N=20, G=1.0, cash_yield=0.02, order='ACB'):
    w = w or {'A': .08, 'C': .08, 'B': .025}; O_ = np.where(np.isfinite(ratio), O0 * ratio, O0).astype(np.float32) if buy935 else O0; C_ = O0 if exit_open else C0
    SL = g.SL; dates_, F_, buyok_ = g.dates, g.F_, g.buyok; fee_, rate_ = g.fee, g.rate
    t0 = int(np.searchsorted(dates_, '2008-01-01')); cash = 1.0; active = []; eq = np.full(nd, np.nan); expo = np.zeros(nd); k = len(Hs)
    for t in range(t0, nd):
        for p in [p for p in active if p['x'] == t and p['net'] is not None]:
            cash += p['inv'] * (1 + p['net']); active.remove(p)
        if t + 1 < nd:
            held = {p['j'] for p in active}
            for s in order:
                gate, e6, r20 = SL[s]
                if not gate[t]: continue
                n_s = len({p['j'] for p in active if p['s'] == s})
                if n_s >= N: continue
                pool = np.nonzero(e6[t] & buyok_[t])[0]; pool = np.array([j for j in pool if j not in held], dtype=int)
                if not len(pool): continue
                pool = pool[np.argsort(r20[t, pool], kind='stable')]
                invested = sum(p['v'] for p in active); equity = cash + invested; inv_s = sum(p['v'] for p in active if p['s'] == s)
                for j in pool[:N - n_s]:
                    size = min(w[s] * equity, G * equity - invested)
                    if size <= 1e-9: break
                    cash -= size; invested += size; inv_s += size
                    e = t + 1; o0 = float(O_[e, j]); raw_e = o0 / float(F_[e, j])
                    for Hh in Hs:
                        ex = _exit_index(C_, j, t + Hh, nd); pos = dict(j=int(j), s=s, e=e, x=ex[0] if ex else t + Hh, inv=size / k, v=size / k, o0=o0, net=None, last=o0)
                        if ex is not None:
                            xi, px = ex; raw_x = px / float(F_[xi, j])
                            pos['net'] = (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee_[xi]; pos['cost_e'] = 0.01 / raw_e + fee_[xi] / 2
                        else: pos['cost_e'] = 0.01 / raw_e + fee_[min(t + Hh, nd - 1)] / 2
                        active.append(pos)
                    held.add(int(j))
        if cash < 0: cash -= -cash * rate_[t] / 242.0
        elif cash > 0 and cash_yield > 0: cash += cash * cash_yield / 242.0
        vs = 0.0
        for p in active:
            if p['e'] <= t:
                ct = C_[t, p['j']]
                if np.isfinite(ct): p['last'] = float(ct)
                p['v'] = p['inv'] * (p['last'] / p['o0']) * (1 - p['cost_e'])
            vs += p['v']
        tot = cash + vs; eq[t] = tot; expo[t] = vs / max(tot, 1e-9)
    return eq, expo
if __name__ == '__main__':
    print('=== D，9:35 买，分批在 9:30 卖（2020 起）', flush=True)
    for label, Hs, b, xo in (('基线：9:30 买，t+20 收盘一次卖', [20], False, False), ('9:35 买，t+21 9:30 一次卖（上次的规则）', [21], True, True),
                             ('9:35 买，t+20 与 t+21 各卖一半', [20, 21], True, True), ('9:35 买，t+21 与 t+22 各卖一半', [21, 22], True, True),
                             ('9:35 买，t+20 / t+21 / t+22 各卖 1/3', [20, 21, 22], True, True), ('9:35 买，t+19 / t+21 / t+23 各卖 1/3', [19, 21, 23], True, True)):
        eq, ex = fused_split(Hs, b, xo); stat(dr(eq), label, ex)
