"""Export group daily-return series (industries, amount quintiles), labels, universe so the panic window can be varied without reloading the panel. Research only."""
import numpy as np, pandas as pd
import grp11 as g
from grp11 import *
D = 'c72/'
import os; os.makedirs(D, exist_ok=True)
# quintile (dynamic label) daily EW means: replicate group_z dyn branch
uni_prev = np.vstack([np.zeros((1, nc), bool), cand.uni[:-1]])
lab_prev = np.vstack([np.full((1, nc), -1, lab.dtype), lab[:-1]])
c = panel.c.astype(np.float32)
ret1 = np.full((nd, nc), np.nan, np.float32); ret1[1:] = c[1:] / c[:-1] - 1
ok_all = uni_prev & np.isfinite(ret1); ret1 = np.where(ok_all, ret1, 0.0).astype(np.float32)
Rq = np.full((nd, 5), np.nan)
for k in range(5):
    M = (lab_prev == k) & ok_all; n = M.sum(1); s = (ret1 * M).sum(1, dtype=np.float64)
    Rq[:, k] = np.where(n >= MIN_MEMBERS, s / np.maximum(n, 1), np.nan)
Ri = np.asarray(g.R, np.float64)
np.savez_compressed(D + 'series.npz', Ri=Ri, Rq=Rq, mret=np.asarray(market.mret, np.float64), l1=np.asarray(l1), lab=lab, uni=np.asarray(cand.uni), poolA=np.asarray(cand.e6))
print('done', Ri.shape, Rq.shape, flush=True)
