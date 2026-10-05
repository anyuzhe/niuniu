"""Rank by float market cap (small first / large first) vs original 20d-drop ranking, inside market-panic (A: z+E6) and industry-panic (B), plus turnover (C). Research only."""
import sys
from grp11 import *
cap = np.load('cap.npy'); yrs = np.array([int(d[:4]) for d in panel.dates])
cov = (np.isfinite(cap) & cand.uni).sum(1) / np.maximum(cand.uni.sum(1), 1)
print('流通市值覆盖率(uni内)按年:', ' '.join(f'{y}:{cov[yrs==y].mean()*100:.0f}%' for y in range(2008, 2027, 2)), flush=True)
rk = lambda key, fc0: Candidates(uni=fc0.uni, e6=fc0.e6, buyok=fc0.buyok, ret20=key.astype(np.float32))
capk = np.where(np.isfinite(cap) & (cap > 0), cap, np.nan)
keys = {'原: 20日跌幅': None, '市值从小到大': np.where(np.isfinite(capk), capk, 1e9), '市值从大到小': np.where(np.isfinite(capk), -capk, 1e9)}
which = sys.argv[1]
S = {'A': ('A 大盘z+E6', market, cand), 'B': ('B 行业恐慌', fmB, fcB), 'C': ('C 成交额五分位', fmC, fcC)}[which]
nm, fm, fc0 = S
for kn, kv in keys.items():
    fc = fc0 if kv is None else rk(kv, fc0)
    r = simulate(panel, fm, fc, DipConfig(leverage=1.0)); eq, ex = r['eq'], r['expo']; tr = r['trades']
    cs = [capk[panel.dates.tolist().index(t['signal']) if False else 0, 0] for t in tr[:0]]
    met(dr(eq), f'{nm} | {kn}', ex)
    # median cap of picks at signal
    didx = {d: i for i, d in enumerate(panel.dates)}; cidx = {str(c): j for j, c in enumerate(panel.codes)}
    pc = [capk[didx[t['signal']], cidx[t['code']]] for t in tr]; pc = np.array([x for x in pc if np.isfinite(x)])
    print(f'{"":46s} 笔{len(tr)} 笔均{np.mean([t["ret"] for t in tr])*1e4:+5.0f}bp 持仓股流通市值中位 {np.median(pc):.0f}亿 (25%分位 {np.percentile(pc,25):.0f}, 75%分位 {np.percentile(pc,75):.0f})', flush=True)
