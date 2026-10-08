"""grp82: B 层只在 A（大盘恐慌）触发（或最近 k 天内触发过）时才买，再叠加行业触发。"""
import os, sys, json, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion
from quantlab.dipbuy.panel import Panel
V = sys.argv[1]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cfg0 = fusion.config_for(V); inp0 = fusion.with_near_high_filter(replace(raw_inp), cfg0)
nd, nc = panel.shape; dates = [str(d) for d in panel.dates]; i18 = int(np.searchsorted(dates, '2018-01-01'))
gA = inp0.gates['A'].astype(bool); gC = inp0.gates['C'].astype(bool); gB = inp0.gates['B'].astype(bool)
ORD0 = tuple(fusion.ORDER)
def within(g, k):
    out = g.copy()
    for s in range(1, k + 1): out[s:] |= g[:-s]
    return out
def run(order, bmask_t):
    fusion.ORDER = order
    pools = dict(inp0.pools); pools['B'] = inp0.pools['B'] & bmask_t[:, None]
    raw = fusion.simulate_fused(panel, replace(inp0, pools=pools), cfg0)
    eq = raw['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]
    cagr = (e[-1] / e[0]) ** (245 / len(e)) - 1; r = e[1:] / e[:-1] - 1; dd = float((e / np.maximum.accumulate(e) - 1).min())
    pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]; npre = int((idx < i18).sum()); npost = int((idx >= i18).sum())
    bt = [t for t in raw['trades'] if t.get('sleeve') == 'B']
    return dict(cagr=float(cagr), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=dd, cagr_pre=float(pre ** (245 / npre) - 1), cagr_post=float(post ** (245 / npost) - 1),
                nB=len(bt), meanB=float(np.mean([t['ret'] for t in bt])) if bt else None, expo=float(np.nanmean(raw['expo'][ok])), final=float(e[-1] / e[0]))
print('A 闸门开的天数占比', gA.mean().round(3), 'C', gC.mean().round(3), 'B', gB.mean().round(3), '| A 闸门日里 C 也开', (gA & gC).sum() / gA.sum(), 'B 也开', (gA & gB).sum() / gA.sum())
out = {}
ALL = np.ones(nd, bool)
for lab, order, m in (('基线 A>C>B，B 不限', ORD0, ALL), ('A>C>B，B 只在 A 当天触发时', ORD0, gA), ('A>C>B，B 在 A 触发后 5 天内', ORD0, within(gA, 5)),
                      ('A>C>B，B 在 A 触发后 10 天内', ORD0, within(gA, 10)), ('A>C>B，B 在 A 触发后 20 天内', ORD0, within(gA, 20)),
                      ('B>A>C，B 只在 A 当天触发时', ('B', 'A', 'C'), gA), ('C>A>B，B 只在 A 当天触发时', ('C', 'A', 'B'), gA),
                      ('C>A>B，B 在 A 触发后 10 天内', ('C', 'A', 'B'), within(gA, 10)), ('去掉 B（对照）', ORD0, np.zeros(nd, bool))):
    o = run(order, m); out[lab] = o
    print(V, f"{lab:28s} cagr {o['cagr']*100:5.1f} pre {o['cagr_pre']*100:5.1f} post {o['cagr_post']*100:5.1f} sh {o['sharpe']:.2f} mdd {o['mdd']*100:6.1f} 终值{o['final']:5.1f}x 仓位{o['expo']*100:3.0f}% B成交{o['nB']} B均值{(o['meanB'] or 0)*100:+.1f}%", flush=True)
fusion.ORDER = ORD0
json.dump(out, open(f'grp82_{V}.json', 'w'), ensure_ascii=False)
