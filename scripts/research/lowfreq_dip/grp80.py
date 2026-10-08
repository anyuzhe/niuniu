"""grp80: 各层的边际贡献——去掉 B 层（以及 A、C 层作对照）后 D / D2 的回测。"""
import os, sys, json, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion
from quantlab.dipbuy.panel import Panel
V = sys.argv[1]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cfg = fusion.config_for(V); inp0 = fusion.with_near_high_filter(replace(raw_inp), cfg)
nd, nc = panel.shape; dates = [str(d) for d in panel.dates]; years = np.array([int(d[:4]) for d in dates]); i18 = int(np.searchsorted(dates, '2018-01-01'))
def run(drop):
    pools = {k: (np.zeros_like(v) if k in drop else v) for k, v in inp0.pools.items()}
    raw = fusion.simulate_fused(panel, replace(inp0, pools=pools), cfg)
    eq = raw['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; r = e[1:] / e[:-1] - 1; dd = float((e / np.maximum.accumulate(e) - 1).min())
    pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]; npre = int((idx < i18).sum()); npost = int((idx >= i18).sum())
    yr = {}
    for y in range(2008, 2027):
        ii = np.nonzero((years == y) & ok)[0]
        if len(ii) > 5:
            base = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]; yr[y] = float(eq[ii[-1]] / base - 1)
    return dict(drop=sorted(drop), cagr=float(cagr), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=dd, cagr_pre=float(pre ** (245 / npre) - 1),
                cagr_post=float(post ** (245 / npost) - 1), years=yr, expo=float(np.nanmean(raw['expo'][ok])), n=len(raw['trades']), final=float(e[-1] / e[0]))
out = {}
for lab, d in (('全开 A+C+B', []), ('去掉 B', ['B']), ('去掉 C', ['C']), ('去掉 A', ['A']), ('只有 A', ['B', 'C']), ('只有 C', ['A', 'B']), ('只有 B', ['A', 'C'])):
    o = run(set(d)); out[lab] = o
    print(V, f"{lab:10s} cagr {o['cagr']*100:5.1f} pre {o['cagr_pre']*100:5.1f} post {o['cagr_post']*100:5.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:6.1f} 终值{o['final']:5.1f}x 平均仓位{o['expo']*100:3.0f}% 成交{o['n']}", flush=True)
json.dump(out, open(f'grp80_{V}.json', 'w'), ensure_ascii=False)
a, b = out['全开 A+C+B']['years'], out['去掉 B']['years']
print(V, '去掉 B 后各年（相对全开，百分点）：', ' '.join(f"{y}:{(b[y]-a[y])*100:+.0f}" for y in sorted(a)))
print(V, '去掉 B 后比全开好的年数', sum(b[y] > a[y] + 1e-9 for y in a), '差的年数', sum(b[y] < a[y] - 1e-9 for y in a), '相同', sum(abs(b[y]-a[y]) <= 1e-9 for y in a))
