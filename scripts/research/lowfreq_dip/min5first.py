"""Extract first 5-min bar (09:30-09:35) open/close per stock-day from silver/qfq_kline_min5_v2 into fb_open.npy / fb_close.npy aligned to the panel. Resumable. Research only."""
import os, sys, time, glob
import numpy as np, pandas as pd, pyarrow.parquet as pq
from grp_lib import *
panel = load_panel(); nd, nc = panel.shape; codes = [str(c) for c in panel.codes]; dix = {d: i for i, d in enumerate(panel.dates)}
cix = {c.replace('.', '_'): j for j, c in enumerate(codes)}
if os.path.exists('fb.npz'):
    Z = np.load('fb.npz'); fo, fc, done = Z['fo'], Z['fc'], set(Z['done'].tolist())
else:
    fo = np.full((nd, nc), np.nan, np.float32); fc = np.full((nd, nc), np.nan, np.float32); done = set()
files = sorted(glob.glob(os.path.join(LAKE, 'silver/qfq_kline_min5_v2/*.parquet'))); T0 = time.time(); n = 0
for fn in files:
    key = os.path.basename(fn)[:-8]
    if key in done or key not in cix: continue
    if time.time() - T0 > float(sys.argv[1]): break
    t = pq.read_table(fn, columns=['date', 'time', 'open', 'close']).to_pandas()
    t = t[t['time'].astype(str).str[8:12] == '0935']
    j = cix[key]; di = np.array([dix.get(d, -1) for d in t['date'].astype(str)]); ok = di >= 0
    fo[di[ok], j] = t['open'].values[ok]; fc[di[ok], j] = t['close'].values[ok]; done.add(key); n += 1
np.savez('fb.npz', fo=fo, fc=fc, done=np.array(sorted(done)))
print('processed', n, 'total done', len(done), 'of', len(cix), round(time.time() - T0), 's', flush=True)
