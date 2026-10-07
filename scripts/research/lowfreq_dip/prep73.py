"""Export daily low / high (qfq) aligned to the new panel (c72/dates_new, codes_new). Research only."""
import os, sys, numpy as np, pyarrow.parquet as pq
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from quantlab.dipbuy.panel import _parquet_files, _stem_code
from pathlib import Path
LAKE = Path(os.path.expanduser('~/mnt/lake')); files = _parquet_files(LAKE / 'silver/qfq_kline_daily_v2')
cal = np.load('c72/dates_new.npy').astype('datetime64[D]'); codes = np.load('c72/codes_new.npy'); nd, nc = len(cal), len(codes)
print(len(files), nc, pq.read_schema(files[0]).names, flush=True)
lo = np.full((nd, nc), np.nan, np.float32); hi = np.full((nd, nc), np.nan, np.float32)
for j, p in enumerate(files):
    assert _stem_code(p.stem) == codes[j]
    t = pq.read_table(p, columns=['date', 'open', 'low', 'high']); d = t.column('date').to_numpy(zero_copy_only=False).astype('datetime64[D]')
    idx = np.searchsorted(cal, d); ok = idx < nd; ok[ok] &= cal[idx[ok]] == d[ok]
    if ok.any():
        ii = idx[ok]; op = t.column('open').to_numpy(zero_copy_only=False)[ok]; lo[ii, j] = t.column('low').to_numpy(zero_copy_only=False)[ok] / op; hi[ii, j] = t.column('high').to_numpy(zero_copy_only=False)[ok] / op
np.savez_compressed('c72/lowhigh.npz', lo=lo.astype(np.float16), hi=hi.astype(np.float16)); print('done', flush=True)
