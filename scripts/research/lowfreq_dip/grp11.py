"""Capital-utilisation fusion: one account, sleeves A/B/C with own slots, shared capital cap G, priority admission, cash yield. Research only."""
from grp7 import *
R, Aamt = ind_series(l1); Z = zscore(R); trigI = np.isfinite(Z) & (Z <= -1.5)
fmB, fcB = build(trigI, l1)
# turnover quintile labels
uni = cand.uni
a = np.nan_to_num(panel.a, nan=0.0).astype(np.float64); cs = np.cumsum(a, 0); amt60 = np.full((nd, nc), np.nan, np.float32); amt60[60:] = ((cs[60:] - cs[:-60]) / 60).astype(np.float32); del a, cs
lab = np.full((nd, nc), -1, np.int8)
for s0 in range(0, nd, 400):
    b = min(nd, s0 + 400); v = np.where(uni[s0:b] & np.isfinite(amt60[s0:b]), amt60[s0:b], np.nan)
    pct = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
    lab[s0:b] = np.where(np.isfinite(pct), np.minimum(np.nan_to_num(pct * 5).astype(np.int16), 4), -1).astype(np.int8)
cfg1 = DipConfig(leverage=1.0)
fmC, fcC, _ = inputs(panel, cfg1, lab, 'any')
gD = np.isfinite(market.z) & (market.z <= -1.0)
fmD = Market(mret=market.mret, mk20=market.mk20, z=np.where(gD, -9.0, 9.0), count=market.count); fcD = Candidates(uni=uni, e6=uni & np.isfinite(cand.ret20), buyok=cand.buyok, ret20=cand.ret20)
def dr(eq):
    r = np.full(nd, np.nan); r[1:] = eq[1:] / eq[:-1] - 1; return r
yr = np.array([int(d[:4]) for d in panel.dates])
def met(r, label, expo=None):
    m = np.isfinite(r); x = r[m]; cum = np.cumprod(1 + x); n = len(x)
    cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    h = []
    for a_, b_ in ((2008, 2016), (2017, 2026)):
        k = (yr >= a_) & (yr <= b_) & m; y = r[k]; h.append(f'{(np.prod(1 + y) ** (245 / len(y)) - 1) * 100:+.1f}%')
    ex = '' if expo is None else f' 仓位{np.nanmean(expo[m]) * 100:3.0f}%'
    print(f'{label:46s} 年化{cagr*100:+5.1f}% 夏普{sh:.2f} 回撤{dd*100:4.0f}% 卡玛{cagr/-dd:.2f}{ex} | 前半{h[0]} 后半{h[1]}', flush=True)
    return cagr, sh, dd

from quantlab.dipbuy.engine import _exit_index, _fee_by_day, _rate_by_day
dates, C_, O_, F_ = panel.dates, panel.c, panel.o, panel.f
fee = _fee_by_day(dates); rate = _rate_by_day(dates, None)
gateA = np.isfinite(market.z) & (market.z <= -1.5); gateB = fmB.z <= -1.5; gateC = fmC.z <= -1.5
SL = {'A': (gateA, cand.e6, cand.ret20), 'B': (gateB, fcB.e6, fcB.ret20), 'C': (gateC, fcC.e6, fcC.ret20)}
buyok = cand.buyok

