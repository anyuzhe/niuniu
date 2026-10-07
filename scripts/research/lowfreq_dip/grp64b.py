"""grp64: sweep the 'market position' filter beyond the fixed 250-day: window x threshold grids for three families
 (a) within X of the W-day high, (b) above its W-day MA by X, (c) level percentile in W days >= p.  Gate closed when condition holds.
Product engine, with-delisted panel, 2% idle. Robustness: yearly log-gain, gain after dropping best 1/2 years, sub-period gains, null (random same-count masks)."""
import os, sys, json, time
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
VARIANT = sys.argv[1] if len(sys.argv) > 1 else 'D'
MODE = sys.argv[2] if len(sys.argv) > 2 else 'cells'
PART = int(sys.argv[3]) if len(sys.argv) > 3 else 0
NPARTS = int(sys.argv[4]) if len(sys.argv) > 4 else 1
counter = [0]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
sw = os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history')
cls = industry.load_classification(sw, panel.codes)
dates = np.array(panel.dates).astype(str); nd = len(dates)
M = np.load('grp63_mkt.npz'); idx = np.cumprod(1 + np.where(np.isfinite(M['mret']), M['mret'], 0.0))
cfg = fusion.default_config() if VARIANT == 'D' else fusion.d1_config()
inp = fusion.build_inputs(panel, cfg, cls)
gdays = inp.any_gate
YEARS = np.array([int(d[:4]) for d in dates])
def roll(x, w, fn):
    out = np.full(nd, np.nan)
    for t in range(w - 1, nd): out[t] = fn(x[t - w + 1:t + 1])
    return out
def run(keep):
    g2 = {s: inp.gates[s] & keep for s in inp.gates}
    return fusion.simulate_fused(panel, replace(inp, gates=g2, any_gate=g2['A'] | g2['C'] | g2['B']), cfg)
def summ(raw):
    eq = raw['eq']; ok = np.isfinite(eq); e = eq[ok]; r = e[1:] / e[:-1] - 1
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; sh = r.mean() / r.std() * np.sqrt(245); dd = (e / np.maximum.accumulate(e) - 1).min()
    ly = {}
    for y in range(2008, 2027):
        ii = np.nonzero((YEARS == y) & ok)[0]
        if len(ii) > 5:
            prev = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]
            ly[y] = float(np.log(eq[ii[-1]] / prev))
    return cagr, sh, dd, ly
base = run(np.ones(nd, bool)); b_cagr, b_sh, b_dd, b_ly = summ(base)
print(VARIANT, 'base', round(b_cagr, 4), round(b_sh, 3), round(b_dd, 3), flush=True)
cells = []
def add(fam, W, X, cond):
    counter[0] += 1
    if MODE != 'cells' or (counter[0] - 1) % NPARTS != PART:
        return
    cond = np.where(np.isfinite(cond), cond, False)
    keep = ~cond; nmask = int((gdays & ~keep).sum())
    c, s, d, ly = summ(run(keep))
    diffs = np.array([ly[y] - b_ly[y] for y in sorted(b_ly) if y in ly]); ys = [y for y in sorted(b_ly) if y in ly]
    srt = np.sort(diffs)[::-1]
    cells.append(dict(fam=fam, W=W, X=X, cagr=c, sh=s, dd=d, nmask=nmask, gain=c - b_cagr, tot=float(diffs.sum()),
                      drop1=float(diffs.sum() - srt[0]), drop2=float(diffs.sum() - srt[0] - srt[1]),
                      early=float(sum(diffs[i] for i, y in enumerate(ys) if y <= 2019)), late=float(sum(diffs[i] for i, y in enumerate(ys) if y >= 2020)),
                      wins=int((diffs > 0.002).sum()), losses=int((diffs < -0.002).sum())))
t0 = time.time()
for W in (20, 40, 60, 90, 120, 180, 250, 375, 500, 750, 1000):
    rm = roll(idx, W, np.max); dd = idx / rm - 1
    for X in (0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20):
        add('near_high', W, X, dd > -X)
print('near_high done', round(time.time() - t0), flush=True)
for W in (20, 60, 120, 250, 500):
    ma = roll(idx, W, np.mean); gap = idx / ma - 1
    for X in (0.02, 0.05, 0.08, 0.12, 0.20):
        add('above_ma', W, X, gap > X)
for W in (120, 250, 500, 1000):
    pr = np.full(nd, np.nan)
    for t in range(W - 1, nd):
        win = idx[t - W + 1:t + 1]; pr[t] = (win < idx[t]).mean()
    for p in (0.80, 0.90, 0.95, 0.98):
        add('pctile', W, p, pr >= p)
print('all families done', round(time.time() - t0), flush=True)
if MODE == 'cells':
    json.dump(dict(base=dict(cagr=b_cagr, sh=b_sh, dd=b_dd), cells=cells), open(f'grp64_{VARIANT}_cells_{PART}.json', 'w'), default=float)
    print('saved part', PART, len(cells)); sys.exit()
grid = [0, 10, 20, 40, 70, 110, 160, 230, 330, 470, 650]
rng = np.random.default_rng(11 + PART); gi = np.nonzero(gdays)[0]; out = {}
for n in grid[1 + PART::NPARTS]:
    cs = []
    for k in range(8):
        keep = np.ones(nd, bool); keep[rng.choice(gi, n, replace=False)] = False
        cs.append(summ(run(keep))[0])
    out[n] = (float(np.mean(cs)), float(np.std(cs)))
    print('null', n, out[n], flush=True)
json.dump(out, open(f'grp64_{VARIANT}_null_{PART}.json', 'w'))
