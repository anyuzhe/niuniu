"""Cascade / hierarchical fusion: day-level regime decides which pool is traded. Levels: market z (E6) > graded market > industry z > turnover-quintile z / float-cap-quintile z.
One account, 1x, per-level 20 slots, 5% each (unless noted), 2% cash yield. Research only."""
import sys
import grp11 as g
from grp11 import *
labcap = np.load('capq.npy'); fmM, fcM, _ = inputs(panel, cfg1, labcap, 'any')
gateM = fmM.z <= -1.5
gA, gB, gC = gateA, gateB, gateC
gGr = np.isfinite(market.z) & (market.z > -1.5) & (market.z <= -1.0)          # graded: moderately weak market
SL = g.SL
SL['G'] = (gGr, fcD.e6, fcD.ret20)                                           # weakest 20 without E6
SL['M'] = (gateM, fcM.e6, fcM.ret20)
def excl(order):
    """make sleeves exclusive in priority order (a later level only on days no earlier level fired)"""
    seen = np.zeros(nd, bool); res = {}
    for k in order:
        gate, e6, r20 = g.SL0[k]; res[k] = (gate & ~seen, e6, r20); seen |= gate
    return res
g.SL0 = dict(SL)
def run(label, order, exclusive=True, **kw):
    if exclusive:
        SL.update(excl(order))
    else:
        SL.update({k: g.SL0[k] for k in order})
    return show(label, order=order, cash_yield=0.02, **kw)
if __name__ == '__main__':
    st = sys.argv[1]
    if st == 'a':
        print('=== 级联（当天只用最高优先级触发的那一层；其下层只在上层没触发的日子才买）', flush=True)
        run('A>B 级联', 'AB'); run('A>C 级联', 'AC'); run('A>B>C 成交额 级联', 'ABC'); run('A>B>M 流通市值 级联', 'ABM')
    if st == 'b':
        run('A>C>B 级联', 'ACB'); run('A>M>B 级联', 'AMB'); run('A>G>B>C 级联（G=大盘 z∈(−1.5,−1.0] 买最弱20）', 'AGBC')
        run('C>B>A 反向对照', 'CBA')
    if st == 'c':
        print('=== 按层级定仓位（信号越强，每只越重；总仓位上限 1x）', flush=True)
        run('A>B>C，A 每只10% B 5% C 3%', 'ABC', w={'A': .10, 'B': .05, 'C': .03})
        run('A>G>B>C，A 10% G 5% B 4% C 3%', 'AGBC', w={'A': .10, 'G': .05, 'B': .04, 'C': .03})
        run('A>B>C，各 5%，B≤50% C≤50%', 'ABC', caps={'B': .5, 'C': .5})
    if st == 'd':
        print('=== 共振：A/B/C 三层里同时触发 k 层才买（池=触发层候选并集，按20日跌幅最弱）', flush=True)
        k = gA.astype(int) + gB.astype(int) + gC.astype(int)
        poolU = (gA[:, None] & cand.e6) | (gB[:, None] & fcB.e6) | (gC[:, None] & fcC.e6)
        for kk in (1, 2, 3):
            SL['U'] = (k >= kk, poolU, cand.ret20); print(f'k>={kk}: 触发 {int((k >= kk).sum())} 天', flush=True)
            show(f'共振 k>={kk}', order='U', w=0.05, G=1.0, cash_yield=0.02)
        SL['U'] = (k >= 1, poolU, cand.ret20)
        print('--- 共振加权：仓位 = 每只 2.5% x k（k=1,2,3 分别用 Z/Y/X 三个子账户，总仓位上限 1x）', flush=True)
        SL['Z'] = (k == 1, poolU, cand.ret20); SL['Y'] = (k == 2, poolU, cand.ret20); SL['X'] = (k == 3, poolU, cand.ret20)
        show('k 加权 2.5%/5%/7.5%', order='XYZ', w={'X': .075, 'Y': .05, 'Z': .025}, G=1.0, cash_yield=0.02)
    if st == 'e':
        print('=== 去掉 B（行业层触发太广，拉低平均质量），层级按“每笔质量”排', flush=True)
        run('A>C>G', 'ACG'); run('A>C>M>G', 'ACMG'); run('A>M>C', 'AMC'); run('C>A（成交额层优先）', 'CA'); run('A>G', 'AG')
    if st == 'f':
        print('=== 共振加权，放大每只仓位提高利用率（总仓位仍 ≤1x，无杠杆）', flush=True)
        k = gA.astype(int) + gB.astype(int) + gC.astype(int)
        poolU = (gA[:, None] & cand.e6) | (gB[:, None] & fcB.e6) | (gC[:, None] & fcC.e6)
        SL['Z'] = (k == 1, poolU, cand.ret20); SL['Y'] = (k == 2, poolU, cand.ret20); SL['X'] = (k == 3, poolU, cand.ret20)
        for m in (1.5, 2.0):
            show(f'k 加权 x{m:g}（{2.5*m:.2f}%/{5*m:g}%/{7.5*m:.2f}%）', order='XYZ', w={'X': .075 * m, 'Y': .05 * m, 'Z': .025 * m}, G=1.0, cash_yield=0.02)
        show('k 加权 x2，Z 层(k=1)砍掉', order='XY', w={'X': .15, 'Y': .10}, G=1.0, cash_yield=0.02)
