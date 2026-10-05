"""Relative-laggard as a ranking tilt inside the dip strategies (A: market z + E6, C: turnover-quintile panic). Research only."""
from grp11 import *
s_ = pd.DataFrame(np.log1p(np.nan_to_num(R))); r20i = (np.exp(s_.rolling(20, min_periods=20).sum()) - 1).to_numpy(); r20i[~np.isfinite(R)] = np.nan
mm = np.nonzero(l1 >= 0)[0]; ind20 = np.full((nd, nc), np.nan, np.float32); ind20[:, mm] = r20i[:, l1[mm]]
gap20 = ind20 - cand.ret20
def rk(x):
    return pd.DataFrame(np.where(np.isfinite(x), x, np.nan)).rank(axis=1, pct=True).to_numpy().astype(np.float32)
r_ret = rk(cand.ret20); r_gap = rk(-gap20)                   # low = weakest / most lagging vs industry
keys = {'按20日跌幅(原)': cand.ret20, '按相对行业落后': np.where(np.isfinite(gap20), -gap20, 9.0).astype(np.float32),
        '两者平均排名': np.where(np.isfinite(r_gap), (r_ret + r_gap) / 2, 9.0).astype(np.float32),
        '按跌幅, 但剔除行业也大跌(行业20日<-10%)': np.where(np.isfinite(ind20) & (ind20 < -0.10), 9.0, cand.ret20).astype(np.float32)}
for nm, (fm, fc0) in {'A 大盘z+E6': (market, cand), 'C 成交额五分位': (fmC, fcC)}.items():
    for kn, kv in keys.items():
        fc = Candidates(uni=fc0.uni, e6=fc0.e6, buyok=fc0.buyok, ret20=kv)
        r = simulate(panel, fm, fc, DipConfig(leverage=1.0)); eq, ex = r["eq"], r["expo"]; met(dr(eq), f'{nm} | {kn}', ex)
