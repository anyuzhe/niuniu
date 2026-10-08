"""grp81: 各层优先级重排（C 层是否应排在 A 层前面）及 A 层权重降低。"""
import os, sys, json, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion
from quantlab.dipbuy.panel import Panel
V = sys.argv[1]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cfg0 = fusion.config_for(V); inp = fusion.with_near_high_filter(replace(raw_inp), cfg0)
nd, nc = panel.shape; dates = [str(d) for d in panel.dates]; i18 = int(np.searchsorted(dates, '2018-01-01'))
ORD0 = tuple(fusion.ORDER)
def run(order, **kw):
    fusion.ORDER = order; cfg = replace(cfg0, **kw)
    raw = fusion.simulate_fused(panel, inp, cfg)
    eq = raw['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; r = e[1:] / e[:-1] - 1; dd = float((e / np.maximum.accumulate(e) - 1).min())
    pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]; npre = int((idx < i18).sum()); npost = int((idx >= i18).sum())
    return dict(cagr=float(cagr), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=dd, cagr_pre=float(pre ** (245 / npre) - 1), cagr_post=float(post ** (245 / npost) - 1), final=float(e[-1] / e[0]))
out = {}
for lab, order, kw in (('A>C>B 基线', ('A', 'C', 'B'), {}), ('C>A>B', ('C', 'A', 'B'), {}), ('C>B>A', ('C', 'B', 'A'), {}), ('B>C>A', ('B', 'C', 'A'), {}),
                       ('A>C>B, A 权重 4%', ('A', 'C', 'B'), dict(weight_a=0.04)), ('C>A>B, A 权重 4%', ('C', 'A', 'B'), dict(weight_a=0.04)),
                       ('C>A>B, A 权重 2.5%', ('C', 'A', 'B'), dict(weight_a=0.025))):
    o = run(order, **kw); out[lab] = o
    print(V, f"{lab:20s} cagr {o['cagr']*100:5.1f} pre {o['cagr_pre']*100:5.1f} post {o['cagr_post']*100:5.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:6.1f} 终值{o['final']:5.1f}x", flush=True)
fusion.ORDER = ORD0
json.dump(out, open(f'grp81_{V}.json', 'w'), ensure_ascii=False)
