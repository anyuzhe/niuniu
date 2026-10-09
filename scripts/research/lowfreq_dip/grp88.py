"""grp88: 用广度/波动/成交额恐慌计数决定新开仓位大小（预先登记见档案 §130）。python grp88.py run | report"""
import os, sys, json, pickle, time, inspect
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
mode = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
dates = np.array([str(d) for d in panel.dates]); nd, nc = panel.shape; years = np.array([int(d[:4]) for d in dates]); i18 = int(np.searchsorted(dates, '2018-01-01'))
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
F = np.load(os.path.join(HERE, 'grp87_feat.npz'))
def cond(x, th, d):
    with np.errstate(invalid='ignore'): r = (x >= th) if d == 1 else (x <= th)
    return np.where(np.isfinite(x), r, False)
p = cond(F['br5'], .80, 1).astype(int) + cond(F['vol'], 1.25, 1) + cond(F['amt'], 1.0, 1) + cond(F['spd'], -1.5, -1)
SCHEMES = {'BASE': np.ones(nd), 'UP': np.where(p >= 3, 1.5, 1.0), 'DOWN': np.where(p == 0, 0.5, 1.0),
           'BOTH': np.where(p == 0, 0.5, np.where(p >= 3, 1.5, 1.0)), 'LIN': 0.5 + 0.25 * p}
src = inspect.getsource(fusion.simulate_fused); assert src.count('size = min(W[s] * equity, G * equity - invested)') == 1
src = src.replace('def simulate_fused(', 'def simulate_fused_mult(').replace('size = min(W[s] * equity, G * equity - invested)', 'size = min(W[s] * MULT[t] * equity, G * equity - invested)')
exec(src, fusion.__dict__)
def ex15(eq):
    ok = np.isfinite(eq); e = eq[ok]; yy = years[ok]; r = e[1:] / e[:-1] - 1; r = np.where(yy[1:] == 2015, 0.0, r)
    g = np.cumprod(1 + r); return float(g[-1] ** (245 / len(g)) - 1)
CACHE = os.path.join(HERE, 'grp88_cache.json'); cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
def sim(V, sch):
    key = f'{V}|{sch}'
    if key in cache: return cache[key]
    cfg = fusion.config_for(V); inp = fusion.with_industry_blacklist(fusion.with_near_high_filter(replace(raw_inp), cfg), cfg, cls)
    fusion.MULT = SCHEMES[sch]; raw = fusion.simulate_fused_mult(panel, inp, cfg)
    eq = raw['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]; r = e[1:] / e[:-1] - 1
    n0 = int((idx < i18).sum()); n1 = int((idx >= i18).sum()); pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]
    o = dict(cagr=float((e[-1] / e[0]) ** (245 / len(e)) - 1), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=float((e / np.maximum.accumulate(e) - 1).min()),
             final=float(e[-1] / e[0]), pre=float(pre ** (245 / n0) - 1), post=float(post ** (245 / n1) - 1), ex15=ex15(eq),
             expo=float(np.nanmean(raw['expo'][idx])), n=len(raw['trades']))
    cache[key] = o; json.dump(cache, open(CACHE, 'w'), ensure_ascii=False); return o
if mode == 'run':
    for V in ('D', 'D2'):
        for s in SCHEMES: sim(V, s)
    print('done')
for V in ('D', 'D2'):
    b = cache.get(f'{V}|BASE')
    if not b: continue
    print(f"\n== {V} 基线 {b['cagr']*100:.1f}% 夏普 {b['sharpe']:.2f} 回撤 {b['mdd']*100:.1f}% 终值 {b['final']:.1f}x 前 {b['pre']*100:.1f}% 后 {b['post']*100:.1f}% 去2015 {b['ex15']*100:.1f}% 平均仓位 {b['expo']*100:.1f}% 成交 {b['n']}")
    for s in ('UP', 'DOWN', 'BOTH', 'LIN'):
        o = cache.get(f'{V}|{s}')
        if o: print(f"  {s:5s} {o['cagr']*100:5.1f}% ({(o['cagr']-b['cagr'])*100:+.1f}) 夏普 {o['sharpe']:.2f} 回撤 {o['mdd']*100:6.1f}% ({(o['mdd']-b['mdd'])*100:+.1f}) 前 {(o['pre']-b['pre'])*100:+5.1f} 后 {(o['post']-b['post'])*100:+5.1f} 去2015 {(o['ex15']-b['ex15'])*100:+5.1f} 平均仓位 {o['expo']*100:.1f}% 成交 {o['n']}")
