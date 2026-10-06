"""D: how often does the shared 1x gross cap clip A/C/B, how much is lost, and do 'make room' rules help? Research only."""
import grp11 as g
from grp11 import *
from quantlab.dipbuy.engine import _exit_index
W0 = {'A': .08, 'C': .08, 'B': .025}
def fused2(order='ACB', w=W0, G=1.0, caps=None, evict=None, N=20, H=20, cash_yield=0.02, stats=None, ekey='old', hist=None, ecost=0.0, evlog=None, esell='close', buylog=None, quota=None):
    caps = caps or {}; evict = evict or {}
    t0 = int(np.searchsorted(dates, '2008-01-01')); cash = 1.0; active = []; eq = np.full(nd, np.nan); expo = np.zeros(nd)
    ev = 0
    for t in range(t0, nd):
        for p in [p for p in active if p['x'] == t and p['net'] is not None]:
            cash += p['inv'] * (1 + p['net']); active.remove(p)
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
                if hist is not None: hist.append((t, s, n_s, {k: sum(p['v'] for p in active if p['s'] == k) / equity for k in 'ACB'}, cash / equity))
                want = min(N - n_s, len(pool)); ideal = min(want * w[s] * equity, max(caps.get(s, 9.0) * equity - inv_s, 0))
                room = G * equity - invested
                if evict.get(s) and room < ideal - 1e-9:
                    need = ideal - room
                    cands = sorted([p for p in active if p['s'] in evict[s] and p['e'] <= t and np.isfinite(C_[t, p['j']]) and (esell == 'close' or (np.isfinite(O_[t + 1, p['j']]) and O_[t + 1, p['j']] > 0.905 * C_[t, p['j']]))], key=(lambda p: p['e']) if ekey == 'old' else (lambda p: -p['e']) if ekey == 'new' else (lambda p: p['v'] / p['inv']))
                    for p in cands:
                        if need <= 1e-9: break
                        j = p['j']
                        if esell == 'close':
                            rx = float(C_[t, j]) / float(F_[t, j]); val = p['v']; tf = fee[t]
                        else:
                            rx = float(O_[t + 1, j]) / float(F_[t + 1, j]); val = p['inv'] * (float(O_[t + 1, j]) / p['o0']) * (1 - p['cost_e']); tf = fee[t + 1]
                        cash += val * (1 - 0.01 / rx - tf / 2 - ecost); need -= p['v']
                        if evlog is not None: evlog.append((t, s, p['s'], p['v'] / p['inv'] - 1, p['net'], t - p['e']))
                        active.remove(p); held.discard(j); ev += 1
                    invested = sum(p['v'] for p in active); equity = cash + invested; inv_s = sum(p['v'] for p in active if p['s'] == s)
                    ideal = min(want * w[s] * equity, max(caps.get(s, 9.0) * equity - inv_s, 0))
                got = 0.0
                if hist is not None: hist[-1] = hist[-1] + (room if False else (G * equity - invested) / equity, want)
                for j in pool[:min(N - n_s, quota or N)]:
                    size = min(w[s] * equity, caps.get(s, 9.0) * equity - inv_s, G * equity - invested)
                    if size <= 1e-9: break
                    cash -= size; invested += size; inv_s += size; got += size
                    e = t + 1; o0 = float(O_[e, j]); raw_e = o0 / float(F_[e, j]); ex = _exit_index(C_, j, t + H, nd)
                    pos = dict(j=int(j), s=s, e=e, x=ex[0] if ex else t + H, inv=size, v=size, o0=o0, net=None, last=o0)
                    if ex is not None:
                        xi, px = ex; raw_x = px / float(F_[xi, j])
                        pos['net'] = (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee[xi]; pos['cost_e'] = 0.01 / raw_e + fee[xi] / 2
                    else: pos['cost_e'] = 0.01 / raw_e + fee[min(t + H, nd - 1)] / 2
                    active.append(pos); held.add(int(j))
                    if buylog is not None: buylog.append((t, s, size / equity))
                if stats is not None:
                    st = stats.setdefault(s, dict(days=0, clipped=0, zero=0, short=0.0, ideal=0.0, got=0.0, pre_inv=[], ep=[]))
                    st['days'] += 1; st['ideal'] += ideal / equity; st['got'] += got / equity
                    if got < ideal * 0.999: st['clipped'] += 1; st['short'] += (ideal - got) / equity
                    if got < 1e-9: st['zero'] += 1
                    st['pre_inv'].append((invested - got) / equity)
                    # who held the room at the time
                    pass
        if cash > 0 and cash_yield > 0: cash += cash * cash_yield / 242.0
        vs = 0.0
        for p in active:
            if p['e'] <= t:
                ct = C_[t, p['j']]
                if np.isfinite(ct): p['last'] = float(ct)
                p['v'] = p['inv'] * (p['last'] / p['o0']) * (1 - p['cost_e'])
            vs += p['v']
        tot = cash + vs; eq[t] = tot; expo[t] = vs / max(tot, 1e-9)
    return eq, expo, ev

if __name__ == '__main__':
    st = {}
    eq, ex, _ = fused2(stats=st)
    r = dr(eq); met(r, 'D 基线(重算)', ex)
    eq0, ex0, *_ = g.fused(order='ACB', w=W0, G=1.0, caps={}, cash_yield=0.02)
    print('与 grp11.fused 最大差', np.nanmax(np.abs(eq - eq0) / eq0))
    print('\n=== 闸门打开且有候选的日子里，总仓位上限（1x）卡住了多少（理想=名额×权重，对比实际买到）')
    for s in 'ACB':
        a = st[s]; pi = np.array(a['pre_inv'])
        print(f"{s}: 可买日 {a['days']:4d}  被截断 {a['clipped']:4d} ({a['clipped']/max(a['days'],1)*100:.0f}%)  完全买不进 {a['zero']:4d} ({a['zero']/max(a['days'],1)*100:.0f}%)  "
              f"理想合计 {a['ideal']:.1f}  实际 {a['got']:.1f}  少买 {a['short']:.1f} (占理想 {a['short']/max(a['ideal'],1e-9)*100:.0f}%)  开买前已投入均值 {pi.mean()*100:.0f}%")
    # trigger-episode view for A: per A episode, how much of ideal got filled on first day
    gA = np.nonzero(gateA)[0]; gA = gA[gA >= int(np.searchsorted(dates, '2008-01-01'))]
    print('\n=== 不同方案 (1x, 2008 起, 闲置 2%)')
    rows = {}
    def run(label, **kw):
        eq, ex, ev = fused2(**kw); r = dr(eq); c, sh, dd = met(r, label, ex); rows[label] = (c, sh, dd); print(f'{"":46s} 提前平仓 {ev} 笔', flush=True)
    run('基线 A>C>B')
    run('B 最多占 25%', caps={'B': .25})
    run('B 最多占 15%', caps={'B': .15})
    run('B 25% + C 50%', caps={'B': .25, 'C': .5})
    run('A 触发时平掉 B 腾位置', evict={'A': 'B'})
    run('A 平 B/C; C 平 B', evict={'A': 'BC', 'C': 'B'})
    run('C 平 B (A 不挤)', evict={'C': 'B'})
    run('A 权重 6%', w={'A': .06, 'C': .08, 'B': .025})
    run('A 权重 10%', w={'A': .10, 'C': .08, 'B': .025})
    run('优先级 B>C>A (反例)', order='BCA')
