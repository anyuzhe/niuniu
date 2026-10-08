"""grp72: B 层加个股层规则（只作用于 B 层候选池）后 D / D2 的回测。
python grp72.py named V | placebo V seed n rule  -> grp72_<mode>_<V>.json
规则（阈值事先固定，不在样本内挑）：
  S250_x   个股前 250 日涨跌 >= x（不足 250 日的不过滤）
  N_k      触发当天该行业参与成分股数 st.n >= k
  I250_x   该行业成分股前 250 日平均涨跌 >= x"""
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
i18 = int(np.searchsorted(dates, '2018-01-01'))
c = panel.c.astype(np.float64); labels = np.asarray(cls.labels); st = inp0.ind_state
ngrp = st.n.shape[1]
r250 = np.full((nd, nc), np.nan); r250[250:] = c[250:] / c[:-250] - 1
ind_r250 = np.full((nd, ngrp), np.nan)
for g in range(ngrp):
    cols = np.nonzero(labels == g)[0]
    if len(cols): 
        with np.errstate(all='ignore'):
            ind_r250[:, g] = np.nanmean(r250[:, cols], axis=1)
lab_ok = labels >= 0
n_stock = np.where(lab_ok[None, :], st.n[:, np.clip(labels, 0, ngrp - 1)], np.nan)
ir_stock = np.where(lab_ok[None, :], ind_r250[:, np.clip(labels, 0, ngrp - 1)], np.nan)
def rule(name):
    k, x = name.split('_'); x = float(x)
    if k == 'S250': return ~(r250 < x)          # NaN 视为通过
    if k == 'N': return ~(n_stock < x)
    if k == 'I250': return ~(ir_stock < x)
    raise ValueError(name)
def run(names, extra=None):
    keep = np.ones((nd, nc), bool)
    for n in names: keep &= rule(n)
    if extra is not None: keep &= extra
    B = inp0.pools['B']
    inp = replace(inp0, pools={**inp0.pools, 'B': B & keep})
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
    return dict(rules=list(names), cagr=float(cagr), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=dd,
                cagr_pre=float(pre ** (245 / npre) - 1), cagr_post=float(post ** (245 / npost) - 1),
                years=yr, nB=len(bt), meanB=float(np.mean(bt)) if bt else None,
                keep_frac=float((keep & B).sum() / max(1, B.sum())))
SETS = {'base': [], 'S250_-0.2': ['S250_-0.2'], 'S250_-0.1': ['S250_-0.1'], 'S250_0': ['S250_0'],
        'N_20': ['N_20'], 'N_30': ['N_30'], 'N_40': ['N_40'],
        'I250_-0.1': ['I250_-0.1'], 'I250_0': ['I250_0'],
        'S-0.1+N30': ['S250_-0.1', 'N_30'], 'I0+N30': ['I250_0', 'N_30'], 'S-0.1+I0': ['S250_-0.1', 'I250_0']}
t0 = time.time(); out = {}
if mode == 'named':
    which = sys.argv[3].split(',') if len(sys.argv) > 3 else list(SETS)
    for k in which:
        out[k] = run(SETS[k]); o = out[k]
        print(V, k, f"cagr {o['cagr']*100:.1f} pre {o['cagr_pre']*100:.1f} post {o['cagr_post']*100:.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:.1f} nB {o['nB']} meanB {o['meanB']} keep {o['keep_frac']:.2f}", round(time.time()-t0), 's', flush=True)
    json.dump(out, open(f"grp72_named_{V}_{which[0].replace('/','')}_{len(which)}.json", 'w'), ensure_ascii=False)
elif mode == 'placebo':
    seed, n, rl = int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    kf = run(SETS[rl])['keep_frac']; rng = np.random.default_rng(seed); res = []
    for _ in range(n):
        r = run([], extra=rng.random((nd, nc)) < kf); res.append(r)
        print(V, 'placebo', rl, round(kf, 2), round(r['cagr']*100, 1), round(r['cagr_post']*100, 1), round(time.time()-t0), 's', flush=True)
        if time.time() - t0 > 90: break
    json.dump(res, open(f'grp72_placebo_{V}_{rl}_{seed}.json', 'w'))

if mode == 'ngrid':
    for k in (10, 15, 20, 25, 30, 35, 40, 50, 60, 80):
        SETS[f'N_{k}'] = [f'N_{k}']
        o = run([f'N_{k}']); out[k] = o
        print(V, 'N>=', k, f"cagr {o['cagr']*100:.1f} pre {o['cagr_pre']*100:.1f} post {o['cagr_post']*100:.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:.1f} nB {o['nB']} keep {o['keep_frac']:.2f}", flush=True)
    json.dump(out, open(f'grp72_ngrid_{V}.json', 'w'))
elif mode == 'permn':
    seed, n, k = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]); rng = np.random.default_rng(seed); res = []
    base_keep = run([f'N_{k}'])['keep_frac']
    for _ in range(n):
        perm = rng.permutation(ngrp)          # 把“行业 → 成分股数序列”随机对调
        ns = np.where(lab_ok[None, :], st.n[:, perm[np.clip(labels, 0, ngrp - 1)]], np.nan)
        r = run([], extra=~(ns < k)); res.append(r)
        print(V, 'permN', k, f"keep {r['keep_frac']:.2f} cagr {r['cagr']*100:.1f} post {r['cagr_post']*100:.1f}", round(time.time()-t0), 's', flush=True)
        if time.time() - t0 > 85: break
    json.dump(dict(real_keep=base_keep, res=res), open(f'grp72_permn_{V}_{k}_{seed}.json', 'w'))
