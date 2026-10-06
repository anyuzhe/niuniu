"""D with a per-day buy quota per sleeve (spread the entry over days instead of filling all slots on the first day). Research only."""
import numpy as np, multiprocessing as mp
import grp52 as h
from grp52 import *
def episode_day(gate, gap=5):
    k = np.zeros(nd, int); lo = -10 ** 9; st = None
    for t in range(nd):
        if gate[t]:
            if t - lo > gap: st = t
            k[t] = t - st + 1; lo = t
    return k
EP = {s: episode_day(SL[s][0]) for s in 'ACB'}
def one(q):
    bl = []; eq, ex, _ = fused2(quota=q, buylog=bl); r = dr(eq)
    m = np.isfinite(r); x = r[m]; cum = np.cumprod(1 + x); n = len(x)
    cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    hh = []
    for a_, b_ in ((2008, 2016), (2017, 2026)):
        k = (yr >= a_) & (yr <= b_) & m; y = r[k]; hh.append(np.prod(1 + y) ** (245 / len(y)) - 1)
    first = []
    for s in 'ACB':
        b = [(EP[s][t], w) for t, ss, w in bl if ss == s]; tot = sum(w for _, w in b)
        first.append(sum(w for d, w in b if d == 1) / tot if tot else np.nan)
    return q, cagr, sh, dd, hh, float(np.nanmean(ex[m])), len(bl), first, float(cum[-1])
if __name__ == '__main__':
    with mp.get_context('fork').Pool(2) as p:
        for q, c, sh, dd, hh, ex, n, first, fin in p.imap(one, [20, 10, 7, 5, 4, 3, 2, 1]):
            lab = '基线(首日填满)' if q == 20 else f'每层每天最多买 {q} 只'
            print(f'{lab:16s} 年化{c*100:+5.1f}% 夏普{sh:.2f} 回撤{dd*100:4.0f}% 仓位{ex*100:3.0f}% 终值{fin:5.1f}x 买入{n}笔 | 前半{hh[0]*100:+.1f}% 后半{hh[1]*100:+.1f}% | 首日买入占比 A{first[0]*100:.0f}% C{first[1]*100:.0f}% B{first[2]*100:.0f}%', flush=True)
