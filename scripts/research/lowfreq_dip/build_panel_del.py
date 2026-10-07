"""Listed panel (lake qfq v2) + delisted stocks (baostock raw + baostock qfq twin) -> panel_del.npz with an `isdel` flag. Research only."""
import os, sys, glob, time, numpy as np, pandas as pd
from grp_lib import *
t0 = time.time(); base = load_panel(); nd, nc = base.shape; print('listed panel', base.shape, round(time.time() - t0), 's', flush=True)
cal = np.array(base.dates).astype('datetime64[D]'); B = os.path.expanduser('~/mnt/lake/bronze/provider=baostock/')
raw = {os.path.basename(f)[:-8]: f for f in glob.glob(B + 'stock_kline_daily_delisted/*.parquet')}; qf = {os.path.basename(f)[:-8]: f for f in glob.glob(B + 'stock_kline_daily_delisted_qfq_bs/*.parquet')}
keys = sorted(set(raw) & set(qf)); nx = len(keys)
o = np.full((nd, nx), np.nan, np.float32); c = o.copy(); f = o.copy(); a = o.copy(); st = np.zeros((nd, nx), bool); ts = np.full((nd, nx), -1, np.int8); codes = []; have = set(base.codes)
for j, k in enumerate(keys):
    code = k.replace('_', '.', 1); codes.append(code)
    r = pd.read_parquet(raw[k]); q = pd.read_parquet(qf[k]); assert len(r) == len(q) and (r['date'].values == q['date'].values).all(), k
    d = pd.to_datetime(r['date']).values.astype('datetime64[D]'); idx = np.searchsorted(cal, d); ok = idx < nd; ok[ok] &= cal[idx[ok]] == d[ok]
    if not ok.any(): continue
    ii = idx[ok]; trad = (r['tradestatus'].astype(str).values == '1')[ok]
    rc = r['close'].values[ok].astype(np.float64); qc = q['close'].values[ok].astype(np.float64); qo = q['open'].values[ok].astype(np.float64)
    fac = np.where((rc > 0) & np.isfinite(rc), qc / np.where(rc > 0, rc, np.nan), np.nan)
    live = trad & np.isfinite(qc) & (qc > 0) & np.isfinite(qo) & (qo > 0)
    o[ii, j] = np.where(live, qo, np.nan); c[ii, j] = np.where(live, qc, np.nan); f[ii, j] = np.where(live, fac, np.nan)
    a[ii, j] = np.where(live, pd.to_numeric(r['amount'], errors='coerce').values[ok], np.nan)
    st[ii, j] = (r['isST'].astype(str).values == '1')[ok]; ts[ii, j] = np.where(trad, 1, 0)
print('delisted cols', nx, 'dup with listed:', sum(c_ in have for c_ in codes), round(time.time() - t0), 's', flush=True)
panel_o = np.hstack([base.o, o]); panel_c = np.hstack([base.c, c]); panel_f = np.hstack([base.f, f]); panel_a = np.hstack([base.a, a])
np.savez('panel_del.npz', dates=np.array(base.dates), codes=np.array(list(base.codes) + codes), o=panel_o, c=panel_c, f=panel_f, a=panel_a, st=np.hstack([base.st, st]), ts=np.hstack([base.ts, ts]), isdel=np.r_[np.zeros(nc, bool), np.ones(nx, bool)])
print('saved', round(time.time() - t0), 's', flush=True)
