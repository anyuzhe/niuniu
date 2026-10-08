"""grp71: B 层表现差的行业有什么共性。读 grp69_D.json / grp69_D2.json（B 层成交），对每笔算触发时的特征；
再做“行业整体”视角：全部触发日里该行业所有成员的 20 日前向收益（不受名额限制）。"""
import os, sys, json, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
c, o, a = panel.c.astype(np.float64), panel.o.astype(np.float64), panel.a.astype(np.float64)
nd, nc = c.shape; dates = [str(d) for d in panel.dates]; di = {d: i for i, d in enumerate(dates)}
labels = np.asarray(cls.labels); names = cls.names; st = inp.ind_state; thr = -1.5
gap120 = fusion.near_high_gap(inp.market, 120); gap250 = fusion.near_high_gap(inp.market, 250)
code_j = {str(x): j for j, x in enumerate(panel.codes)}
BAD = ['国防军工', '环保', '煤炭', '基础化工', '家用电器', '美容护理']; RE = ['房地产']
GOOD = ['计算机', '医药生物', '有色金属', '公用事业', '食品饮料', '农林牧渔', '电子', '银行']
def grp_of(n): return '差(6)' if n in BAD else '房地产' if n in RE else '好(8)' if n in GOOD else '其余'
def feat(t, j, g, ret):
    f = {}
    f['r20'] = c[t, j] / c[t - 20, j] - 1; f['r60'] = c[t, j] / c[t - 60, j] - 1; f['r120'] = c[t, j] / c[t - 120, j] - 1
    f['r250'] = c[t, j] / c[t - 250, j] - 1 if t >= 250 else np.nan
    f['dd250'] = c[t, j] / np.nanmax(c[max(0, t - 249):t + 1, j]) - 1
    r = c[t - 59:t + 1, j][1:] / c[t - 59:t + 1, j][:-1] - 1; f['vol60'] = np.nanstd(r)
    f['ladv'] = np.log10(np.nanmean(a[t - 19:t + 1, j]) + 1); f['price'] = panel.c[t, j] / panel.f[t, j]
    ent = o[t + 1, j]
    if t + 20 < nd and np.isfinite(ent) and ent > 0:
        path = c[t + 1:t + 21, j] / ent - 1; f['mae'] = np.nanmin(path); f['r5'] = path[4]; f['r10'] = path[9]
    f['z_ind'] = st.z[t, g]; f['r20_ind'] = st.ret20[t, g]; f['n_ind'] = st.n[t, g]
    f['chronic'] = int((st.z[t - 19:t + 1, g] <= thr).sum())
    cols = np.nonzero(labels == g)[0]
    f['r120_ind'] = np.nanmean(c[t, cols] / c[t - 120, cols] - 1); f['r250_ind'] = np.nanmean(c[t, cols] / c[t - 250, cols] - 1) if t >= 250 else np.nan
    f['mkt_gap120'] = gap120[t]; f['mkt_gap250'] = gap250[t]; f['mkt_z'] = inp.market.z[t]
    f['ret'] = ret
    return f
out = {}
for V in ('D', 'D2'):
    T = json.load(open(f'grp69_{V}.json'))['trades']; rows = []
    for tr in T:
        t = di[tr['signal']]; j = code_j[tr['code']]
        if t < 130 or t + 21 >= nd: continue
        g = int(labels[j]); f = feat(t, j, g, tr['ret']); f['ind'] = names[g]; f['grp'] = grp_of(names[g]); f['signal'] = tr['signal']; rows.append(f)
    out[V] = rows; print(V, 'trades with features', len(rows), flush=True)
json.dump(out, open('grp71_trades.json', 'w'), ensure_ascii=False, default=float)

# ---- 行业整体视角：全部触发日里该行业所有成员的 20 日前向收益（不受名额限制）
ngrp = len(names); recs = []
trig = np.argwhere(np.isfinite(st.z) & (st.z <= thr))
for t, g in trig:
    if t < 130 or t + 20 >= nd: continue
    cols = np.nonzero(labels == g)[0]
    ent = o[t + 1, cols]; ex = c[t + 20, cols]; ok = np.isfinite(ent) & (ent > 0) & np.isfinite(ex) & inp.cand.uni[t, cols]
    if ok.sum() < 5: continue
    fwd = ex[ok] / ent[ok] - 1
    recs.append(dict(t=int(t), g=int(g), ind=names[g], date=dates[t], fwd=float(fwd.mean()), n=int(ok.sum()),
                     r120_ind=float(np.nanmean(c[t, cols] / c[t - 120, cols] - 1)), z=float(st.z[t, g]), gap120=float(gap120[t])))
json.dump(recs, open('grp71_indlevel.json', 'w'), ensure_ascii=False)
print('industry-level trigger days', len(recs))
