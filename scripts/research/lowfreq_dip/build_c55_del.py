"""14:55 5-minute close aligned to panel_del (listed from the old c55.npz + delisted min5 files). Research only."""
import os, glob, numpy as np, pyarrow.parquet as pq, pyarrow.compute as pc
z = np.load('panel_del.npz', allow_pickle=True); dates = z['dates'].astype(str); codes = z['codes'].astype(str); isdel = z['isdel'].astype(bool); nd, nc = len(dates), len(codes)
di = {d: i for i, d in enumerate(dates)}; ci = {c: j for j, c in enumerate(codes)}
old = np.load('c55.npz', allow_pickle=True); od = old['dates'].astype(str); oc = old['codes'].astype(str); oa = old['c55']
out = np.full((nd, nc), np.nan, np.float32)
ri = np.array([di.get(d, -1) for d in od]); cj = np.array([ci.get(c, -1) for c in oc])
m = ri >= 0; n = cj >= 0
sub = oa[m][:, n]; out[np.ix_(ri[m], cj[n])] = sub
print('from old', int(np.isfinite(out).sum()), flush=True)
M = os.path.expanduser('~/mnt/lake/bronze/provider=baostock/stock_kline_min5_delisted'); got = 0; nf = 0
for fp in sorted(glob.glob(M + '/*.parquet')):
    code = os.path.basename(fp)[:-8].replace('_', '.'); j = ci.get(code)
    if j is None: continue
    nf += 1
    t = pq.read_table(fp, columns=['date', 'time', 'close']); t = t.filter(pc.match_substring_regex(t['time'], r'1455\d*$'))
    for d, cl in zip(t['date'].to_pylist(), t['close'].to_pylist()):
        i = di.get(str(d))
        if i is not None and cl: out[i, j] = cl; got += 1
print('delisted files', nf, 'bars', got, 'finite total', int(np.isfinite(out).sum()), flush=True)
np.savez_compressed('c55_del.npz', c55=out, dates=dates, codes=codes)
