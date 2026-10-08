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

if mode == 'trend':
    # 行业综合指数（成分股等权）的大趋势过滤
    def ma(a, w):
        cs = np.cumsum(a, axis=0); out = np.full_like(a, np.nan); out[w - 1:] = (cs[w - 1:] - np.vstack([np.zeros((1, a.shape[1])), cs[:-w]])) / w; return out
    m60, m120, m250 = ma(idx, 60), ma(idx, 120), ma(idx, 250)
    def lag(a, k): o = np.full_like(a, np.nan); o[k:] = a[:-k]; return o
    r120i = idx / lag(idx, 120) - 1; r250i = idx / lag(idx, 250) - 1
    hi500 = np.full_like(idx, np.nan)
    for t in range(499, nd): hi500[t] = idx[t - 499:t + 1].max(axis=0)
    F2 = {'idx>MA120': idx > m120, 'idx>MA250': idx > m250,
          'MA250上行': m250 > lag(m250, 20), 'MA120上行': m120 > lag(m120, 20),
          'idx>MA250*0.9': idx > 0.9 * m250, 'idx>MA250*0.8': idx > 0.8 * m250,
          'r120>=-10%': r120i >= -0.10, 'r250>=0': r250i >= 0, 'r250>=-10%': r250i >= -0.10,
          '离500日高点>-30%': idx / hi500 - 1 > -0.30, '离500日高点>-40%': idx / hi500 - 1 > -0.40,
          'MA60>MA250': m60 > m250}
    def runf(name, nan_pass=True):
        f = F2[name]; ok = np.isfinite(f.astype(float)) 
        # NaN 比较得到 False，需要让数据不足的日子通过
        base = {'idx>MA120': m120, 'idx>MA250': m250, 'MA250上行': lag(m250, 20), 'MA120上行': lag(m120, 20), 'idx>MA250*0.9': m250, 'idx>MA250*0.8': m250,
                'r120>=-10%': r120i, 'r250>=0': r250i, 'r250>=-10%': r250i, '离500日高点>-30%': hi500, '离500日高点>-40%': hi500, 'MA60>MA250': m250}[name]
        f = f | ~np.isfinite(base)
        extra = np.where(lab_ok[None, :], f[:, np.clip(labels, 0, ngrp - 1)], True)
        return extra, f
    res = {}
    for name in F2:
        extra, f = runf(name); o = run([], extra=extra); res[name] = o
        print(V, f"{name:14s} cagr {o['cagr']*100:.1f} pre {o['cagr_pre']*100:.1f} post {o['cagr_post']*100:.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:.1f} nB {o['nB']} meanB {o['meanB']*100:.1f} keep {o['keep_frac']:.2f}", flush=True)
        if name in ('idx>MA250', 'r250>=0', 'MA250上行'):
            e2 = extra & rule('N_30'); o2 = run([], extra=e2)
            print(V, f"{name:14s}+N30 cagr {o2['cagr']*100:.1f} pre {o2['cagr_pre']*100:.1f} post {o2['cagr_post']*100:.1f} sh {o2['sharpe']:.2f} mdd {o2['mdd']*100:.1f} nB {o2['nB']} keep {o2['keep_frac']:.2f}", flush=True)
    json.dump(res, open(f'grp74_trend_{V}.json', 'w'), ensure_ascii=False)

if mode == 'trendperm':
    name, nperm, seed = sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
    def ma(a, w):
        cs = np.cumsum(a, axis=0); out = np.full_like(a, np.nan); out[w - 1:] = (cs[w - 1:] - np.vstack([np.zeros((1, a.shape[1])), cs[:-w]])) / w; return out
    def lag(a, k): o = np.full_like(a, np.nan); o[k:] = a[:-k]; return o
    m60, m250 = ma(idx, 60), ma(idx, 250); r250i = idx / lag(idx, 250) - 1
    f, base = {'r250>=0': (r250i >= 0, r250i), 'MA60>MA250': (m60 > m250, m250)}[name]
    f = f | ~np.isfinite(base)
    real = run([], extra=np.where(lab_ok[None, :], f[:, np.clip(labels, 0, ngrp - 1)], True)); rng = np.random.default_rng(seed); res = []
    print(V, name, 'real', round(real['cagr'] * 100, 1), round(real['cagr_post'] * 100, 1), 'keep', round(real['keep_frac'], 2), flush=True)
    for _ in range(nperm):
        perm = rng.permutation(ngrp); fp = f[:, perm]       # 把行业的趋势序列随机对调给别的行业
        r = run([], extra=np.where(lab_ok[None, :], fp[:, np.clip(labels, 0, ngrp - 1)], True)); res.append(r)
        print(V, 'perm', round(r['cagr'] * 100, 1), round(r['cagr_post'] * 100, 1), round(r['keep_frac'], 2), flush=True)
        if time.time() - t0 > 80: break

