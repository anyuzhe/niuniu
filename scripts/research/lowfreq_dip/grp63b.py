"""grp63 step2: does the market's own position (percentile / drawdown / MA gap) predict D's per-trade net return? Pre-registered metrics, terciles over all days."""
import json, numpy as np
M = np.load('grp63_mkt.npz'); dates = M['dates']; mret = M['mret']
idx = np.cumprod(1 + np.where(np.isfinite(mret), mret, 0.0))
n = len(idx)
def roll_pct(x, w):
    out = np.full(n, np.nan)
    for t in range(w - 1, n):
        win = x[t - w + 1:t + 1]; out[t] = (win < x[t]).mean() + 0.5 * (win == x[t]).mean() / len(win) * 0
    return out
def roll_max(x, w):
    out = np.full(n, np.nan)
    for t in range(w - 1, n): out[t] = x[t - w + 1:t + 1].max()
    return out
def roll_mean(x, w):
    c = np.cumsum(np.insert(x, 0, 0)); out = np.full(n, np.nan); out[w - 1:] = (c[w:] - c[:-w]) / w; return out
metrics = {
 'pct500': roll_pct(idx, 500), 'pct1250': roll_pct(idx, 1250),
 'dd250': idx / roll_max(idx, 250) - 1, 'dd_run': idx / np.maximum.accumulate(idx) - 1,
 'ma250gap': idx / roll_mean(idx, 250) - 1,
 'ret60': np.concatenate([np.full(60, np.nan), idx[60:] / idx[:-60] - 1]),
}
warm = 1250
trs = json.load(open('grp62_trades.json'))
di = {d: i for i, d in enumerate(dates)}
for name in ('D', 'D1'):
    T = [t for t in trs[name] if t['closed'] == 'exit']
    sig = np.array([di[t['signal']] for t in T]); ret = np.array([t['ret'] for t in T]); yr = np.array([int(t['signal'][:4]) for t in T])
    sl = np.array([t['sleeve'] for t in T])
    order = np.argsort(sig); 
    # episodes: consecutive signal days within 5 trading days
    ep = np.zeros(len(T), int); ss = np.sort(np.unique(sig)); eid = {}; k = 0
    for i, d in enumerate(ss):
        if i and d - ss[i - 1] > 5: k += 1
        eid[d] = k
    ep = np.array([eid[s] for s in sig])
    print(f'===== {name}  trades {len(T)}  signal-days {len(ss)}  episodes {k+1}   all-trade mean {ret.mean()*100:+.2f}%')
    rng = np.random.default_rng(1)
    for mname, x in metrics.items():
        v = x[sig]; ok = np.isfinite(v)
        allv = x[warm:]; q = np.nanquantile(allv, [1/3, 2/3]); 
        # terciles by all-days distribution
        b = np.where(v <= q[0], 0, np.where(v <= q[1], 1, 2)); b[~ok] = -1
        line = f'{mname:9s} thr[{q[0]:+.2f},{q[1]:+.2f}] '
        res = []
        for g in (0, 1, 2):
            m = b == g
            e_means = [ret[(ep == e) & m].mean() for e in np.unique(ep[m])] if m.any() else []
            res.append((m.sum(), len(e_means), ret[m].mean() if m.any() else np.nan, np.mean(e_means) if e_means else np.nan))
        line += ' | '.join(f'T{g+1}: n={r[0]:3d} ep={r[1]:2d} mean {r[2]*100:+5.2f}% epmean {r[3]*100:+5.2f}%' for g, r in enumerate(res))
        print(line)
        # cluster bootstrap: diff T1 - T3 episode means
        def diff(sample_eps):
            a = [ret[(ep == e) & (b == 0)] for e in sample_eps]; c = [ret[(ep == e) & (b == 2)] for e in sample_eps]
            a = np.concatenate(a) if a else np.array([]); c = np.concatenate(c) if c else np.array([])
            return (a.mean() - c.mean()) if len(a) and len(c) else np.nan
        eps = np.unique(ep[ok]); ds = [diff(rng.choice(eps, len(eps))) for _ in range(2000)]
        ds = np.array([d for d in ds if np.isfinite(d)])
        print(f'          T1-T3 diff {diff(eps)*100:+.2f} pt  cluster-bootstrap 90% CI [{np.percentile(ds,5)*100:+.1f}, {np.percentile(ds,95)*100:+.1f}]')
        # period consistency
        pr = []
        for lo, hi in ((2008, 2013), (2014, 2019), (2020, 2026)):
            m0 = (yr >= lo) & (yr <= hi) & (b == 0); m2 = (yr >= lo) & (yr <= hi) & (b == 2)
            pr.append(f'{lo}-{hi}: T1 {ret[m0].mean()*100:+.1f}%({m0.sum()}) T3 {ret[m2].mean()*100:+.1f}%({m2.sum()})' if m0.any() and m2.any() else f'{lo}-{hi}: n/a')
        print('          ' + ' ; '.join(pr))
