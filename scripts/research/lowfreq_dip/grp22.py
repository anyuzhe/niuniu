"""Weekly/bi-weekly rotation: every P trading days re-rank candidates and rotate into the latest top-N (sell holdings no longer in the top-N, buy new ones).
vs fixed 20-day hold. Same cost model as the product engine, 1x, no leverage. Research only."""
import sys
from grp11 import *
from quantlab.dipbuy.engine import _fee_by_day
fee = _fee_by_day(panel.dates); O, Cc, F = panel.o, panel.c, panel.f
def rot(fm, fc, P=5, off='hold', cap=20, N=20, start='2008-01-01', cash_yield=0.0, replace_only_if_worse=False):
    gate = np.isfinite(fm.z) & (fm.z <= -1.5); t0 = int(np.searchsorted(panel.dates, start))
    last_reb = -999; cash = 1.0; active = []; eq = np.full(nd, np.nan); expo = np.zeros(nd); pend_s = []; pend_b = []; closed = []; nb = 0
    key = fc.ret20; pool_all = fc.e6 & fc.buyok
    for t in range(t0, nd):
        # execute at today's open
        if pend_s or pend_b:
            keep = []
            for p in active:
                if p['id'] in pend_s:
                    s = t; j = p['j']
                    if not np.isfinite(O[s, j]): keep.append(p); continue
                    raw_s = O[s, j] / F[s, j]
                    net = O[s, j] * (1 - 0.01 / raw_s) / (p['o0'] * (1 + p['ce'])) - 1 - fee[s] if False else (O[s, j] * (1 - 0.01 / raw_s)) / (p['o0'] * (1 + 0.01 / p['rawe'])) - 1 - fee[s]
                    cash += p['inv'] * (1 + net); closed.append((t - p['e'], net))
                else: keep.append(p)
            active = keep; pend_s = []
            invested = sum(p['v'] for p in active); equity = cash + invested
            held = {p['j'] for p in active}
            for j in pend_b:
                if j in held or not np.isfinite(O[t, j]): continue
                size = min(equity / N, cash)
                if size <= 1e-9: break
                raw_e = O[t, j] / F[t, j]; cash -= size; nb += 1
                active.append(dict(id=nb, j=int(j), e=t, inv=size, v=size, o0=float(O[t, j]), rawe=raw_e, ce=0.01 / raw_e + fee[t] / 2, last=float(O[t, j])))
            pend_b = []
        if cash > 0 and cash_yield > 0: cash += cash * cash_yield / 242.0
        vs = 0.0
        for p in active:
            ct = Cc[t, p['j']]
            if np.isfinite(ct): p['last'] = float(ct)
            p['v'] = p['inv'] * (p['last'] / p['o0']) * (1 - p['ce']); vs += p['v']
        eq[t] = cash + vs; expo[t] = vs / max(cash + vs, 1e-9)
        if t + 1 >= nd: break
        sell_ids = set()
        if cap:
            for p in active:
                if t - p['e'] >= cap: sell_ids.add(p['id'])
        if gate[t] and t - last_reb >= P or (not gate[t] and off == 'sell'):
            if gate[t]:
                last_reb = t
                idx = np.nonzero(pool_all[t])[0]
                idx = idx[np.argsort(key[t, idx], kind='stable')][:N]; tgt = set(int(x) for x in idx)
                for p in active:
                    if p['j'] not in tgt: sell_ids.add(p['id'])
                pend_b = [int(x) for x in idx if int(x) not in {p['j'] for p in active if p['id'] not in sell_ids}]
            elif off == 'sell':
                for p in active: sell_ids.add(p['id'])
        pend_s = sell_ids
    ret = np.full(nd, np.nan); ret[1:] = eq[1:] / eq[:-1] - 1
    h = np.mean([x[0] for x in closed]) if closed else 0; m = np.mean([x[1] for x in closed]) * 1e4 if closed else 0
    return ret, expo, len(closed), h, m
if __name__ == '__main__':
    which = sys.argv[1]
    nm, fm, fc0 = {'A': ('A 大盘z+E6', market, cand), 'B': ('B 行业恐慌', fmB, fcB), 'C': ('C 成交额五分位', fmC, fcC)}[which]
    r = simulate(panel, fm, fc0, DipConfig(leverage=1.0)); met(dr(r['eq']), f'{nm} | 基线: 固定持有20日', r['expo'])
    for P, off, cap in ((5, 'hold', 20), (5, 'sell', 0), (5, 'hold', 0), (10, 'hold', 20), (10, 'sell', 0), (3, 'sell', 0)):
        ret, ex, n, h, m = rot(fm, fc0, P=P, off=off, cap=cap)
        met(ret, f'{nm} | 每{P}日换榜, 无信号{"清仓" if off=="sell" else "持有"}, 持有上限{cap or "无"}', ex)
        print(f'{"":46s} 平仓{n}笔 平均持有{h:4.1f}天 笔均{m:+5.0f}bp', flush=True)