def _quality_features():
    lidx = np.log(idx); dr = np.full_like(idx, np.nan); dr[1:] = lidx[1:] - lidx[:-1]
    def rsum(a, w):
        cs = np.cumsum(np.nan_to_num(a), axis=0); out = np.full_like(a, np.nan); out[w:] = cs[w:] - cs[:-w]; return out
    net250 = np.full_like(idx, np.nan); net250[250:] = lidx[250:] - lidx[:-250]
    path250 = rsum(np.abs(dr), 250); er250 = net250 / path250
    down250 = rsum((dr < 0).astype(float), 250) / 250
    hi250 = np.full_like(idx, np.nan)
    for t in range(249, nd): hi250[t] = idx[t - 249:t + 1].max(axis=0)
    dd250 = idx / hi250 - 1
    lo60 = np.full_like(idx, np.nan)
    # 近 60 日里创 120 日新低的天数占比
    lo120 = np.full_like(idx, np.nan)
    for t in range(119, nd): lo120[t] = idx[t - 119:t + 1].min(axis=0)
    newlow = (idx <= lo120 * 1.0000001).astype(float); nl60 = rsum(newlow, 60) / 60
    return dict(net250=net250, er250=er250, down250=down250, dd250=dd250, nl60=nl60)
if mode == 'quality':
    Q = _quality_features(); r250i = Q['net250']
    def blk(name):
        n, e, d, dd, nl = Q['net250'], Q['er250'], Q['down250'], Q['dd250'], Q['nl60']
        if name == 'ref r250>=0': return n < 0
        if name == 'ER<-0.05': return e < -0.05
        if name == 'ER<-0.10': return e < -0.10
        if name == 'ER<-0.15': return e < -0.15
        if name == 'down日>51%且r250<0': return (d > 0.51) & (n < 0)
        if name == 'r250<0且未深跌(dd>-35%)': return (n < 0) & (dd > -0.35)
        if name == 'r250<0且未深跌(dd>-30%)': return (n < 0) & (dd > -0.30)
        if name == 'r250<0且未深跌(dd>-40%)': return (n < 0) & (dd > -0.40)
        if name == 'ER<-0.10且未深跌(dd>-35%)': return (e < -0.10) & (dd > -0.35)
        if name == 'ER<-0.05且未深跌(dd>-35%)': return (e < -0.05) & (dd > -0.35)
        if name == 'r250<0且近60日新低多(>30%)': return (n < 0) & (nl > 0.30)
        if name == 'ER<-0.05且近60日新低多': return (e < -0.05) & (nl > 0.30)
    NAMES = ['ref r250>=0', 'ER<-0.05', 'ER<-0.10', 'ER<-0.15', 'down日>51%且r250<0', 'r250<0且未深跌(dd>-30%)', 'r250<0且未深跌(dd>-35%)', 'r250<0且未深跌(dd>-40%)',
             'ER<-0.05且未深跌(dd>-35%)', 'ER<-0.10且未深跌(dd>-35%)', 'r250<0且近60日新低多(>30%)', 'ER<-0.05且近60日新低多']
    res = {}
    for name in NAMES:
        b = blk(name); f = ~(b & np.isfinite(Q['net250']))
        extra = np.where(lab_ok[None, :], f[:, np.clip(labels, 0, ngrp - 1)], True); o = run([], extra=extra); res[name] = dict(o, F=None)
        print(V, f"{name:26s} cagr {o['cagr']*100:.1f} pre {o['cagr_pre']*100:.1f} post {o['cagr_post']*100:.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:.1f} nB {o['nB']} meanB {o['meanB']*100:.1f} keep {o['keep_frac']:.2f}", flush=True)
    json.dump({k: {kk: vv for kk, vv in v.items() if kk != 'F'} for k, v in res.items()}, open(f'grp74_quality_{V}.json', 'w'), ensure_ascii=False)

if mode == 'zthr':
    # B 层候选只在“行业 z 足够深”时才买（行业 z <= thr2）；其余不变
    res = {}
    for thr2 in (-1.5, -1.75, -2.0, -2.25, -2.5):
        f = ~(z > thr2)                                   # z 为 NaN 视为通过（不会出现在触发行业里）
        extra = np.where(lab_ok[None, :], f[:, np.clip(labels, 0, ngrp - 1)], True); o = run([], extra=extra); res[thr2] = o
        print(V, thr2, f"cagr {o['cagr']*100:.1f} pre {o['cagr_pre']*100:.1f} post {o['cagr_post']*100:.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:.1f} nB {o['nB']} meanB {o['meanB']*100:.1f} keep {o['keep_frac']:.2f}", flush=True)
    json.dump({str(k): v for k, v in res.items()}, open(f'grp74_zthr_{V}.json', 'w'), ensure_ascii=False)

if mode == 'breadth':
    # B 层只在“同一天触发的行业数 >= k”（行业信号广泛）时买；或只在“孤立行业恐慌”（<= k）时买，作对照
    br = np.nansum(z <= -1.5, axis=1); res = {}
    for lab, f in (('base', np.ones(nd, bool)), ('>=2', br >= 2), ('>=4', br >= 4), ('>=6', br >= 6), ('>=9', br >= 9), ('<=3', br <= 3), ('<=8', br <= 8)):
        extra = np.repeat(f[:, None], nc, axis=1); o = run([], extra=extra); res[lab] = o
        print(V, f"{lab:5s} cagr {o['cagr']*100:.1f} pre {o['cagr_pre']*100:.1f} post {o['cagr_post']*100:.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:.1f} nB {o['nB']} meanB {(o['meanB'] or 0)*100:.1f} keep {o['keep_frac']:.2f}", flush=True)
    json.dump(res, open(f'grp74_breadth_{V}.json', 'w'), ensure_ascii=False)
