"""Fusion of: A original (market z + E6), B industry panic, C turnover-quintile panic, D simple (market z<=-1.0, weakest 20). Sub-account mixes and one-account priority union. Research only."""
from grp7 import *
R, Aamt = ind_series(l1); Z = zscore(R); trigI = np.isfinite(Z) & (Z <= -1.5)
fmB, fcB = build(trigI, l1)
# turnover quintile labels
uni = cand.uni
a = np.nan_to_num(panel.a, nan=0.0).astype(np.float64); cs = np.cumsum(a, 0); amt60 = np.full((nd, nc), np.nan, np.float32); amt60[60:] = ((cs[60:] - cs[:-60]) / 60).astype(np.float32); del a, cs
lab = np.full((nd, nc), -1, np.int8)
for s0 in range(0, nd, 400):
    b = min(nd, s0 + 400); v = np.where(uni[s0:b] & np.isfinite(amt60[s0:b]), amt60[s0:b], np.nan)
    pct = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
    lab[s0:b] = np.where(np.isfinite(pct), np.minimum(np.nan_to_num(pct * 5).astype(np.int16), 4), -1).astype(np.int8)
cfg1 = DipConfig(leverage=1.0)
fmC, fcC, _ = inputs(panel, cfg1, lab, 'any')
gD = np.isfinite(market.z) & (market.z <= -1.0)
fmD = Market(mret=market.mret, mk20=market.mk20, z=np.where(gD, -9.0, 9.0), count=market.count); fcD = Candidates(uni=uni, e6=uni & np.isfinite(cand.ret20), buyok=cand.buyok, ret20=cand.ret20)
def eqrun(fm, fc, L=1.0):
    cfg = DipConfig(leverage=L); r = simulate(panel, fm, fc, cfg); return r['eq'], r['expo'], cfg, r
def dr(eq):
    r = np.full(nd, np.nan); r[1:] = eq[1:] / eq[:-1] - 1; return r
yr = np.array([int(d[:4]) for d in panel.dates])
def met(r, label, expo=None):
    m = np.isfinite(r); x = r[m]; cum = np.cumprod(1 + x); n = len(x)
    cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    h = []
    for a_, b_ in ((2008, 2016), (2017, 2026)):
        k = (yr >= a_) & (yr <= b_) & m; y = r[k]; h.append(f'{(np.prod(1 + y) ** (245 / len(y)) - 1) * 100:+.1f}%')
    ex = '' if expo is None else f' 仓位{np.nanmean(expo[m]) * 100:3.0f}%'
    print(f'{label:46s} 年化{cagr*100:+5.1f}% 夏普{sh:.2f} 回撤{dd*100:4.0f}% 卡玛{cagr/-dd:.2f}{ex} | 前半{h[0]} 后半{h[1]}', flush=True)
    return cagr, sh, dd
S = {}
for nm, (fm, fc, L) in {'A原策略1x': (market, cand, 1.0), 'A原策略2x': (market, cand, 2.0), 'B行业恐慌1x': (fmB, fcB, 1.0), 'C成交额五分位1x': (fmC, fcC, 1.0), 'D简单z<=-1 1x': (fmD, fcD, 1.0)}.items():
    eq, ex, cfg, _ = eqrun(fm, fc, L); S[nm] = (dr(eq), ex); met(dr(eq), nm, ex)
names = list(S); M = np.array([S[n][0] for n in names]); ok = np.zeros(M.shape[1], bool); ok[1:] = np.all(np.isfinite(M[:, 1:]), axis=0)
print('=== 日收益相关系数', flush=True)
Mm = M[:, ok]; C = np.corrcoef(Mm); print(' ' * 14 + ' '.join(f'{n[:6]:>7s}' for n in names))
for i, n in enumerate(names): print(f'{n[:12]:14s}' + ' '.join(f'{C[i,j]:7.2f}' for j in range(len(names))))
print('=== 分账户混合（固定比例，日收益加权）', flush=True)
def mix(w, label):
    r = sum(wi * S[n][0] for n, wi in w.items()); ex = sum(wi * S[n][1] for n, wi in w.items()); met(np.where(np.isfinite(r), r, np.nan), label, ex)
mix({'A原策略2x': .5, 'B行业恐慌1x': .5}, 'A2x 50% + B1x 50%')
mix({'A原策略2x': .5, 'C成交额五分位1x': .5}, 'A2x 50% + C1x 50%')
mix({'B行业恐慌1x': .5, 'C成交额五分位1x': .5}, 'B1x 50% + C1x 50%')
mix({'A原策略2x': 1/3, 'B行业恐慌1x': 1/3, 'C成交额五分位1x': 1/3}, 'A2x + B1x + C1x 各1/3')
mix({'A原策略1x': 1/3, 'B行业恐慌1x': 1/3, 'C成交额五分位1x': 1/3}, 'A1x + B1x + C1x 各1/3')
mix({'A原策略2x': .4, 'B行业恐慌1x': .4, 'D简单z<=-1 1x': .2}, 'A2x .4 + B1x .4 + D1x .2')
mix({'A原策略2x': 1.0, 'B行业恐慌1x': 1.0}, '各用一份本金: A2x + B1x（总杠杆最高3x）')
print('=== 单账户优先级合并（同一批 20 个名额：E6恐慌股优先 > 行业恐慌股 > 成交额档恐慌股）', flush=True)
mk = np.isfinite(market.z) & (market.z <= -1.5)
poolA = cand.e6 & mk[:, None]
for L in (1.0, 1.5, 2.0):
    for combo, pools in {'A+B': (poolA, fcB.e6), 'A+C': (poolA, fcC.e6), 'A+B+C': (poolA, fcB.e6, fcC.e6)}.items():
        pool = np.zeros_like(poolA)
        for p in pools: pool |= p
        prio = cand.ret20.copy().astype(np.float32); prio[poolA] -= 10.0                         # E6 in market panic first
        if combo != 'A+C':
            only_b = fcB.e6 & ~poolA; prio[only_b] -= 5.0                                         # then industry-panic stocks
        fm = Market(mret=market.mret, mk20=market.mk20, z=np.where(pool.any(1), -9.0, 9.0), count=market.count)
        fc = Candidates(uni=uni, e6=pool, buyok=cand.buyok, ret20=prio)
        eq, ex, cfg, r = eqrun(fm, fc, L); met(dr(eq), f'优先级 {combo} {L:g}x', ex)
