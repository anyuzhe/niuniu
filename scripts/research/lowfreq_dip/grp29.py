"""D optimisation ideas not tried before: idle-cash yield, per-sleeve holding days, signal-depth position scaling. Research only."""
import sys, inspect, grp11 as g
from grp11 import *
W = {'A': .08, 'C': .08, 'B': .025}
src = inspect.getsource(g.fused).replace('def fused(', 'def fused_z(').replace(
    "size = min((w[s] if isinstance(w, dict) else w) * equity,", "size = min((w[s] if isinstance(w, dict) else w) * equity * ZF[s][t],")
exec(src, g.__dict__)
def zf(zarr, lo, hi, base=-1.5):
    f = np.clip(np.where(np.isfinite(zarr), zarr / base, 1.0), lo, hi); return f
mode = sys.argv[1]
if mode == 'cash':
    for cy in (0.0, 0.02, 0.03, 0.04):
        show(f'D 闲置资金年化 {cy*100:g}%', order='ACB', w=W, G=1.0, caps={}, cash_yield=cy)
elif mode == 'hold':
    for hA, hC, hB in ((20, 20, 20), (30, 20, 20), (20, 30, 20), (20, 20, 30), (15, 20, 20), (20, 15, 20), (20, 20, 15), (30, 30, 30), (15, 15, 15), (40, 40, 40)):
        show(f'D 持有 A{hA} C{hC} B{hB}', order='ACB', w=W, G=1.0, caps={}, cash_yield=0.02, H={'A': hA, 'C': hC, 'B': hB})
elif mode == 'depth':
    zA, zB, zC = market.z, fmB.z, fmC.z
    for lo, hi in ((1.0, 1.0), (0.75, 1.5), (0.5, 2.0), (1.0, 2.0)):
        g.ZF = {'A': zf(zA, lo, hi), 'B': zf(zB, lo, hi), 'C': zf(zC, lo, hi)}
        eq, ex, ntr, pnl, wsum, minr = g.fused_z(order='ACB', w=W, G=1.0, caps={}, cash_yield=0.02)
        met(dr(eq), f'D 仓位按 z 深度缩放 [{lo},{hi}]（z/−1.5）', ex)
