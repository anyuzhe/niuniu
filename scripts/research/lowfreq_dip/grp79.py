"""grp79: 市场性恐慌日 B 层买不到（A、C 层先占满仓位）——让 B 层也能买会怎样？
变体：优先级 A>C>B(基线) / B>A>C / A>B>C / 降低 A、C 单只权重给 B 留仓位；同时统计市场性恐慌日的仓位占用。"""
import os, sys, json, pickle, time
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
V = sys.argv[1]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cfg0 = fusion.config_for(V)
inp = fusion.with_near_high_filter(replace(raw_inp), cfg0)
nd, nc = panel.shape; dates = [str(d) for d in panel.dates]
i18 = int(np.searchsorted(dates, '2018-01-01'))
z = inp.ind_state.z; breadth = np.nansum(z <= -1.5, axis=1)
ORD0 = tuple(fusion.ORDER)
def run(order, **kw):
    fusion.ORDER = order
    cfg = replace(cfg0, **kw)
    raw = fusion.simulate_fused(panel, inp, cfg)
    eq = raw['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; r = e[1:] / e[:-1] - 1
    dd = float((e / np.maximum.accumulate(e) - 1).min())
    pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]; npre = int((idx < i18).sum()); npost = int((idx >= i18).sum())
    bt = [t for t in raw['trades'] if t.get('sleeve') == 'B']; bb = [dates.index(t['signal']) if 'signal' in t else None for t in bt]
    big = [t['ret'] for t in bt if t.get('signal') and breadth[dates.index(t['signal'])] >= 16] if bt and 'signal' in bt[0] else []
    expo = raw['expo']; m = (breadth >= 16) & ok
    return dict(order=''.join(order), kw=kw, cagr=float(cagr), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=dd, cagr_pre=float(pre ** (245 / npre) - 1),
                cagr_post=float(post ** (245 / npost) - 1), nB=len(bt), meanB=float(np.mean([t['ret'] for t in bt])) if bt else None,
                nB_big=len(big), meanB_big=float(np.mean(big)) if big else None, expo_big=float(expo[m].mean()), expo_all=float(expo[ok].mean()))
print('ORDER 默认', ORD0)
S = [('基线 A>C>B', ORD0, {}), ('B>A>C', ('B', 'A', 'C'), {}), ('A>B>C', ('A', 'B', 'C'), {}),
     ('A,C 权重 5%（B 2.5%）', ORD0, dict(weight_a=0.05, weight_c=0.05)), ('A,C 权重 4%', ORD0, dict(weight_a=0.04, weight_c=0.04)),
     ('B 权重 4%（A,C 8%）', ORD0, dict(weight_b=0.04)), ('B>A>C 且 B 2.5%→5%', ('B', 'A', 'C'), dict(weight_b=0.05))]
out = {}
for lab, order, kw in S:
    o = run(order, **kw); out[lab] = o
    print(V, f"{lab:22s} cagr {o['cagr']*100:.1f} pre {o['cagr_pre']*100:.1f} post {o['cagr_post']*100:.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:.1f} nB {o['nB']} meanB {(o['meanB'] or 0)*100:.1f} | 广度>=16买入 {o['nB_big']}笔 均值 {(o['meanB_big'] or 0)*100:.1f}% | 仓位(全期/广度>=16) {o['expo_all']*100:.0f}%/{o['expo_big']*100:.0f}%", flush=True)
fusion.ORDER = ORD0
json.dump(out, open(f'grp79_{V}.json', 'w'), ensure_ascii=False)
