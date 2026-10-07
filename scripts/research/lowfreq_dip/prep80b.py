"""stage 2: features for prep80 (loads c80 O/C/A)."""
import numpy as np, pandas as pd, os
D = os.environ.get("OUTDIR","c80")+"/"
Cf = np.load(D+"C.npy").astype(np.float64); Af = np.nan_to_num(np.load(D+"A.npy").astype(np.float64), nan=0.0)

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