def fused(order, w=0.05, G=1.0, caps=None, N=20, H=20, cash_yield=0.0, t0=None):
    """one account. order: sleeve letters in admission priority. per-position size w*equity; sleeve cap caps[s]*equity; total gross cap G*equity."""
    caps = caps or {}
    t0 = int(np.searchsorted(dates, '2008-01-01')); cash = 1.0; active = []; eq = np.full(nd, np.nan); expo = np.zeros(nd); ntr = {s: 0 for s in order}; pnl = {s: 0.0 for s in order}; wsum = {s: 0.0 for s in order}
    minr = 9.0
    for t in range(t0, nd):
        for p in [p for p in active if p['x'] == t and p['net'] is not None]:
            cash += p['inv'] * (1 + p['net']); ntr[p['s']] += 1; pnl[p['s']] += p['net']; wsum[p['s']] += p['inv']; active.remove(p)
        if t + 1 < nd:
            held = {p['j'] for p in active}
            for s in order:
                gate, e6, r20 = SL[s]
                if not gate[t]: continue
                n_s = sum(1 for p in active if p['s'] == s)
                if n_s >= N: continue
                pool = np.nonzero(e6[t] & buyok[t])[0]
                pool = np.array([j for j in pool if j not in held], dtype=int)
                if not len(pool): continue
                pool = pool[np.argsort(r20[t, pool], kind='stable')]
                invested = sum(p['v'] for p in active); equity = cash + invested
                inv_s = sum(p['v'] for p in active if p['s'] == s)
                for j in pool[:N - n_s]:
                    size = min((w[s] if isinstance(w, dict) else w) * equity, caps.get(s, 9.0) * equity - inv_s, G * equity - invested)
                    if size <= 1e-9: break
                    cash -= size; invested += size; inv_s += size
                    e = t + 1; o0 = float(O_[e, j]); raw_e = o0 / float(F_[e, j]); ex = _exit_index(C_, j, t + H, nd)
                    pos = dict(j=int(j), s=s, e=e, x=ex[0] if ex else t + H, inv=size, v=size, o0=o0, net=None, last=o0)
                    if ex is not None:
                        xi, px = ex; raw_x = px / float(F_[xi, j])
                        pos['net'] = (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee[xi]
                        pos['cost_e'] = 0.01 / raw_e + fee[xi] / 2
                    else:
                        pos['cost_e'] = 0.01 / raw_e + fee[min(t + H, nd - 1)] / 2
                    active.append(pos); held.add(int(j))
        if cash < 0: cash -= -cash * rate[t] / 242.0
        elif cash > 0 and cash_yield > 0: cash += cash * cash_yield / 242.0
        vs = 0.0
        for p in active:
            if p['e'] <= t:
                ct = C_[t, p['j']]
                if np.isfinite(ct): p['last'] = float(ct)
                p['v'] = p['inv'] * (p['last'] / p['o0']) * (1 - p['cost_e'])
            vs += p['v']
        tot = cash + vs; eq[t] = tot; expo[t] = vs / max(tot, 1e-9)
        if cash < 0: minr = min(minr, (vs) / max(-cash, 1e-9))
    return eq, expo, ntr, pnl, wsum, minr

def show(label, **kw):
    eq, ex, ntr, pnl, wsum, minr = fused(**kw); r = dr(eq); met(r, label, ex)
    cy = kw.get('cash_yield', 0.0)
    ut = ' '.join(f"{s}:{ntr[s]}笔均{pnl[s]/max(ntr[s],1)*1e4:+.0f}bp" for s in ntr)
    extra = f'  最低保证金比 {minr:.2f}' if minr < 9 else ''
    print(f'{"":46s} {ut}{extra}', flush=True)
    return r, ex

if __name__ == '__main__':
    import sys
    stage = sys.argv[1] if len(sys.argv) > 1 else 'a'
    if stage == 'a':
        print('=== 一个账户 1x（无杠杆，总仓位上限=100%），各子策略自带 20 个名额，每只 5%，按优先级抢资金', flush=True)
        for order in ('ACB', 'ABC', 'BCA', 'CBA', 'AC', 'AB', 'BC'):
            show(f'1x 优先级 {order}', order=order, w=0.05, G=1.0)
    if stage == 'b':
        print('=== 总仓位上限 1.5x / 2x（融资，利率按年代）', flush=True)
        for G in (1.5, 2.0):
            for order in ('ACB', 'ABC'):
                show(f'{G:g}x 优先级 {order} 每只5%', order=order, w=0.05, G=G)
        print('=== 每只放大到 10%（名额不变，资金用得更满）1x', flush=True)
        for order in ('ACB', 'ABC'):
            show(f'1x 优先级 {order} 每只10%', order=order, w=0.10, G=1.0)
        print('=== 预留：B 最多占 50% 资金，给 A/C 留空间；1x', flush=True)
        show('1x ACB, B≤50%', order='ACB', w=0.05, G=1.0, caps={'B': 0.5})
        show('1x ACB, B≤50%, C≤50%', order='ACB', w=0.05, G=1.0, caps={'B': 0.5, 'C': 0.5})
    if stage == 'c':
        print('=== 闲置资金按 2% 年化（货基）', flush=True)
        for order in ('ACB',):
            show(f'1x {order} 现金2%', order=order, w=0.05, G=1.0, cash_yield=0.02)
        show('单A 1x 现金2%', order='A', w=0.05, G=1.0, cash_yield=0.02)
        show('单B 1x 现金2%', order='B', w=0.05, G=1.0, cash_yield=0.02)
        show('单C 1x 现金2%', order='C', w=0.05, G=1.0, cash_yield=0.02)
        show('单A 1x 现金0', order='A', w=0.05, G=1.0)
    if stage == 'd':
        print('=== 现金 2% 下的融合（同口径对比单策略：A 12.1%/0.81/−28%，B 18.9%/0.80/−47%，C 17.7%/0.85/−36%）', flush=True)
        show('1x ACB, B≤50% C≤50%, 现金2%', order='ACB', w=0.05, G=1.0, caps={'B': 0.5, 'C': 0.5}, cash_yield=0.02)
        show('1x AC, 现金2%', order='AC', w=0.05, G=1.0, cash_yield=0.02)
        show('1x ACB, B≤30% C≤40%, 现金2%', order='ACB', w=0.05, G=1.0, caps={'B': 0.3, 'C': 0.4}, cash_yield=0.02)
        show('1.5x ACB, B≤50% C≤50%, 现金2%', order='ACB', w=0.05, G=1.5, caps={'B': 0.5, 'C': 0.5}, cash_yield=0.02)
