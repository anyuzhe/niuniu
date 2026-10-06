"""Is 'B evicts A/C' just a shorter holding period? (a) D with fixed holds of 5/10/15/20/30 days, no eviction. Research only."""
import grp11 as g
from grp11 import *
W = {'A': .08, 'C': .08, 'B': .025}
for H in (5, 8, 10, 15, 20, 30):
    eq, ex, ntr, pnl, wsum, minr = g.fused(order='ACB', w=W, G=1.0, caps={}, cash_yield=0.02, H=H)
    r = dr(eq); met(r, f'D 固定持有 {H:2d} 天(次日开盘买,2008起)', ex)
    print(f'{"":46s} ' + ' '.join(f"{s}:{ntr[s]}笔均{pnl[s]/max(ntr[s],1)*1e4:+.0f}bp" for s in ntr), flush=True)
