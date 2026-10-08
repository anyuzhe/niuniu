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

# ---- 行业“止跌确认”特征（只用 t 日及以前的信息）
idx = np.ones((nd, ngrp))
retm = np.full((nd, nc), np.nan); retm[1:] = c[1:] / c[:-1] - 1
for g in range(ngrp):
    cols = np.nonzero(labels == g)[0]
    if len(cols):
        with np.errstate(all='ignore'): r = np.nanmean(retm[:, cols], axis=1)
        idx[:, g] = np.cumprod(1 + np.nan_to_num(r, nan=0.0))
z = st.z
def roll_min(a, w):
    out = np.full_like(a, np.nan)
    for t in range(w - 1, len(a)): out[t] = np.nanmin(a[t - w + 1:t + 1], axis=0)
    return out
r1 = np.full((nd, ngrp), np.nan); r1[1:] = idx[1:] / idx[:-1] - 1
r3 = np.full((nd, ngrp), np.nan); r3[3:] = idx[3:] / idx[:-3] - 1
zmin5 = roll_min(z, 5)
F = {'R1': r1 > 0, 'R3': r3 > 0, 'R3b': r3 > 0.01,
     'Zup': np.concatenate([np.zeros((1, ngrp), bool), z[1:] > z[:-1]]),
     'Zoff5': (z - zmin5) >= 0.3}
def rule(name):
    if name in F: return np.where(lab_ok[None, :], F[name][:, np.clip(labels, 0, ngrp - 1)], True)
    k, x = name.split('_'); x = float(x)
    if k == 'N': return ~(n_stock < x)
    if k == 'I250': return ~(ir_stock < x)
    raise ValueError(name)
SETS = {'base': [], 'R1': ['R1'], 'R3': ['R3'], 'R3b': ['R3b'], 'Zup': ['Zup'], 'Zoff5': ['Zoff5'],
        'N30': ['N_30'], 'R3+N30': ['R3', 'N_30'], 'Zoff5+N30': ['Zoff5', 'N_30'], 'Zup+N30': ['Zup', 'N_30']}
t0 = time.time(); out = {}
if mode == 'named':
    for k in SETS:
        o = run(SETS[k]); out[k] = o
        print(V, k, f"cagr {o['cagr']*100:.1f} pre {o['cagr_pre']*100:.1f} post {o['cagr_post']*100:.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:.1f} nB {o['nB']} meanB {o['meanB']*100:.1f} keep {o['keep_frac']:.2f}", round(time.time()-t0), 's', flush=True)
    json.dump(out, open(f'grp74_named_{V}.json', 'w'), ensure_ascii=False)
elif mode == 'placebo':
    seed, n, rl = int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    kf = run(SETS[rl])['keep_frac']; rng = np.random.default_rng(seed); res = []
    for _ in range(n):
        r = run([], extra=rng.random((nd, nc)) < kf); res.append(r)
        print(V, 'placebo', rl, round(kf, 2), round(r['cagr']*100, 1), round(r['cagr_post']*100, 1), round(time.time()-t0), 's', flush=True)
        if time.time() - t0 > 80: break

if mode == 'hist':
    # 自适应黑名单：某行业上一个已结束的有成交的段，账户平均收益低于 thr，就跳过它的新段（只用过去的结果）。
    # 段与结果来自 grp69_<V>.json 的未过滤成交（近似：过滤后成交会变，这里只作检验）。
    import collections
    T = json.load(open(f'grp69_{V}.json'))['trades']
    by = collections.defaultdict(list)
    for tr in T: by[tr['ind']].append(tr)
    name_idx = {n: i for i, n in enumerate(cls.names)}
    di = {d: i for i, d in enumerate(dates)}
    def build(thr, mode_):
        keep_g = np.ones((nd, ngrp), bool)
        for ind, rs in by.items():
            rs.sort(key=lambda r: r['signal']); eps = []; cur = []
            for r in rs:
                if cur and (np.datetime64(r['signal']) - np.datetime64(cur[-1]['signal'])).astype(int) > 25: eps.append(cur); cur = []
                cur.append(r)
            if cur: eps.append(cur)
            g = name_idx[ind]; info = [(di[e[-1]['signal']] + 21, float(np.mean([r['ret'] for r in e]))) for e in eps]   # (结束下标, 段均值)
            starts = [di[e[0]['signal']] for e in eps]
            for k in range(1, len(eps)):
                done = [m for (end, m) in info[:k] if end <= starts[k]]
                if not done: continue
                v = done[-1] if mode_ == 'last' else float(np.mean(done))
                if v < thr:
                    lo = starts[k] - 3; hi = (starts[k + 1] - 3) if k + 1 < len(eps) else nd
                    keep_g[lo:hi, g] = False
        return keep_g
    for mode_ in ('last', 'cum'):
        for thr in (-0.03, -0.05, -0.08):
            kg = build(thr, mode_); extra = np.where(lab_ok[None, :], kg[:, np.clip(labels, 0, ngrp - 1)], True)
            o = run([], extra=extra)
            print(V, mode_, thr, f"cagr {o['cagr']*100:.1f} pre {o['cagr_pre']*100:.1f} post {o['cagr_post']*100:.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:.1f} nB {o['nB']} meanB {o['meanB']*100:.1f} keep {o['keep_frac']:.2f}", flush=True)
