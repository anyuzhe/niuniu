"""Walk-forward (rolling-origin) selection among candidate configs: choose by trailing window Sharpe, apply next year. Candidate daily returns cached in wf_cands.npz. Research only."""
import sys, time, os
from grp11 import *
T1 = time.time(); BUDGET = float(sys.argv[1]) if len(sys.argv) > 1 else 120
cache = 'wf_cands.npz'
C = dict(np.load(cache, allow_pickle=True)) if os.path.exists(cache) else {}
S = {'A': (market, cand), 'B': (fmB, fcB), 'C': (fmC, fcC), 'D': (fmD, fcD)}
jobs = [(f'{k}_H{h}', k, h) for k in 'ABCD' for h in (15, 20, 25)]
for name, k, h in jobs:
    if name in C or time.time() - T1 > BUDGET: continue
    fm, fc = S[k]; r = simulate(panel, fm, fc, DipConfig(leverage=1.0, hold_days=h, cash_yield=0.02)); C[name] = dr(r['eq']); print('done', name, round(time.time() - T1), flush=True)
if 'FUSED' not in C and time.time() - T1 < BUDGET:
    SL = g.SL if False else None
    import grp11 as g
    g.SL['B'] = (gateB, fcB.e6, fcB.ret20); g.SL['C'] = (gateC, fcC.e6, fcC.ret20); g.SL['A'] = (gateA, cand.e6, cand.ret20)
    eq = fused(order='ACB', w=0.05, G=1.0, caps={'B': .5, 'C': .5}, cash_yield=0.02)[0]; C['FUSED'] = dr(eq); print('done FUSED', flush=True)
np.savez(cache, **C)
need = [j[0] for j in jobs] + ['FUSED']
if all(n in C for n in need) and (len(sys.argv) > 2):
    names = need; M = np.array([C[n] for n in names]); valid = np.all(np.isfinite(M[:, 1:]), 0); 
    yr = np.array([int(d[:4]) for d in panel.dates])
    def sh(x): x = x[np.isfinite(x)]; return x.mean() / x.std() * np.sqrt(245) if len(x) > 50 and x.std() > 0 else -9
    def cg(x): x = x[np.isfinite(x)]; return np.prod(1 + x) ** (245 / len(x)) - 1 if len(x) else np.nan
    def stats(r, label):
        x = r[np.isfinite(r)]; cum = np.cumprod(1 + x); dd = (cum / np.maximum.accumulate(cum) - 1).min()
        print(f'{label:46s} 年化{cg(x)*100:+5.1f}% 夏普{sh(x):.2f} 回撤{dd*100:4.0f}%', flush=True)
    for label, win in (('滚动5年窗口', 5), ('扩展窗口(自2008)', 99)):
        for crit in ('sharpe', 'cagr'):
            oos = np.full(nd, np.nan); picks = []; rk_ic = []
            for y in range(2013, 2027):
                lo = max(2008, y - win); tr = (yr >= lo) & (yr < y); te = yr == y
                score = np.array([sh(M[i][tr]) if crit == 'sharpe' else cg(M[i][tr]) for i in range(len(names))])
                b = int(np.argmax(score)); oos[te] = M[b][te]; picks.append((y, names[b]))
                nxt = np.array([cg(M[i][te]) for i in range(len(names))])
                rk_ic.append(np.corrcoef(pd.Series(score).rank().to_numpy(), pd.Series(nxt).rank().to_numpy())[0, 1])
            stats(oos, f'滚动选择[{label}, 按{crit}]（2013-2026）')
            print('   选择:', ' '.join(f'{y}:{n}' for y, n in picks), '| 排名相关均值 %.2f, 为正的年份 %d/%d' % (np.nanmean(rk_ic), sum(1 for v in rk_ic if v > 0), len(rk_ic)), flush=True)
    te = yr >= 2013
    print('--- 同期(2013-2026)固定配置对照', flush=True)
    for n in names: stats(np.where(te, C[n], np.nan), f'固定 {n}')
    stats(np.where(te, np.nanmean(M, 0), np.nan), '所有候选等权平均（每日）')
