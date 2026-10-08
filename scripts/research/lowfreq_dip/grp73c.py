import os, sys, json, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
dates = [str(d) for d in panel.dates]; di = {d: i for i, d in enumerate(dates)}
inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
gA, gC = inp.gates['A'], inp.gates['C']; mz = inp.market.z
rows = json.load(open('grp73_rows.json'))
for r in rows:
    t = di[r['signal']]; r['A'] = bool(gA[t]); r['C'] = bool(gC[t]); r['mz'] = float(mz[t]) if np.isfinite(mz[t]) else np.nan
def s(R, lab):
    if not R: return
    print(f"{lab:14s} n={len(R):4d} 账户{np.mean([r['ret'] for r in R])*100:+5.1f}% 行业20日{np.mean([r['ind20'] for r in R])*100:+5.1f}% A闸开{np.mean([r['A'] for r in R])*100:3.0f}% C闸开{np.mean([r['C'] for r in R])*100:3.0f}% 大盘z中位{np.nanmedian([r['mz'] for r in R]):+.2f}")
for g in ('差6', '房地产', '其余', '好8'):
    R = [r for r in rows if r['grp'] == g]; s(R, g); s([r for r in R if r['A']], g + ' A开'); s([r for r in R if not r['A']], g + ' A关')
print('全部B笔 A开/关'); s([r for r in rows if r['A']], '全部A开'); s([r for r in rows if not r['A']], '全部A关')
import collections
print('2018年占比: 差6+房地产', np.mean([r['year']==2018 for r in rows if r['grp'] in ('差6','房地产')]), '好8', np.mean([r['year']==2018 for r in rows if r['grp']=='好8']))
