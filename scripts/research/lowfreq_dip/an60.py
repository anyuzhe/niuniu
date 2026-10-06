"""Does it matter WHEN in a panic episode we buy? Per-trade returns by day-in-episode, and D with entries restricted by day. Research only."""
import grp11 as g
from grp11 import *
from quantlab.dipbuy.engine import _exit_index
t0 = int(np.searchsorted(dates, '2008-01-01'))
def episode_day(gate, gap=5):
    k = np.zeros(nd, int); lo = -10 ** 9; st = None
    for t in range(nd):
        if gate[t]:
            if t - lo > gap: st = t
            k[t] = t - st + 1; lo = t
    return k
EP = {s: episode_day(g.SL[s][0]) for s in 'ACB'}
mk = np.nan_to_num(market.mret); cm = np.cumprod(1 + mk)
def net(j, t, H=20):
    e = t + 1
    if e >= nd: return None
    o0 = float(O_[e, j]); raw_e = o0 / float(F_[e, j]); ex = _exit_index(C_, j, t + H, nd)
    if not ex: return None
    xi, px = ex; raw_x = px / float(F_[xi, j])
    return (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee[xi], xi, e
bins = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, 999)]
print('=== 每个信号日买最弱 20 只、次日开盘买持有 20 天，单笔平均净收益(bp) 与 同期全市场等权涨跌(bp)，按“触发后第几天”分 ===')
for s in 'ACB':
    gate, e6, r20 = g.SL[s]; rows = {b: [] for b in bins}
    for t in range(t0, nd - 22):
        if not gate[t]: continue
        pool = np.nonzero(e6[t] & buyok[t])[0]
        if not len(pool): continue
        pool = pool[np.argsort(r20[t, pool], kind='stable')][:20]
        rs = [net(j, t) for j in pool]; rs = [r for r in rs if r]
        if not rs: continue
        e = rs[0][2]; x = rs[0][1]
        for b in bins:
            if b[0] <= EP[s][t] <= b[1]:
                rows[b].append((np.mean([r[0] for r in rs]), cm[x] / cm[e - 1] - 1)); break
    print(f'-- {s}')
    for b in bins:
        r = np.array(rows[b])
        if len(r): print(f'   第 {b[0]}{"" if b[0]==b[1] else "-" + (str(b[1]) if b[1] < 999 else "")}天{"+" if b[1]==999 else ""}: {len(r):4d} 个信号日  单笔均值 {r[:,0].mean()*1e4:+6.0f}bp  同期大盘 {r[:,1].mean()*1e4:+6.0f}bp  超额 {(r[:,0]-r[:,1]).mean()*1e4:+6.0f}bp  胜率(超额>0) {np.mean(r[:,0]>r[:,1])*100:3.0f}%', flush=True)
print('\n=== D（共用账户、权重不变）只在触发后的某几天里允许买入 ===')
W = {'A': .08, 'C': .08, 'B': .025}; orig = dict(g.SL)
def run(label, lo, hi):
    g.SL = {s: (orig[s][0] & (EP[s] >= lo) & (EP[s] <= hi), orig[s][1], orig[s][2]) for s in 'ACB'}
    eq, ex, ntr, pnl, wsum, minr = g.fused(order='ACB', w=W, G=1.0, caps={}, cash_yield=0.02); r = dr(eq); met(r, label, ex)
    print(f'{"":46s} ' + ' '.join(f"{s}:{ntr[s]}笔均{pnl[s]/max(ntr[s],1)*1e4:+.0f}bp" for s in ntr), flush=True)
for lab, lo, hi in (('全部天数(基线)', 1, 999), ('只在触发第 1 天买', 1, 1), ('触发后前 3 天', 1, 3), ('触发后前 5 天', 1, 5), ('第 2 天起', 2, 999), ('第 3 天起', 3, 999), ('第 6 天起', 6, 999)):
    run(lab, lo, hi)
