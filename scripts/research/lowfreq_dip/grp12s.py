"""B-only layer check: yearly contribution and weight sensitivity. Research only."""
import sys
import numpy as np
import grp12 as h
from grp12 import *
SL = h.SL
SL['P'] = (gC & ~gB & ~gA, fcC.e6, fcC.ret20); SL['Q'] = (gC & gB & ~gA, fcC.e6, fcC.ret20); SL['R'] = (gC & gA, fcC.e6, fcC.ret20); SL['S'] = (gB & ~gC & ~gA, fcB.e6, fcB.ret20)
W0 = {'P': .03, 'Q': .05, 'R': .08}
def series(ws):
    if ws == 0: return dr(fused(order='RQP', w=W0, G=1.0, cash_yield=0.02)[0])
    return dr(fused(order='RQPS', w={**W0, 'S': ws}, G=1.0, cash_yield=0.02)[0])
st = sys.argv[1]
if st == 'y':
    r0 = series(0); r1 = series(.025); np.save('s_r0.npy', r0); np.save('s_r1.npy', r1)
    print('年份   不加    加S    差    | 当年S层触发天数')
    dS = (gB & ~gC & ~gA)
    for y in range(2008, 2027):
        k = (yr == y) & np.isfinite(r0) & np.isfinite(r1)
        if k.sum() < 20: continue
        a = np.prod(1 + r0[k]) - 1; b = np.prod(1 + r1[k]) - 1
        print(f'{y}  {a*100:+6.1f}% {b*100:+6.1f}% {100*(b-a):+5.1f} | {int((dS & (yr == y)).sum())}', flush=True)
    d = r1 - r0; k = np.isfinite(d)
    print('S 层日度增量 平均', d[k].mean() * 245 * 100, '% /年; 正的年份数', sum((np.prod(1 + r1[(yr == y) & k]) > np.prod(1 + r0[(yr == y) & k])) for y in range(2008, 2027) if ((yr == y) & k).sum() > 20))
    # leave-best-years-out
    ys = list(range(2008, 2027)); diffs = {y: np.prod(1 + r1[(yr == y) & k]) - np.prod(1 + r0[(yr == y) & k]) for y in ys if ((yr == y) & k).sum() > 20}
    top = sorted(diffs, key=diffs.get, reverse=True)[:3]; print('增量最大的三年', top, '去掉这三年后 S 层年均增量', np.mean([v for y, v in diffs.items() if y not in top]) * 100, '个点')
if st == 'w':
    print('=== S 层权重敏感性（3/5/8% 的成交额分层固定）', flush=True)
    for ws in (0, .01, .025, .04, .05):
        r = series(ws); met(r, f'S 层权重 {ws*100:g}%')
