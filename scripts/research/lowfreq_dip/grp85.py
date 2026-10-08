"""grp85: D3 里把 B 层某个行业关掉，到底哪些真的有用？——单行业剔除 + 前后半段互相验证。
python grp85.py single V          # 逐个行业剔除（31 次），记全段 / 2018前 / 2018后 年化
python grp85.py cross V           # 用一半挑、另一半验证（前→后、后→前），k = 1,2,3,5,7；以及单行业增益在前后半段的相关性
"""
import os, sys, json, time
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import pickle
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
mode, V = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cfg = fusion.config_for(V); inp0 = fusion.with_near_high_filter(replace(raw_inp), cfg)
nd, nc = panel.shape; dates = [str(d) for d in panel.dates]; i18 = int(np.searchsorted(dates, '2018-01-01'))
ind_of = np.array([cls.name_of(j) for j in range(nc)]); ALL = sorted(set(ind_of) - {''})
CACHE = os.path.join(HERE, f'grp85_cache_{V}.json')
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
def run(excl):
    key = '|'.join(sorted(excl))
    if key in cache: return cache[key]
    keep = ~np.isin(ind_of, list(excl))
    inp = replace(inp0, pools={**inp0.pools, 'B': inp0.pools['B'] & keep[None, :]})
    eq = fusion.simulate_fused(panel, inp, cfg)['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]
    npre = int((idx < i18).sum()); npost = int((idx >= i18).sum())
    pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]
    o = dict(cagr=float((e[-1] / e[0]) ** (245 / len(e)) - 1), pre=float(pre ** (245 / npre) - 1), post=float(post ** (245 / npost) - 1),
             mdd=float((e / np.maximum.accumulate(e) - 1).min()))
    cache[key] = o; json.dump(cache, open(CACHE, 'w'), ensure_ascii=False)
    return o
t0 = time.time(); base = run([])
print(V, 'base', {k: round(v * 100, 1) for k, v in base.items()}, 'n_ind', len(ALL), flush=True)
def gains(excl):
    o = run(excl); return {k: (o[k] - base[k]) * 100 for k in ('cagr', 'pre', 'post')} | {'mdd': (o['mdd'] - base['mdd']) * 100}
if mode == 'single':
    rows = []
    for k in ALL:
        if time.time() - t0 > 100: print('time budget hit; rerun to continue'); break
        g = gains([k]); rows.append((k, g))
    rows.sort(key=lambda r: -r[1]['cagr'])
    n_B = {}
    for k, g in rows: print(f"{k:8s} 全段 {g['cagr']:+5.2f}  前 {g['pre']:+5.2f}  后 {g['post']:+5.2f}  回撤 {g['mdd']:+5.2f}")
    json.dump(dict(base=base, rows=rows), open(os.path.join(HERE, f'grp85_single_{V}.json'), 'w'), ensure_ascii=False, indent=1)
elif mode == 'cross':
    g1 = {k: gains([k]) for k in ALL}
    pre = np.array([g1[k]['pre'] for k in ALL]); post = np.array([g1[k]['post'] for k in ALL])
    print('单行业剔除增益：前半段 vs 后半段 的 Pearson 相关 %.2f，Spearman %.2f' % (np.corrcoef(pre, post)[0, 1],
          np.corrcoef(np.argsort(np.argsort(pre)), np.argsort(np.argsort(post)))[0, 1]), flush=True)
    both = [k for k in ALL if g1[k]['pre'] > 0 and g1[k]['post'] > 0 and g1[k]['cagr'] > 0.3]
    print('前后半段都为正、全段 >0.3 点的行业：', [(k, round(g1[k]['pre'], 2), round(g1[k]['post'], 2)) for k in both], flush=True)
    res = {}
    for src, dst in (('pre', 'post'), ('post', 'pre')):
        order = sorted(ALL, key=lambda k: -g1[k][src])
        for K in (1, 2, 3, 5, 7):
            if time.time() - t0 > 105: print('time budget hit; rerun'); break
            ex = order[:K]; g = gains(ex)
            res[f'{src}->{dst}|{K}'] = dict(excl=ex, sel=g[src], oos=g[dst], full=g['cagr'])
            print(f"{src}段挑前{K}个 {ex} → 挑选段 {g[src]:+5.2f}，另一半 {g[dst]:+5.2f}，全段 {g['cagr']:+5.2f}", flush=True)
    json.dump(dict(base=base, single=g1, cross=res), open(os.path.join(HERE, f'grp85_cross_{V}.json'), 'w'), ensure_ascii=False, indent=1)
elif mode == 'pair':
    seed, n = int(sys.argv[3]), int(sys.argv[4])
    g = gains(['房地产', '国防军工'])
    print(f"剔除 房地产+国防军工：全段 {g['cagr']:+.2f} 前 {g['pre']:+.2f} 后 {g['post']:+.2f} 回撤 {g['mdd']:+.2f}", flush=True)
    eff = [k for k in ALL if not k.isdigit()]; rng = np.random.default_rng(seed); got = []
    for _ in range(n):
        if time.time() - t0 > 100: break
        ex = list(rng.choice(eff, 2, replace=False)); gg = gains(ex); got.append((gg['cagr'], gg['pre'], gg['post']))
    a = np.array(got)
    print(f"随机剔除 2 个行业 {len(a)} 次：全段增益 均值 {a[:,0].mean():+.2f} 标准差 {a[:,0].std():.2f} 95分位 {np.percentile(a[:,0],95):+.2f} 最大 {a[:,0].max():+.2f}；"
          f"其中前后半段都为正的占 {((a[:,1]>0)&(a[:,2]>0)).mean()*100:.0f}%，真实组合全段 {g['cagr']:+.2f} 在随机里的名次 {(a[:,0]>=g['cagr']).sum()+1}/{len(a)+1}")
elif mode == 'add':
    PAIR = ['房地产', '国防军工']; b2 = run(PAIR)
    print('已剔除 房地产+国防军工 的基线', {k: round(v * 100, 1) for k, v in b2.items()}, flush=True)
    eff = [k for k in ALL if not k.isdigit() and k not in PAIR]; rows = []
    for k in eff:
        if time.time() - t0 > 105: print('time budget hit; rerun'); break
        o = run(PAIR + [k]); rows.append((k, {x: (o[x] - b2[x]) * 100 for x in ('cagr', 'pre', 'post', 'mdd')}))
    rows.sort(key=lambda r: -r[1]['cagr'])
    for k, g in rows: print(f"+{k:8s} 全段 {g['cagr']:+5.2f}  前 {g['pre']:+5.2f}  后 {g['post']:+5.2f}  回撤 {g['mdd']:+5.2f}")
    pre = np.array([g['pre'] for _, g in rows]); post = np.array([g['post'] for _, g in rows])
    print('在已剔除两个的基础上，再加一个行业：前后半段增益相关 %.2f' % np.corrcoef(pre, post)[0, 1])
    json.dump(dict(base=b2, rows=rows), open(os.path.join(HERE, f'grp85_add_{V}.json'), 'w'), ensure_ascii=False, indent=1)
