"""Export panel + D gates/pools/ranks + a few stock features to .npy so later experiments load in seconds. Research only."""
import numpy as np, pandas as pd, json
import grp11 as g
from grp11 import *
from quantlab.dipbuy.engine import _fee_by_day
import os; D = os.environ.get('OUTDIR','c80')+'/'; os.makedirs(D, exist_ok=True)
np.save(D + 'dates.npy', np.array(dates)); np.save(D + 'codes.npy', np.array(panel.codes))
DROP = os.environ.get('DROPDEL') == '1'
isdel = np.load(os.environ['PANEL_NPZ'], allow_pickle=True)['isdel'].astype(bool)
if DROP:   # listed-only run: save gates/pools padded to the full column set, prefix 0
    keep = ~isdel
    for s in 'ACB':
        gate, e6, r20 = g.SL[s]; full = np.zeros((nd, len(isdel)), bool); full[:, keep] = e6
        np.save(D + f'gate0{s}.npy', np.asarray(gate, bool)); np.save(D + f'pool0{s}.npy', full)
    print('nodel done', flush=True); raise SystemExit
for nm, a in (('O', O_), ('C', C_), ('F', F_)): np.save(D + nm + '.npy', np.asarray(a, np.float32))
np.save(D + 'A.npy', np.asarray(panel.a, np.float32)); np.save(D + 'isdel.npy', isdel)
np.save(D + 'buyok.npy', np.asarray(buyok, bool)); np.save(D + 'fee.npy', np.asarray(fee, np.float64))
for s in 'ACB':
    gate, e6, r20 = g.SL[s]
    np.save(D + f'gate{s}.npy', np.asarray(gate, bool)); np.save(D + f'pool{s}.npy', np.asarray(e6, bool))
    if s == 'A': np.save(D + 'r20A.npy', np.asarray(r20, np.float32))
np.save(D + 'mz.npy', np.asarray(market.z, np.float64)); np.save(D + 'mret.npy', np.nan_to_num(np.asarray(market.mret, np.float64)))
uni_prev = np.vstack([np.zeros((1, nc), bool), cand.uni[:-1]]); lab_prev = np.vstack([np.full((1, nc), -1, lab.dtype), lab[:-1]])
c = panel.c.astype(np.float32); ret1 = np.full((nd, nc), np.nan, np.float32); ret1[1:] = c[1:] / c[:-1] - 1
ok_all = uni_prev & np.isfinite(ret1); ret1 = np.where(ok_all, ret1, 0.0).astype(np.float32)
Rq = np.full((nd, 5), np.nan)
for k in range(5):
    M = (lab_prev == k) & ok_all; n = M.sum(1); ss = (ret1 * M).sum(1, dtype=np.float64); Rq[:, k] = np.where(n >= MIN_MEMBERS, ss / np.maximum(n, 1), np.nan)
np.savez_compressed(D+'series.npz', Ri=np.asarray(g.R,np.float64), Rq=Rq, mret=np.asarray(market.mret,np.float64), l1=np.asarray(l1), lab=lab, uni=np.asarray(cand.uni), poolA=np.asarray(cand.e6), codes=np.array(panel.codes))
print('stage1 done',flush=True)
