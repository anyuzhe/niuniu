"""D: all eviction-rule combinations (target sleeve x subset of other sleeves). Research only."""
import itertools, sys, json
import multiprocessing as mp
import grp52 as h
from grp52 import *
ESELL = sys.argv[2] if len(sys.argv) > 2 else 'close'
SUB = {'A': ['', 'B', 'C', 'BC'], 'C': ['', 'A', 'B', 'AB'], 'B': ['', 'A', 'C', 'AC']}
def cagr_stats(eq):
    r = dr(eq); m = np.isfinite(r); x = r[m]; cum = np.cumprod(1 + x); n = len(x)
    c = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    hh = []
    for a_, b_ in ((2008, 2016), (2017, 2026)):
        k = (yr >= a_) & (yr <= b_) & m; y = r[k]; hh.append((np.prod(1 + y) ** (245 / len(y)) - 1))
    return c, sh, dd, hh[0], hh[1]
def job(a):
    ea, ec, eb, ecost, ekey = a[:5]
    ev = {k: v for k, v in (('A', ea), ('C', ec), ('B', eb)) if v}
    eq, ex, n = fused2(evict=ev, ecost=ecost, ekey=ekey, esell=ESELL)
    return (a, cagr_stats(eq) + (float(np.nanmean(ex)),), n, [float(eq[np.searchsorted(dates, f'{y}-12-31', side='right') - 1]) for y in range(2008, 2027)])
if __name__ == '__main__':
    jobs = [(ea, ec, eb, ecost, 'old') for ecost in (0.0, 0.003) for ea in SUB['A'] for ec in SUB['C'] for eb in SUB['B']]
    with mp.get_context('fork').Pool(int(sys.argv[1]) if len(sys.argv) > 1 else 4) as p:
        res = []
        for i, r in enumerate(p.imap_unordered(job, jobs)):
            res.append(r); print(i + 1, len(jobs), r[0], f'{r[1][0]*100:.1f}', flush=True)
    json.dump([dict(a=list(r[0]), s=[float(x) for x in r[1]], n=r[2], eqy=r[3]) for r in res], open(f'grp55_{ESELL}.json', 'w'))
    print('saved', flush=True)
