"""Extract the 14:55 5-minute bar close (raw, unadjusted) per (date, code) aligned to the dipbuy panel. Research only."""
import os, glob, numpy as np, pyarrow.parquet as pq, pyarrow.compute as pc, pyarrow as pa
from grp_lib import *
panel = load_panel(); dates = np.array(panel.dates); nd, nc = panel.shape
di = {d: i for i, d in enumerate(dates)}; ci = {c: j for j, c in enumerate(panel.codes)}
M = f'{LAKE}/bronze/provider=baostock/stock_kline_min5'
out = np.full((nd, nc), np.nan, np.float32); outv = np.full((nd, nc), np.nan, np.float32); got = 0
for k, fp in enumerate(sorted(glob.glob(M + '/*.parquet'))):
    code = os.path.basename(fp)[:-8].replace('_', '.')
    j = ci.get(code)
    if j is None: continue
    t = pq.read_table(fp, columns=['date', 'time', 'close', 'volume'], filters=[('time', 'in', [f'{d}' for d in []])]) if False else pq.read_table(fp, columns=['date', 'time', 'close', 'volume'])
    m = pc.match_substring_regex(t['time'], r'1455\d*$')
    t = t.filter(m)
    for d, cl, v in zip(t['date'].to_pylist(), t['close'].to_pylist(), t['volume'].to_pylist()):
        i = di.get(str(d))
        if i is not None and cl:
            out[i, j] = cl; outv[i, j] = v; got += 1
    if k % 500 == 0: print(k, got, flush=True)
np.savez_compressed('c55.npz', c55=out, v55=outv, dates=dates, codes=np.array(panel.codes))
print('done', got, flush=True)
