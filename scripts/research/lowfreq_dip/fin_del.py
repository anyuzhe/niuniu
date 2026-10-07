"""Annual profit + balance data (baostock, with pubDate) for the delisted columns, resumable. Research only."""
import baostock as bs, numpy as np, json, os, sys, time
T0 = time.time(); LIM = float(sys.argv[1]) if len(sys.argv) > 1 else 150
codes = np.load('c80/codes.npy').astype(str); isdel = np.load('c80/isdel.npy'); dates = np.load('c80/dates.npy').astype(str)
F = 'fin_del.json'; res = json.load(open(F)) if os.path.exists(F) else {}
CC = np.load('c80/C.npy', mmap_mode='r'); bs.login()
def q(fn, **kw):
    rs = fn(**kw); rows = []
    while rs.error_code == '0' and rs.next(): rows.append(rs.get_row_data())
    return rs.fields, rows
dl = [c for c, d in zip(codes, isdel) if d]
for c in dl:
    if c in res: continue
    if time.time() - T0 > LIM: break
    j = int(np.nonzero(codes == c)[0][0]); ok = np.nonzero(np.isfinite(CC[:, j]))[0]
    if not len(ok): res[c] = {}; continue
    y0, y1 = int(dates[ok[0]][:4]) - 1, int(dates[ok[-1]][:4])
    out = {}
    for y in range(max(2005, y0), min(2025, y1) + 1):
        f1, r1 = q(bs.query_profit_data, code=c, year=y, quarter=4); f2, r2 = q(bs.query_balance_data, code=c, year=y, quarter=4)
        if r1: out[str(y)] = dict(zip(f1, r1[0])); out[str(y)].update({k: v for k, v in zip(f2, r2[0]) if k in ('liabilityToAsset', 'assetToEquity')} if r2 else {})
    res[c] = out
    json.dump(res, open(F, 'w'), ensure_ascii=False)
print('done', len(res), 'of', len(dl), round(time.time() - T0), 's', flush=True)
bs.logout()
