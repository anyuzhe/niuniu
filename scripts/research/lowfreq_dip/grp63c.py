"""grp63 step3: backtest the pre-registered position filter 'skip when market within X of its 250-day high' on D / D1 (product engine, with-delisted panel, 2% idle)."""
import os, sys, time, json
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
sw = os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history')
cls = industry.load_classification(sw, panel.codes)
dates = np.array(panel.dates).astype(str)
nd = len(dates)
M = np.load('grp63_mkt.npz'); idx = np.cumprod(1 + np.where(np.isfinite(M['mret']), M['mret'], 0.0))
rm = np.full(nd, np.nan)
for t in range(249, nd): rm[t] = idx[t - 249:t + 1].max()
dd250 = idx / rm - 1
def stats(raw):
    eq = raw['eq']; ok = np.isfinite(eq); e = eq[ok]; r = e[1:] / e[:-1] - 1
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; sh = r.mean() / r.std() * np.sqrt(245) if r.std() > 0 else 0
    dd = (e / np.maximum.accumulate(e) - 1).min(); tr = raw['trades']
    return cagr, sh, dd, len(tr), float(np.mean(raw['expo'][ok]))
def years(raw):
    eq = raw['eq']; out = {}
    for y in range(2008, 2027):
        m = np.array([d.startswith(str(y)) for d in dates]) & np.isfinite(eq)
        if m.sum() > 5:
            ii = np.nonzero(m)[0]; prev = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]
            out[y] = eq[ii[-1]] / prev - 1
    return out
out = {}
for name, cfg in (('D', fusion.default_config()), ('D1', fusion.d1_config())):
    inp = fusion.build_inputs(panel, cfg, cls)
    t0 = time.time(); base = fusion.simulate_fused(panel, inp, cfg); print(name, 'sim secs', round(time.time() - t0, 1), flush=True)
    res = {'base': (stats(base), years(base))}
    gdays = inp.any_gate
    print(name, 'gate days', int(gdays.sum()), 'near-high gate days (dd250>-6%)', int((gdays & (dd250 > -0.06)).sum()), flush=True)
    for thr in (-0.03, -0.06, -0.10):
        keep = ~(dd250 > thr)
        keep = np.where(np.isfinite(dd250), keep, True)
        g2 = {s: inp.gates[s] & keep for s in inp.gates}
        inp2 = replace(inp, gates=g2, any_gate=g2['A'] | g2['C'] | g2['B'])
        raw = fusion.simulate_fused(panel, inp2, cfg)
        res[f'skip dd250>{thr:.2f}'] = (stats(raw), years(raw))
        print(name, f'skip dd250>{thr:+.2f}', [round(x, 3) if isinstance(x, float) else x for x in stats(raw)], 'masked gate days', int((gdays & ~keep).sum()), flush=True)
    print(name, 'base', [round(x, 3) if isinstance(x, float) else x for x in stats(base)], flush=True)
    # random baseline: mask the same number of gate days (same count as thr -0.06) at random, 60 draws
    nmask = int((gdays & (dd250 > -0.06)).sum()); gi = np.nonzero(gdays)[0]; rng = np.random.default_rng(7); rc = []
    for k in range(60):
        drop = rng.choice(gi, nmask, replace=False); keep = np.ones(nd, bool); keep[drop] = False
        g2 = {s: inp.gates[s] & keep for s in inp.gates}
        inp2 = replace(inp, gates=g2, any_gate=g2['A'] | g2['C'] | g2['B'])
        rc.append(stats(fusion.simulate_fused(panel, inp2, cfg))[0])
    rc = np.array(rc); print(name, 'random mask same count: CAGR mean', round(rc.mean(), 4), 'p5/p95', round(np.percentile(rc, 5), 4), round(np.percentile(rc, 95), 4), flush=True)
    res['random'] = [float(x) for x in rc]
    out[name] = {k: v for k, v in res.items()}
json.dump(out, open('grp63_c.json', 'w'), default=float)
print('done')
