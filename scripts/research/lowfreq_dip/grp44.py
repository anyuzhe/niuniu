"""Sleeve E for D's idle capital: calm-market stock-level dips in strong stocks (sharp 5d drop / deep pullback, uptrend filter). Added at lowest priority, small weight, shared 1x account. Research only."""
import sys, gc, grp11 as g
from grp11 import *
c = panel.c.astype(np.float32); nd_, nc_ = c.shape
roll = lambda a, L: pd.DataFrame(a).rolling(L, min_periods=L).mean().to_numpy().astype(np.float32)
ma20, ma60 = roll(c, 20), roll(c, 60)
hi20 = pd.DataFrame(c).rolling(20, min_periods=20).max().to_numpy().astype(np.float32)
r5 = np.full((nd_, nc_), np.nan, np.float32); r5[5:] = c[5:] / c[:-5] - 1
dist = c / hi20 - 1
trend = (ma20 > ma60) & (c > ma60)
uni = cand.uni
poolE = {'强势股急跌（5 日跌>8%，MA20>MA60 且在 MA60 上）': (uni & trend & (r5 < -0.08) & (r5 > -0.20), r5),
         '深回踩（距 20 日高 −10%~−20%，同趋势条件）': (uni & trend & (dist <= -0.10) & (dist >= -0.20), dist),
         '强势股急跌，且不限趋势（对照）': (uni & (r5 < -0.08) & (r5 > -0.20), r5)}
base_SL = dict(g.SL)
allday = np.ones(nd_, bool)
W0 = {'A': .08, 'C': .08, 'B': .025}
g.SL = dict(base_SL)
show('D 基线', order='ACB', w=W0, G=1.0, caps={}, cash_yield=0.02)
for name, (pool, key) in poolE.items():
    g.SL = dict(base_SL); g.SL['E'] = (allday, pool & np.isfinite(key), key.astype(np.float32))
    for wE in (0.01, 0.025, 0.04):
        w = dict(W0); w['E'] = wE
        show(f'D + E[{name}] 每只 {wE*100:g}%', order='ACBE', w=w, G=1.0, caps={}, cash_yield=0.02)
    gc.collect()
