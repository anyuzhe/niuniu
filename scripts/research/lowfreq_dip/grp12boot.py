"""Paired block bootstrap: is 'C tiers 3/5/8% + B-only 2.5%' better than single C? Research only."""
import numpy as np
import grp12 as h
from grp12 import *
SL = h.SL; g = h.g
SL['P'] = (gC & ~gB & ~gA, fcC.e6, fcC.ret20); SL['Q'] = (gC & gB & ~gA, fcC.e6, fcC.ret20); SL['R'] = (gC & gA, fcC.e6, fcC.ret20); SL['S'] = (gB & ~gC & ~gA, fcB.e6, fcB.ret20)
SL['C'] = (gC, fcC.e6, fcC.ret20)
r1 = dr(fused(order='RQPS', w={'P': .03, 'Q': .05, 'R': .08, 'S': .025}, G=1.0, cash_yield=0.02)[0])
r0 = dr(fused(order='C', w=0.05, G=1.0, cash_yield=0.02)[0])
m = np.isfinite(r1) & np.isfinite(r0); a, b = r1[m], r0[m]; n = len(a)
sh = lambda x: x.mean() / x.std() * np.sqrt(245)
print('sharpe', sh(a), sh(b), 'diff', sh(a) - sh(b), 'corr', np.corrcoef(a, b)[0, 1])
rng = np.random.default_rng(1); L = 20; d = []
for _ in range(2000):
    idx = np.concatenate([np.arange(s, s + L) % n for s in rng.integers(0, n, n // L + 1)])[:n]
    d.append(sh(a[idx]) - sh(b[idx]))
d = np.array(d); print('boot diff mean', d.mean(), 'sd', d.std(), '90% CI', np.percentile(d, [5, 95]), 'P(diff>0)', (d > 0).mean())
ca = lambda x: np.prod(1 + x) ** (245 / len(x)) - 1
dc = []
for _ in range(2000):
    idx = np.concatenate([np.arange(s, s + L) % n for s in rng.integers(0, n, n // L + 1)])[:n]
    dc.append(ca(a[idx]) - ca(b[idx]))
dc = np.array(dc); print('cagr diff', ca(a) - ca(b), '90% CI', np.percentile(dc, [5, 95]), 'P>0', (dc > 0).mean())
