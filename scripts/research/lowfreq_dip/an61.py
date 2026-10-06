import numpy as np
import grp52 as h
from grp52 import *
def episode_day(gate, gap=5):
    k = np.zeros(nd, int); lo = -10 ** 9; st = None
    for t in range(nd):
        if gate[t]:
            if t - lo > gap: st = t
            k[t] = t - st + 1; lo = t
    return k
bl = []; eq, ex, _ = fused2(buylog=bl)
bins = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, 999)]
print('原版 D：每个买入发生在“触发后第几天”（按买入笔数 / 按占权益比例）')
for s in 'ACB':
    ep = episode_day(SL[s][0]); b = [(ep[t], w) for t, ss, w in bl if ss == s]
    n = len(b); wsum = sum(w for _, w in b)
    out = []
    for lo, hi in bins:
        k = [w for d, w in b if lo <= d <= hi]; out.append(f'第{lo}{"" if lo==hi else "-"+(str(hi) if hi<999 else "")}{"+" if hi==999 else ""}天 {len(k)/n*100:3.0f}%/{sum(k)/wsum*100:3.0f}%')
    print(f'{s}: 共 {n} 笔  ' + '  '.join(out))
# how many distinct days per episode have any buy, and share of an episode's buys made on its first day
for s in 'ACB':
    ep = episode_day(SL[s][0]); bydays = {}
    for t, ss, w in bl:
        if ss == s: bydays.setdefault(t - ep[t] + 1, []).append((ep[t], w))
    first = [sum(w for d, w in v if d == 1) / sum(w for d, w in v) for v in bydays.values()]
    ndays = [len({d for d, w in v}) for v in bydays.values()]
    print(f'{s}: {len(bydays)} 段恐慌有买入；每段首日买的资金占该段全部买入资金的均值 {np.mean(first)*100:.0f}%；每段有买入的不同“第几天”数均值 {np.mean(ndays):.1f}')
