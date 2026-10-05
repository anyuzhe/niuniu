"""Minimum float-market-cap gate on A/B/C candidates (original 20d-drop ranking): return vs capacity. Research only."""
import sys
from grp11 import *
cap = np.load('cap.npy'); capk = np.where(np.isfinite(cap) & (cap > 0), cap, np.nan)
a = np.nan_to_num(panel.a, nan=0.0).astype(np.float64); cs = np.cumsum(a, 0); amt60 = np.full((nd, nc), np.nan, np.float32); amt60[60:] = ((cs[60:] - cs[:-60]) / 60).astype(np.float32); del a, cs
didx = {d: i for i, d in enumerate(panel.dates)}; cidx = {str(c): j for j, c in enumerate(panel.codes)}
which = sys.argv[1]
nm, fm, fc0 = {'A': ('A 大盘z+E6', market, cand), 'B': ('B 行业恐慌', fmB, fcB), 'C': ('C 成交额五分位', fmC, fcC)}[which]
for thr in (0, 15, 30, 50, 100):
    pool = fc0.e6 & (capk >= thr) if thr else fc0.e6
    fm2 = fm
    fc = Candidates(uni=fc0.uni, e6=pool, buyok=fc0.buyok, ret20=fc0.ret20)
    r = simulate(panel, fm2, fc, DipConfig(leverage=1.0)); eq, ex = r['eq'], r['expo']; tr = r['trades']
    met(dr(eq), f'{nm} | 流通市值>={thr}亿' if thr else f'{nm} | 无门槛', ex)
    am = np.array([amt60[didx[t['signal']], cidx[t['code']]] for t in tr]); am = am[np.isfinite(am)]
    cp = np.array([capk[didx[t['signal']], cidx[t['code']]] for t in tr]); cp = cp[np.isfinite(cp)]
    # capacity: 20 positions, each <= 2% of the stock's 60d average daily amount (use 25th pct amount): account size
    cap25 = 20 * 0.02 * np.percentile(am, 25) / 1e4
    print(f'{"":42s} 笔{len(tr)} 笔均{np.mean([t["ret"] for t in tr])*1e4:+5.0f}bp 持仓市值中位{np.median(cp):.0f}亿 成交额中位{np.median(am)/1e8:.2f}亿 25%分位{np.percentile(am,25)/1e8:.2f}亿 | 容量估计(20只×2%日成交额, 25%分位){cap25:,.0f}万元', flush=True)
