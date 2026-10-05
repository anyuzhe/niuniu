"""D (A8%/C8%/B2.5%, priority A>C>B, shared 1x, idle cash 2%) with realistic execution at a given account size: 100-share lots, two-sided commission with 5-yuan minimum, transfer fee, extra slippage. Research only."""
import sys
from grp11 import *
import grp11 as g
from quantlab.dipbuy.engine import _exit_index
g.SL['A'] = (gateA, cand.e6, cand.ret20); g.SL['B'] = (gateB, fcB.e6, fcB.ret20); g.SL['C'] = (gateC, fcC.e6, fcC.ret20)
SLd = g.SL; stamp = np.where(dates < '2008-09-19', 0.003, np.where(dates < '2023-08-28', 0.001, 0.0005))
comm_engine = np.where(dates < '2015-01-01', 0.0006, np.where(dates < '2020-01-01', 0.0004, 0.00022))
def fused_real(cash0=400000.0, lot=True, comm=0.00025, min_comm=5.0, extra_slip=0.0, engine_fee=False, w=None, N=20, H=20, G=1.0, cash_yield=0.02, order='ACB'):
    w = w or {'A': .08, 'C': .08, 'B': .025}; t0 = int(np.searchsorted(dates, '2008-01-01')); cash = cash0; active = []; eq = np.full(nd, np.nan); expo = np.zeros(nd); skipped = 0; bought = 0; devs = []
    xfer = 0.00001
    for t in range(t0, nd):
        for p in [p for p in active if p['x'] == t and p['net'] is not None]:
            proceeds = p['inv'] * (1 + p['net'])
            if engine_fee: proceeds -= p['inv'] * (1 + p['net']) * (stamp[t] + comm_engine[t])
            else:
                cs = max(min_comm, comm * proceeds) if min_comm > 0 or comm > 0 else 0
                proceeds -= proceeds * (stamp[t] + xfer) + cs
            cash += proceeds; active.remove(p)
        if t + 1 < nd:
            held = {p['j'] for p in active}
            for s in order:
                gate, e6, r20 = SLd[s]
                if not gate[t]: continue
                n_s = sum(1 for p in active if p['s'] == s)
                if n_s >= N: continue
                pool = np.nonzero(e6[t] & buyok[t])[0]; pool = np.array([j for j in pool if j not in held], dtype=int)
                if not len(pool): continue
                pool = pool[np.argsort(r20[t, pool], kind='stable')]
                invested = sum(p['v'] for p in active); equity = cash + invested
                for j in pool[:N - n_s]:
                    target = min(w[s] * equity, G * equity - invested, cash)
                    if target <= 1: break
                    e = t + 1; o0 = float(O_[e, j]); raw_e = o0 / float(F_[e, j])
                    unit = raw_e * (1 + extra_slip) + 0.01
                    if lot:
                        sh = int(target / (unit * 100)) * 100
                        if sh <= 0: skipped += 1; continue
                    else: sh = target / unit
                    inv = sh * unit
                    cb = 0.0 if engine_fee else (max(min_comm, comm * inv) if (min_comm > 0 or comm > 0) else 0) + inv * xfer
                    if inv + cb > cash + 1e-6: continue
                    cash -= inv + cb; invested += inv; bought += 1; devs.append(inv / equity / w[s])
                    ex = _exit_index(C_, j, t + H, nd)
                    pos = dict(j=int(j), s=s, e=e, x=ex[0] if ex else t + H, inv=inv, v=inv, o0=o0, net=None, last=o0)
                    if ex is not None:
                        xi, px = ex; raw_x = px / float(F_[xi, j])
                        pos['net'] = (px * (1 - 0.01 / raw_x - extra_slip)) / (o0 * (1 + 0.01 / raw_e + extra_slip)) - 1
                    active.append(pos); held.add(int(j))
        if cash > 0 and cash_yield > 0: cash += cash * cash_yield / 242.0
        vs = 0.0
        for p in active:
            if p['e'] <= t:
                ct = C_[t, p['j']]
                if np.isfinite(ct): p['last'] = float(ct)
                p['v'] = p['inv'] * (p['last'] / p['o0'])
            vs += p['v']
        tot = cash + vs; eq[t] = tot; expo[t] = vs / max(tot, 1e-9)
    return eq, expo, skipped, bought, np.mean(devs) if devs else np.nan
def run(label, **kw):
    eq, ex, sk, bo, dv = fused_real(**kw); r = dr(eq); cg, sh, dd = met(r, label, ex)
    print(f'{"":46s} 买入{bo}次 因一手买不起跳过{sk}次 实际权重/目标权重均值{dv:.2f} 期末资金 {eq[np.isfinite(eq)][-1]/1e4:,.1f}万', flush=True); return cg
if __name__ == '__main__':
    st = sys.argv[1]
    if st == 'a':
        print('=== D 在 40 万本金下的执行摩擦（2008 起，扣成本，闲置资金 2%）', flush=True)
        run('S0 理想：可分割份额，引擎费率（对账用）', cash0=400000, lot=False, engine_fee=True)
        run('S1 整手(100股)，引擎费率', cash0=400000, lot=True, engine_fee=True)
        run('S2 整手 + 双边佣金万2.5（无最低）', cash0=400000, lot=True, comm=0.00025, min_comm=0)
        run('S3 整手 + 佣金万2.5、最低5元 + 过户费', cash0=400000, lot=True, comm=0.00025, min_comm=5)
    if st == 'b':
        print('=== 再加冲击成本（每边额外滑点）', flush=True)
        run('S4 S3 + 每边滑点 10bp', cash0=400000, lot=True, extra_slip=0.001)
        run('S5 S3 + 每边滑点 20bp', cash0=400000, lot=True, extra_slip=0.002)
        print('=== 本金大小对比（S3 口径）', flush=True)
        for c0 in (100000, 200000, 1000000):
            run(f'S3 本金 {c0/1e4:.0f}万', cash0=c0, lot=True, comm=0.00025, min_comm=5)
