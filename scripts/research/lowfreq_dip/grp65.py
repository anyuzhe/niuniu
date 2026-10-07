"""grp65: 近高点过滤（120 日 / 5%）开关用产品代码跑出的逐年对比。python grp65.py D|D1 -> grp65_<V>.json"""
import os, sys, json
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from dataclasses import replace
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
V = sys.argv[1]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
off = fusion.default_config() if V == 'D' else fusion.d1_config()
on = replace(off, near_high_on=True)
assert off.hash() == (fusion.default_config() if V == 'D' else fusion.d1_config()).hash() and on.hash() != off.hash()
inp = fusion.build_inputs(panel, off, cls)
years = np.array([int(str(d)[:4]) for d in panel.dates])
def run(cfg):
    i = fusion.with_near_high_filter(inp, cfg)
    raw = fusion.simulate_fused(panel, i, cfg)
    eq = raw['eq']; ok = np.isfinite(eq); e = eq[ok]; r = e[1:] / e[:-1] - 1
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1
    dd = (e / np.maximum.accumulate(e) - 1).min()
    yr = {}
    prev = None
    for y in range(2008, 2027):
        ii = np.nonzero((years == y) & ok)[0]
        if len(ii) < 5: continue
        base = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]
        yr[y] = float(eq[ii[-1]] / base - 1)
    nt = len(raw['trades'])
    return dict(cagr=float(cagr), sharpe=float(r.mean() / r.std() * np.sqrt(245)), dd=float(dd), years=yr, trades=nt,
                days=int(i.any_gate[int(np.searchsorted(panel.dates, off.start)):].sum()), last=str(panel.dates[np.nonzero(ok)[0][-1]]))
out = dict(off=run(off), on=run(on))
json.dump(out, open(f'grp65_{V}.json', 'w'), indent=1)
print(V, 'done', {k: (round(v['cagr'], 4), round(v['sharpe'], 3), round(v['dd'], 3), v['trades'], v['days']) for k, v in out.items()})
