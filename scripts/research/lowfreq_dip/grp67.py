"""grp67: D / D1 / D2 每段较长的水下期间，等权大盘指数同期怎么走。读 grp66_*.json 和 grp63_mkt.npz。"""
import json, os
import numpy as np
for loc in ('grp63_mkt.npz', os.path.expanduser('~/research/lowfreq/grp63_mkt.npz')):
    if os.path.exists(loc): M = np.load(loc); break
dates = [str(d) for d in M['dates']]; pos = {d: i for i, d in enumerate(dates)}
idx = np.cumprod(1 + np.where(np.isfinite(M['mret']), M['mret'], 0.0))
def ix(d):
    return pos[d] if d in pos else int(np.searchsorted(dates, d))
rows = []
for V in ('D', 'D1', 'D2'):
    r = json.load(open(f'grp66_{V}.json'))
    for e in r['top_by_days']:
        if e['days'] < 150: continue
        a, b = ix(e['peak']), ix(e['trough'])
        c = ix(e['recover']) if e['recover'] else len(idx) - 1
        seg = idx[a:c + 1]
        pk = np.maximum.accumulate(seg); dd = (seg / pk - 1).min()
        look = idx[max(0, a - 120):a + 1]
        rows.append(dict(V=V, peak=e['peak'], trough=e['trough'], rec=e['recover'], days=e['days'], depth=e['depth'],
                         idx_to_trough=float(idx[b] / idx[a] - 1), idx_to_rec=float(idx[c] / idx[a] - 1),
                         idx_maxdd_in=float(dd), idx_gap_at_peak=float(idx[a] / look.max() - 1),
                         strat_to_rec=0.0))
json.dump(rows, open('grp67.json', 'w'), ensure_ascii=False, indent=1)
print(f'{"V":3} {"策略高点":10} {"低点":10} {"新高":10} {"交易日":>5} {"策略最深":>7} | {"指数:高点→低点":>13} {"高点→新高日":>11} {"区间内最大回撤":>12} {"高点时离120日高":>13}')
for x in rows:
    print(f'{x["V"]:3} {x["peak"]:10} {x["trough"]:10} {str(x["rec"]):10} {x["days"]:5d} {x["depth"]*100:+7.1f}% | {x["idx_to_trough"]*100:+12.1f}% {x["idx_to_rec"]*100:+10.1f}% {x["idx_maxdd_in"]*100:+11.1f}% {x["idx_gap_at_peak"]*100:+12.1f}%')
# 全期：指数自己的最长水下
pk = np.maximum.accumulate(idx); ddi = idx / pk - 1
print('指数全期最大回撤', round(ddi.min() * 100, 1), '% 在', dates[int(np.argmin(ddi))], ' 当前离前高', round(ddi[-1] * 100, 1), '%')
