"""grp70: B 层剔除若干申万行业后，D / D2 的回测。
python grp70.py named V | oos V | placebo V seed n   -> grp70_<mode>_<V>[_seed].json"""
import os, sys, json, pickle, time
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
mode, V = sys.argv[1], sys.argv[2]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cfg = fusion.config_for(V)
inp0 = fusion.with_near_high_filter(replace(raw_inp), cfg)
nd, nc = panel.shape
dates = [str(d) for d in panel.dates]; years = np.array([int(d[:4]) for d in dates])
ind_of = np.array([cls.name_of(j) for j in range(nc)])
ALL = sorted(set(ind_of))
i18 = int(np.searchsorted(dates, '2018-01-01'))
def run(excl):
    keep = ~np.isin(ind_of, list(excl))
    inp = replace(inp0, pools={**inp0.pools, 'B': inp0.pools['B'] & keep[None, :]})
    raw = fusion.simulate_fused(panel, inp, cfg)
    eq = raw['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; r = e[1:] / e[:-1] - 1
    dd = float((e / np.maximum.accumulate(e) - 1).min())
    pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]
    npre = int((idx < i18).sum()); npost = int((idx >= i18).sum())
    yr = {}
    for y in range(2008, 2027):
        ii = np.nonzero((years == y) & ok)[0]
        if len(ii) > 5:
            base = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]
            yr[y] = float(eq[ii[-1]] / base - 1)
    bt = [t['ret'] for t in raw['trades'] if t.get('sleeve') == 'B']
    return dict(excl=sorted(excl), cagr=float(cagr), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=dd,
                cagr_pre=float(pre ** (245 / npre) - 1), cagr_post=float(post ** (245 / npost) - 1),
                years=yr, nB=len(bt), meanB=float(np.mean(bt)))
S1 = ['国防军工']; S2 = S1 + ['环保', '煤炭', '基础化工']; S3 = S2 + ['家用电器', '美容护理']; S4 = S3 + ['房地产']
out = {}; t0 = time.time()
if mode == 'named':
    which = sys.argv[3] if len(sys.argv) > 3 else 'all'
    sets = {'base': [], 'S1 国防军工': S1, 'S2 +环保煤炭基础化工': S2, 'S3 +家电美容护理': S3, 'S4 +房地产': S4}
    for k, v in sets.items():
        if which != 'all' and k.split()[0] not in which.split(','): continue
        out[k] = run(v); print(V, k, round(out[k]['cagr'] * 100, 1), round(time.time() - t0), 's', flush=True)
    json.dump(out, open(f'grp70_named_{V}_{which.replace(",", "")}.json', 'w'), ensure_ascii=False)
elif mode == 'oos':
    T = [t for t in json.load(open(f'grp69_{V}.json'))['trades'] if t['signal'] < '2018-01-01']
    from collections import defaultdict
    by = defaultdict(list)
    for t in T: by[t['ind']].append(t)
    pre = {}
    for ind, rs in by.items():
        ds = sorted({r['signal'] for r in rs}); eps = []; cur = [ds[0]]
        for d in ds[1:]:
            if (np.datetime64(d) - np.datetime64(cur[-1])).astype(int) > 25: eps.append(cur); cur = [d]
            else: cur.append(d)
        eps.append(cur)
        if len(eps) >= 3: pre[ind] = float(np.mean([np.mean([r['ret'] for r in rs if r['signal'] in set(e)]) for e in eps]))
    worst = [k for k, _ in sorted(pre.items(), key=lambda kv: kv[1])[:4]]
    print(V, 'pre-2018 worst4', worst, flush=True)
    out['base'] = run([]); out['oos_worst4'] = run(worst); out['worst4'] = worst
    json.dump(out, open(f'grp70_oos_{V}.json', 'w'), ensure_ascii=False)
    for k in ('base', 'oos_worst4'): print(V, k, 'post2018', round(out[k]['cagr_post'] * 100, 1), 'full', round(out[k]['cagr'] * 100, 1), flush=True)
elif mode == 'placebo':
    seed, n = int(sys.argv[3]), int(sys.argv[4]); K = int(sys.argv[5]) if len(sys.argv) > 5 else 4; rng = np.random.default_rng(seed); res = []
    for _ in range(n):
        s = list(rng.choice(ALL, K, replace=False)); r = run(s); res.append(r)
        print(V, 'placebo', s, round(r['cagr'] * 100, 1), round(time.time() - t0), 's', flush=True)
        if time.time() - t0 > 95: break
    json.dump(res, open(f'grp70_placebo_{V}_{seed}_k{K}.json', 'w'), ensure_ascii=False)
