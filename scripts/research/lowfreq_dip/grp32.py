"""D internals not yet tested on the fused account: gate thresholds for B/C, ranking key, slots N, leverage, deep-bear filter. Research only."""
import sys, grp11 as g
from dataclasses import replace
from grp11 import *
W = {'A': .08, 'C': .08, 'B': .025}
base_SL = dict(g.SL)
def run(label, **kw):
    kw.setdefault('order', 'ACB'); kw.setdefault('w', W); kw.setdefault('G', 1.0); kw.setdefault('caps', {}); kw.setdefault('cash_yield', 0.02)
    return show(label, **kw)
mode = sys.argv[1]
if mode == 'thr':
    R1, _ = ind_series(l1)
    Z1 = zscore(R1)
    for thB, thC in ((-1.5, -1.5), (-1.25, -1.5), (-1.0, -1.5), (-1.5, -1.25), (-1.5, -1.0), (-1.25, -1.25)):
        g.SL = dict(base_SL)
        if thB != -1.5:
            fm, fc = build(np.isfinite(Z1) & (Z1 <= thB), l1); g.SL['B'] = ((fm.z <= -1.5), fc.e6, fc.ret20)
        if thC != -1.5:
            fm, fc, _ = inputs(panel, replace(cfg1, z_threshold=thC), lab, 'any'); g.SL['C'] = ((fm.z <= thC), fc.e6, fc.ret20)
        run(f'D 闸门阈值 B {thB} C {thC}')
elif mode == 'rank':
    c = panel.c.astype(np.float32); nd_, nc_ = c.shape
    def ret(k):
        r = np.full((nd_, nc_), np.nan, np.float32); r[k:] = c[k:] / c[:-k] - 1; return r
    r1 = np.full((nd_, nc_), np.nan, np.float32); r1[1:] = c[1:] / c[:-1] - 1
    vol60 = pd.DataFrame(r1).rolling(60, min_periods=40).std().to_numpy().astype(np.float32)
    hi60 = pd.DataFrame(c).rolling(60, min_periods=40).max().to_numpy().astype(np.float32)
    keys = {'20 日涨跌（D）': cand.ret20, '5 日涨跌': ret(5), '10 日涨跌': ret(10), '60 日涨跌': ret(60), '20 日涨跌 / 60 日波动（风险调整）': cand.ret20 / (vol60 * np.sqrt(20)), '距 60 日高点跌幅': c / hi60 - 1, '60 日波动最小优先（取负）': -vol60}
    for name, key in keys.items():
        g.SL = {s: (v[0], v[1], key) for s, v in base_SL.items()}
        run(f'D 排序键：{name}')
elif mode == 'slots':
    for N in (10, 15, 20, 30, 40):
        g.SL = dict(base_SL); run(f'D 每个子策略最多 {N} 个名额', N=N)
elif mode == 'lev':
    for m_, G in ((1.0, 1.0), (1.5, 1.5), (2.0, 2.0), (1.5, 1.0), (2.0, 1.5)):
        g.SL = dict(base_SL); run(f'D 权重×{m_} 总仓位上限 {G}x', w={s: v * m_ for s, v in W.items()}, G=G)
elif mode == 'bear':
    idx = np.cumprod(1 + np.nan_to_num(market.mret)); hi = pd.Series(idx).rolling(250, min_periods=60).max().to_numpy(); dd = idx / hi - 1
    for th in (None, -0.2, -0.3, -0.4):
        g.SL = {s: ((v[0] & (dd > th)) if th is not None else v[0], v[1], v[2]) for s, v in base_SL.items()}
        run(f'D 指数距 250 日高点跌幅超过 {abs(th)*100:.0f}% 时不开仓' if th is not None else 'D 基线')
