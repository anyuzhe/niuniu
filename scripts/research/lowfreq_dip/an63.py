"""Turn 'buying later is better' into a rule: wait for the market to turn (rebound confirmation) instead of buying on day 1. Research only."""
import os, json
import grp11 as g
from grp11 import *
from quantlab.dipbuy.engine import _exit_index
t0 = int(np.searchsorted(dates, '2008-01-01'))
z = np.where(np.isfinite(market.z), market.z, np.nan); mr = np.nan_to_num(market.mret)
def roll_min(x, n):
    out = np.full(nd, np.nan)
    for t in range(n - 1, nd): out[t] = np.nanmin(x[t - n + 1:t + 1]) if np.isfinite(x[t - n + 1:t + 1]).any() else np.nan
    return out
zmin5 = roll_min(z, 5)
r2 = mr + np.concatenate([[0], mr[:-1]]); r3 = r2 + np.concatenate([[0, 0], mr[:-2]])
CONDS = {
  '大盘当天收涨': mr > 0,
  '恐慌分比昨天好转': np.concatenate([[False], z[1:] > z[:-1]]),
  '恐慌分离开 5 日低点 ≥0.3': (z - zmin5) >= 0.3,
  '恐慌分离开 5 日低点 ≥0.6': (z - zmin5) >= 0.6,
  '大盘近 2 日累计 >0': r2 > 0,
  '大盘近 3 日累计 >+1%': r3 > 0.01,
  '(对照)大盘当天收跌': mr < 0,
  '(对照)恐慌分比昨天更差': np.concatenate([[False], z[1:] < z[:-1]]),
}
mk = np.cumprod(1 + mr)
def net(j, t, H=20):
    e = t + 1
    if e >= nd: return None
    o0 = float(O_[e, j]); raw_e = o0 / float(F_[e, j]); ex = _exit_index(C_, j, t + H, nd)
    if not ex: return None
    xi, px = ex; raw_x = px / float(F_[xi, j])
    return (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee[xi], xi, e
out = {}
print('=== 单笔：每个信号日买最弱 20 只、次日开盘买持有 20 天；条件成立 vs 不成立（单笔均值 / 超额大盘，bp；N=信号日数）===', flush=True)
for s in 'ACB':
    gate, e6, r20 = g.SL[s]; days = []
    for t in range(t0, nd - 22):
        if not gate[t]: continue
        pool = np.nonzero(e6[t] & buyok[t])[0]
        if not len(pool): continue
        pool = pool[np.argsort(r20[t, pool], kind='stable')][:20]; rs = [net(j, t) for j in pool]; rs = [r for r in rs if r]
        if rs: days.append((t, np.mean([r[0] for r in rs]), mk[rs[0][1]] / mk[rs[0][2] - 1] - 1))
    D = np.array(days); ts = D[:, 0].astype(int)
    print(f'-- {s} 全部 {len(D)} 日  单笔 {D[:,1].mean()*1e4:+.0f}bp 超额 {(D[:,1]-D[:,2]).mean()*1e4:+.0f}bp', flush=True)
    for nm, c in CONDS.items():
        a = c[ts]; 
        if a.sum() and (~a).sum(): print(f'   {nm:24s} 成立 {a.sum():4d} 日: {D[a,1].mean()*1e4:+5.0f}/{(D[a,1]-D[a,2]).mean()*1e4:+5.0f}   不成立 {(~a).sum():4d} 日: {D[~a,1].mean()*1e4:+5.0f}/{(D[~a,1]-D[~a,2]).mean()*1e4:+5.0f}', flush=True)
print('\n=== D 账户：把条件加到闸门上（只在条件成立的日子买入），权重/名额不变 ===', flush=True)
W = {'A': .08, 'C': .08, 'B': .025}; orig = dict(g.SL)
def run(label, apply):
    g.SL = {s: ((orig[s][0] & CONDS[label.split('|')[0]]) if s in apply else orig[s][0], orig[s][1], orig[s][2]) for s in 'ACB'} if label != '基线' else orig
    eq, ex, ntr, pnl, wsum, minr = g.fused(order='ACB', w=W, G=1.0, caps={}, cash_yield=0.02); r = dr(eq); met(r, label.replace('|', ' 加在 '), ex)
    print(f'{"":46s} ' + ' '.join(f"{s}:{ntr[s]}笔均{pnl[s]/max(ntr[s],1)*1e4:+.0f}bp" for s in ntr), flush=True)
run('基线', 'ACB')
for nm in CONDS:
    run(nm + '|ACB', 'ACB'); run(nm + '|A', 'A')
