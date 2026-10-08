"""grp84: 产品引擎 D3（priority='CAB'）回测复现——D / D1 / D2 / D3 / D4 用 fusion.config_for 的正式配置，不再改 fusion.ORDER。
python grp84.py   （需要 ~/research/lowfreq 下的 panel_del.npz 与 grp70_inp.pkl）"""
import os, sys, pickle, json
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
dates = [str(d) for d in panel.dates]; i18 = int(np.searchsorted(dates, '2018-01-01'))
out = {}
for V in ('D', 'D1', 'D2', 'D3', 'D4'):
    cfg = fusion.config_for(V); inp = fusion.with_industry_blacklist(fusion.with_near_high_filter(replace(raw_inp), cfg), cfg, cls)
    raw = fusion.simulate_fused(panel, inp, cfg)
    eq = raw['eq']; idx = np.nonzero(np.isfinite(eq))[0]; e = eq[idx]
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; r = e[1:] / e[:-1] - 1; dd = float((e / np.maximum.accumulate(e) - 1).min())
    pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]; npre = int((idx < i18).sum()); npost = int((idx >= i18).sum())
    nS = {s: sum(1 for t in raw['trades'] if t.get('sleeve') == s) for s in 'ACB'}
    out[V] = dict(hash=cfg.hash(), cagr=float(cagr), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=dd, final=float(e[-1] / e[0]),
                  pre=float(pre ** (245 / npre) - 1), post=float(post ** (245 / npost) - 1), trades=nS)
    o = out[V]
    print(f"{V:3s} {o['hash']} 年化 {o['cagr']*100:5.1f}% 夏普 {o['sharpe']:.2f} 回撤 {o['mdd']*100:6.1f}% 终值 {o['final']:5.1f}x 2018前 {o['pre']*100:5.1f}% 后 {o['post']*100:5.1f}% 成交 {nS}", flush=True)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'grp84.json'), 'w'), ensure_ascii=False, indent=1)
