"""grp64p: placebo for the 129-cell position-filter grid. The market index is replaced by a block-shuffled copy (20-day blocks, circular), so any 'position' signal is
unrelated to the actual gate-day returns; the same grid is run and the best cell is recorded. Gives the null distribution of 'best of 129 cells'."""
import os, sys, json, time
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
NP = int(sys.argv[1]) if len(sys.argv) > 1 else 30
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 23
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
sw = os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history')
cls = industry.load_classification(sw, panel.codes)
dates = np.array(panel.dates).astype(str); nd = len(dates)
M = np.load('grp63_mkt.npz'); mret = np.where(np.isfinite(M['mret']), M['mret'], 0.0)
cfg = fusion.default_config(); inp = fusion.build_inputs(panel, cfg, cls); gdays = inp.any_gate
YEARS = np.array([int(d[:4]) for d in dates])
def run(keep):
    g2 = {s: inp.gates[s] & keep for s in inp.gates}
    return fusion.simulate_fused(panel, replace(inp, gates=g2, any_gate=g2['A'] | g2['C'] | g2['B']), cfg)
def summ(raw):
    eq = raw['eq']; ok = np.isfinite(eq); e = eq[ok]
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; ly = {}
    for y in range(2008, 2027):
        ii = np.nonzero((YEARS == y) & ok)[0]
        if len(ii) > 5:
            prev = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]
            ly[y] = float(np.log(eq[ii[-1]] / prev))
    return cagr, ly
base_c, base_ly = summ(run(np.ones(nd, bool)))
def roll(x, w, fn):
    out = np.full(nd, np.nan)
    for t in range(w - 1, nd): out[t] = fn(x[t - w + 1:t + 1])
    return out
def conds(idx):
    for W in (20, 40, 60, 90, 120, 180, 250, 375, 500, 750, 1000):
        dd = idx / roll(idx, W, np.max) - 1
        for X in (0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20): yield ('near_high', W, X, dd > -X)
    for W in (20, 60, 120, 250, 500):
        gap = idx / roll(idx, W, np.mean) - 1
        for X in (0.02, 0.05, 0.08, 0.12, 0.20): yield ('above_ma', W, X, gap > X)
    for W in (120, 250, 500, 1000):
        pr = np.full(nd, np.nan)
        for t in range(W - 1, nd): pr[t] = (idx[t - W + 1:t + 1] < idx[t]).mean()
        for p in (0.80, 0.90, 0.95, 0.98): yield ('pctile', W, p, pr >= p)
def grid(idx):
    out = []
    for fam, W, X, cond in conds(idx):
        cond = np.where(np.isfinite(cond), cond, False)
        c, ly = summ(run(~cond)); ys = [y for y in sorted(base_ly) if y in ly]
        diffs = np.array([ly[y] - base_ly[y] for y in ys]); srt = np.sort(diffs)[::-1]
        out.append(dict(gain=c - base_c, drop2=float(diffs.sum() - srt[0] - srt[1]), early=float(sum(d for d, y in zip(diffs, ys) if y <= 2019)),
                        late=float(sum(d for d, y in zip(diffs, ys) if y >= 2020)), nmask=int((gdays & cond).sum())))
    return out
rng = np.random.default_rng(SEED); B = 20; nb = nd // B
res = []
for k in range(NP):
    order = rng.permutation(nb); r = np.concatenate([mret[o * B:(o + 1) * B] for o in order] + [mret[nb * B:]])
    idx = np.cumprod(1 + r); cs = grid(idx)
    g = np.array([c['gain'] for c in cs]); rob = [c['gain'] for c in cs if c['gain'] > 0 and c['drop2'] > 0 and c['early'] >= 0 and c['late'] > 0 and c['nmask'] > 0]
    res.append(dict(best=float(g.max()), n_pos=int((g > 0).sum()), n_gt2=int((g > 0.02).sum()), n_rob=len(rob), best_rob=float(max(rob)) if rob else 0.0))
    print(k, {k_: round(v, 4) if isinstance(v, float) else v for k_, v in res[-1].items()}, flush=True)
    json.dump(res, open(f'grp64p_{SEED}.json', 'w'))
