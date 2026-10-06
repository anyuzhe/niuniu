"""Group-panic stratifications: 60d-avg amount (C, current), float market cap (M), turnover rate = amt60/float cap (T). Per-quintile event stats, standalone, incremental over A, and D variants. Research only."""
import grp11 as g
from grp11 import *
cap = np.load('cap.npy'); capq = np.load('capq.npy')
ok = np.isfinite(cap) & (cap > 0)
tn = np.where(ok, amt60 / (cap * 1e8), np.nan).astype(np.float32)   # amount / float cap = value-based turnover
labT = np.full((nd, nc), -1, np.int8)
for s0 in range(0, nd, 400):
    b = min(nd, s0 + 400); v = np.where(cand.uni[s0:b] & np.isfinite(tn[s0:b]), tn[s0:b], np.nan)
    pct = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
    labT[s0:b] = np.where(np.isfinite(pct), np.minimum(np.nan_to_num(pct * 5).astype(np.int16), 4), -1).astype(np.int8)
fmM, fcM, (zM, _) = inputs(panel, cfg1, capq, 'any')
fmT, fcT, (zT, _) = inputs(panel, cfg1, labT, 'any')
fmC_, fcC_, (zC, _) = inputs(panel, cfg1, lab, 'any')
gateM = fmM.z <= -1.5; gateT = fmT.z <= -1.5
CL = {'C 成交额': (lab, zC, fcC_), 'M 流通市值': (capq, zM, fcM), 'T 换手率': (labT, zT, fcT)}
O, C = panel.o.astype(np.float64), panel.c.astype(np.float64); H = 20; COST = 0.003
print('=== 触发日数（z≤−1.5 的天数，2008 起） 与 单档触发事件质量（该档里 20 日跌最多的 20 只，20 天，净 30bp）；档 0=最小/最不活跃 … 档 4=最大/最活跃', flush=True)
t0_ = int(np.searchsorted(dates, '2008-01-01'))
for nm, (labs, z, fc) in CL.items():
    print(nm, '各档触发天数', [int((z[t0_:, k] <= -1.5).sum()) for k in range(5)], '任一档', int(np.nansum(np.nanmin(z[t0_:], 1) <= -1.5)), flush=True)
    for k in range(5):
        rows = []
        for t in np.nonzero(z[:, k] <= -1.5)[0]:
            if t < t0_ or t + 1 + H >= nd: continue
            pool = np.nonzero((labs[t] == k) & cand.uni[t] & np.isfinite(cand.ret20[t]) & buyok[t])[0]
            if not len(pool): continue
            pick = pool[np.argsort(cand.ret20[t, pool], kind='stable')[:20]]
            for j in pick:
                if np.isfinite(O[t + 1, j]) and np.isfinite(C[t + H, j]): rows.append(C[t + H, j] / O[t + 1, j] - 1 - COST)
        x = np.array(rows)
        if len(x) < 30: print(f'   档{k}: n={len(x)}'); continue
        print(f'   档{k}: n={len(x):5d} 均值 {x.mean()*100:+6.2f}% 中位 {np.median(x)*100:+6.2f}% 胜率 {np.mean(x>0)*100:3.0f}%', flush=True)
print('=== 触发日重合（天数）: A∩C  A∩M  A∩T   C∩M  C∩T  M∩T', flush=True)
s = slice(t0_, nd); f = lambda a, b: int((a[s] & b[s]).sum())
print(f(gateA, gateC), f(gateA, gateM), f(gateA, gateT), f(gateC, gateM), f(gateC, gateT), f(gateM, gateT), '  各自总天数 A/C/M/T', int(gateA[s].sum()), int(gateC[s].sum()), int(gateM[s].sum()), int(gateT[s].sum()), flush=True)
SL = g.SL; SL['M'] = (gateM, fcM.e6, fcM.ret20); SL['T'] = (gateT, fcT.e6, fcT.ret20)
SL['c'] = (gateC & ~gateA, fcC_.e6, fcC_.ret20); SL['m'] = (gateM & ~gateA, fcM.e6, fcM.ret20); SL['t'] = (gateT & ~gateA, fcT.e6, fcT.ret20)
SL['u'] = (gateM & ~gateA & ~gateC, fcM.e6, fcM.ret20); SL['v'] = (gateT & ~gateA & ~gateC, fcT.e6, fcT.ret20)
print('=== 单独跑（每只 5%，20 名额，1x，现金2%）', flush=True)
for k, nm in (('A', 'A'), ('C', 'C 成交额'), ('M', 'M 流通市值'), ('T', 'T 换手率')): show(f'单独 {nm}', order=k, w=0.05, G=1.0, cash_yield=0.02)
print('=== 增量：只在 A 没触发的日子（排除 A 日）', flush=True)
for k, nm in (('c', 'C 成交额'), ('m', 'M 流通市值'), ('t', 'T 换手率')): show(f'排除A日 {nm}', order=k, w=0.05, G=1.0, cash_yield=0.02)
print('--- 只在 A、C 都没触发的日子（M/T 的独有信号）', flush=True)
show('M 独有(无A无C)', order='u', w=0.05, G=1.0, cash_yield=0.02); show('T 独有(无A无C)', order='v', w=0.05, G=1.0, cash_yield=0.02)
print('=== D 变体（A 8%，层 8%，B 2.5%；优先级见标签）', flush=True)
W = {'A': .08, 'C': .08, 'M': .08, 'T': .08, 'B': .025}
show('D 基线 A>C>B', order='ACB', w=W, G=1.0, cash_yield=0.02)
show('D 把 C 换成 M: A>M>B', order='AMB', w=W, G=1.0, cash_yield=0.02)
show('D 把 C 换成 T: A>T>B', order='ATB', w=W, G=1.0, cash_yield=0.02)
show('D 加 M: A>C>M>B', order='ACMB', w=W, G=1.0, cash_yield=0.02)
show('D 加 T: A>C>T>B', order='ACTB', w=W, G=1.0, cash_yield=0.02)
show('D 加 M、T: A>C>M>T>B', order='ACMTB', w=W, G=1.0, cash_yield=0.02)
W2 = dict(W, M=.05, T=.05)
show('D 加 M、T（各 5%）', order='ACMTB', w=W2, G=1.0, cash_yield=0.02)
