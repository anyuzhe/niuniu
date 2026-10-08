"""grp83: D3（D2 + C 优先）再把 B 层里那几个差行业剔除。
python grp83.py named V | oos V | placebo V seed n K"""
import os, sys, json, pickle, time, collections
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
mode, V = sys.argv[1], sys.argv[2]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cfg = fusion.config_for(V); inp0 = fusion.with_near_high_filter(replace(raw_inp), cfg)
nd, nc = panel.shape; dates = [str(d) for d in panel.dates]; years = np.array([int(d[:4]) for d in dates]); i18 = int(np.searchsorted(dates, '2018-01-01'))
ind_of = np.array([cls.name_of(j) for j in range(nc)]); ALL = sorted(set(ind_of))
ORD0 = tuple(fusion.ORDER)
def run(excl, order):
    fusion.ORDER = order
    keep = ~np.isin(ind_of, list(excl))
    inp = replace(inp0, pools={**inp0.pools, 'B': inp0.pools['B'] & keep[None, :]})
    raw = fusion.simulate_fused(panel, inp, cfg)
    eq = raw['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; r = e[1:] / e[:-1] - 1; dd = float((e / np.maximum.accumulate(e) - 1).min())
    pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]; npre = int((idx < i18).sum()); npost = int((idx >= i18).sum())
    yr = {}
    for y in range(2008, 2027):
        ii = np.nonzero((years == y) & ok)[0]
        if len(ii) > 5:
            base = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]; yr[y] = float(eq[ii[-1]] / base - 1)
    bt = [t['ret'] for t in raw['trades'] if t.get('sleeve') == 'B']
    return dict(excl=sorted(excl), cagr=float(cagr), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=dd, cagr_pre=float(pre ** (245 / npre) - 1), cagr_post=float(post ** (245 / npost) - 1),
                years=yr, nB=len(bt), meanB=float(np.mean(bt)) if bt else None, final=float(e[-1] / e[0]))
S1 = ['国防军工']; S2 = S1 + ['环保', '煤炭', '基础化工']; S3 = S2 + ['家用电器', '美容护理']; S4 = S3 + ['房地产']
CORD = ('C', 'A', 'B'); out = {}; t0 = time.time()
if mode == 'named':
    for lab, order in (('原优先级 A>C>B', ORD0), ('C 优先 (D3)', CORD)):
        for k, ex in (('不剔除', []), ('S1 国防军工', S1), ('S2 +环保煤炭基础化工', S2), ('S3 +家电美容护理', S3), ('S4 +房地产', S4)):
            o = run(ex, order); out[f'{lab}|{k}'] = o
            print(V, f"{lab:14s} {k:20s} cagr {o['cagr']*100:5.1f} pre {o['cagr_pre']*100:5.1f} post {o['cagr_post']*100:5.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:6.1f} 终值{o['final']:5.1f}x B成交{o['nB']} B均值{(o['meanB'] or 0)*100:+.1f}%", flush=True)
    json.dump(out, open(f'grp83_named_{V}.json', 'w'), ensure_ascii=False)
elif mode == 'oos':
    T = [t for t in json.load(open(f'grp69_{V}.json'))['trades'] if t['signal'] < '2018-01-01']
    by = collections.defaultdict(list)
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
    print(V, '2018 前最差 4 个行业', worst)
    for lab, order in (('原优先级', ORD0), ('C 优先 (D3)', CORD)):
        a = run([], order); b = run(worst, order)
        print(V, lab, f"不剔除 全期 {a['cagr']*100:.1f} 2018后 {a['cagr_post']*100:.1f} | 剔除 全期 {b['cagr']*100:.1f} 2018后 {b['cagr_post']*100:.1f}（2018后 {(b['cagr_post']-a['cagr_post'])*100:+.1f}）", flush=True)
elif mode == 'placebo':
    seed, n, K = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]); rng = np.random.default_rng(seed); res = []
    for _ in range(n):
        s = list(rng.choice(ALL, K, replace=False)); r = run(s, CORD); res.append(r['cagr'])
        if time.time() - t0 > 85: break
    real = run(S4 if K == 7 else S2 if K == 4 else S1, CORD)['cagr']; res = np.array(res)
    print(V, f'K={K} 随机 {len(res)} 次 年化 5/50/95/max', np.percentile(res, [5, 50, 95, 100]).round(3), '真实', round(real, 3), '真实高于随机比例', (res < real).mean().round(2))
fusion.ORDER = ORD0
