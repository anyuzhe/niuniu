"""Daily baostock valuation (peTTM/pbMRQ/psTTM) aligned to the c80 panel (listed + delisted columns). Research only."""
import numpy as np, glob, os, time, pyarrow.parquet as pq, pandas as pd
T0 = time.time(); L = os.path.expanduser('~/mnt/lake/bronze/provider=baostock/valuation_daily_v1/')
dates = np.load('c80/dates.npy').astype(str); codes = np.load('c80/codes.npy').astype(str); nd, nc = len(dates), len(codes)
ci = {c: i for i, c in enumerate(codes)}; di = {d: i for i, d in enumerate(dates)}
arr = {k: np.full((nd, nc), np.nan, np.float32) for k in ('pe', 'pb', 'ps')}; hit = 0
for n, f in enumerate(sorted(glob.glob(L + '*.parquet'))):
    code = os.path.basename(f)[:-8].replace('_', '.')
    if code not in ci: continue
    t = pq.read_table(f, columns=['date', 'peTTM', 'pbMRQ', 'psTTM']).to_pandas(); j = ci[code]
    ix = t['date'].astype(str).map(di); m = ix.notna().values; ii = ix[m].astype(int).values; hit += 1
    for k, cn in (('pe', 'peTTM'), ('pb', 'pbMRQ'), ('ps', 'psTTM')): arr[k][ii, j] = pd.to_numeric(t[cn], errors='coerce').values[m]
print('matched', hit, 'of', nc, round(time.time() - T0), 's', flush=True)
for k, a in arr.items(): np.save(f'c80/{k}.npy', a.astype(np.float16)); print(k, 'finite', np.isfinite(a).mean().round(3), flush=True)
