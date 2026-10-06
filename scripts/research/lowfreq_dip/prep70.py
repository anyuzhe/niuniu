"""Export panel + D gates/pools/ranks + a few stock features to .npy so later experiments load in seconds. Research only."""
import numpy as np, pandas as pd, json
import grp11 as g
from grp11 import *
from quantlab.dipbuy.engine import _fee_by_day
D = 'c70/'
np.save(D + 'dates.npy', np.array(dates)); np.save(D + 'codes.npy', np.array(panel.codes))
for nm, a in (('O', O_), ('C', C_), ('F', F_)): np.save(D + nm + '.npy', np.asarray(a, np.float32))
np.save(D + 'buyok.npy', np.asarray(buyok, bool)); np.save(D + 'fee.npy', np.asarray(fee, np.float64))
for s in 'ACB':
    gate, e6, r20 = g.SL[s]
    np.save(D + f'gate{s}.npy', np.asarray(gate, bool)); np.save(D + f'pool{s}.npy', np.asarray(e6, bool))
    np.save(D + f'r20{s}.npy', np.asarray(r20, np.float32))
np.save(D + 'mz.npy', np.asarray(market.z, np.float64)); np.save(D + 'mret.npy', np.nan_to_num(np.asarray(market.mret, np.float64)))
# same r20 across sleeves?
a, b, c = (np.load(D + f'r20{s}.npy', mmap_mode='r') for s in 'ACB')
for s, x in (('B', b), ('C', c)):
    m = np.load(D + f'pool{s}.npy', mmap_mode='r')
    print('r20', s, 'equal to A on pool:', bool(np.allclose(np.asarray(x)[m], np.asarray(a)[m], equal_nan=True)), flush=True)
# features (float16)
Cf = np.asarray(C_, np.float64); Af = np.nan_to_num(np.asarray(panel.a, np.float64), nan=0.0)
def roll_mean(x, n):
    cs = np.cumsum(np.nan_to_num(x), 0); out = np.full(x.shape, np.nan); out[n - 1] = cs[n - 1]; out[n:] = cs[n:] - cs[:-n]
    ok = np.cumsum(np.isfinite(x), 0); cnt = np.full(x.shape, np.nan); cnt[n - 1] = ok[n - 1]; cnt[n:] = ok[n:] - ok[:-n]
    return np.where(cnt >= n, out / n, np.nan)
ma20 = roll_mean(Cf, 20); np.save(D + 'distma20.npy', (Cf / ma20 - 1).astype(np.float16)); print('distma20', flush=True)
ret = np.full(Cf.shape, np.nan); ret[1:] = Cf[1:] / Cf[:-1] - 1
m1 = roll_mean(ret, 60); m2 = roll_mean(ret ** 2, 60); sig = np.sqrt(np.maximum(m2 - m1 ** 2, 0)); np.save(D + 'sig60.npy', sig.astype(np.float16)); print('sig60', flush=True)
r5 = np.full(Cf.shape, np.nan); r5[5:] = Cf[5:] / Cf[:-5] - 1; np.save(D + 'r5.npy', r5.astype(np.float16))
a20 = roll_mean(Af, 20); vr = Af / np.where(a20 > 0, a20, np.nan); np.save(D + 'volratio.npy', vr.astype(np.float16)); print('volratio', flush=True)
mx = pd.DataFrame(Cf).rolling(60, min_periods=40).max().to_numpy(); np.save(D + 'dd60.npy', (Cf / mx - 1).astype(np.float16)); print('dd60', flush=True)
np.save(D + 'ret1.npy', ret.astype(np.float16))
print('done', flush=True)
