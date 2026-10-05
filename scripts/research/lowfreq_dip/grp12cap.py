"""Build float-market-cap quintile labels (point-in-time shares) and cache to capq.npy. Research only."""
from grp_lib import *
import time
panel = load_panel(); nd, nc = panel.shape; codes = [str(c) for c in panel.codes]
market, cand = compute_features(panel, 5e7, 3.0); uni = cand.uni
dates = np.array(panel.dates); cap = np.full((nd, nc), np.nan, np.float32); n = 0; T0 = time.time()
for j, code in enumerate(codes):
    sym = code.split('.')[-1]; fn = f'{LAKE}/bronze/provider=eastmoney/share_capital/{sym}.parquet'
    if os.path.exists(fn):
        try:
            S = pd.read_parquet(fn, columns=['NOTICE_DATE', 'END_DATE', 'LISTED_A_SHARES'])
            S['d'] = pd.to_datetime(S['NOTICE_DATE'].fillna(S['END_DATE']), errors='coerce').dt.strftime('%Y-%m-%d')
            S = S.dropna(subset=['d', 'LISTED_A_SHARES']).sort_values('d')
            if len(S):
                ix = np.searchsorted(S['d'].values.astype('U10'), dates, side='right') - 1
                sh = np.where(ix >= 0, S['LISTED_A_SHARES'].values[np.maximum(ix, 0)], np.nan)
                cap[:, j] = (panel.c[:, j] / panel.f[:, j] * sh / 1e8).astype(np.float32); n += 1
        except Exception: pass
    if j % 1000 == 0: print(j, round(time.time() - T0), flush=True)
out = np.full((nd, nc), -1, np.int8)
for a in range(0, nd, 400):
    b = min(nd, a + 400); v = np.where(uni[a:b] & np.isfinite(cap[a:b]), cap[a:b], np.nan)
    pct = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
    out[a:b] = np.where(np.isfinite(pct), np.minimum((pct * 5).astype(np.int16), 4), -1).astype(np.int8)
np.save('cap.npy', cap); np.save('capq.npy', out); print('coverage', n, 'labelled/day', int((out >= 0).sum(1).mean()))
