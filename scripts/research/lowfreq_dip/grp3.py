"""Dynamic style/size groupings (quintiles recomputed every day among tradable stocks) with within-day shuffled-label nulls. Research only.
Features: 60d avg amount (liquidity/size proxy), float market cap (point-in-time shares), 12-1 momentum, 60d volatility, raw price, PB, PE(TTM>0)."""
import json, time, glob
from grp_lib import *
T0 = time.time()
panel = load_panel(); nd, nc = panel.shape; codes = [str(c) for c in panel.codes]
market, cand = compute_features(panel, 5e7, 3.0)
uni = cand.uni
def quintiles(x, nq=5):
    """x [nd,nc] float (nan = none) -> int8 labels, quantile among valid (uni & finite) stocks each day."""
    out = np.full((nd, nc), -1, np.int8)
    for a in range(0, nd, 400):
        b = min(nd, a + 400)
        v = np.where(uni[a:b] & np.isfinite(x[a:b]), x[a:b], np.nan)
        pct = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
        lab = np.where(np.isfinite(pct), np.minimum((pct * nq).astype(np.int16), nq - 1), -1)
        out[a:b] = lab.astype(np.int8)
    return out
feats = {}
c64 = panel.c
# liquidity (60d mean amount)
a = np.nan_to_num(panel.a, nan=0.0).astype(np.float64); cs = np.cumsum(a, 0); amt60 = np.full((nd, nc), np.nan, np.float32); amt60[60:] = ((cs[60:] - cs[:-60]) / 60).astype(np.float32); del a, cs
feats['60日成交额'] = amt60
mom = np.full((nd, nc), np.nan, np.float32); mom[250:] = c64[230:-20] / c64[:-250] - 1; feats['12-1动量'] = mom
r1 = np.full((nd, nc), np.nan, np.float32); r1[1:] = c64[1:] / c64[:-1] - 1
vol = np.full((nd, nc), np.nan, np.float32)
for j0 in range(0, nc, 500):
    df = pd.DataFrame(r1[:, j0:j0 + 500]); vol[:, j0:j0 + 500] = df.rolling(60, min_periods=40).std().to_numpy()
feats['60日波动'] = vol; del r1
feats['原始价格'] = panel.c / panel.f
# float market cap (point-in-time) and valuation
only = os.environ.get('ONLY')
need_val = (not only) or any(k in only.split(',') for k in ('流通市值', 'PB', 'PE(TTM>0)'))
t_load = time.time()
dates = np.array(panel.dates)
cap = np.full((nd, nc), np.nan, np.float32); pb = np.full((nd, nc), np.nan, np.float32); pe = np.full((nd, nc), np.nan, np.float32)
n_cap = n_val = 0
for j, code in enumerate(codes if need_val else []):
    sym = code.split('.')[-1]; fn = f'{LAKE}/bronze/provider=eastmoney/share_capital/{sym}.parquet'
    if os.path.exists(fn):
        try:
            S = pd.read_parquet(fn, columns=['NOTICE_DATE', 'END_DATE', 'LISTED_A_SHARES'])
            S['d'] = pd.to_datetime(S['NOTICE_DATE'].fillna(S['END_DATE']), errors='coerce').dt.strftime('%Y-%m-%d')
            S = S.dropna(subset=['d', 'LISTED_A_SHARES']).sort_values('d')
            if len(S):
                ix = np.searchsorted(S['d'].values.astype('U10'), dates, side='right') - 1
                sh = np.where(ix >= 0, S['LISTED_A_SHARES'].values[np.maximum(ix, 0)], np.nan)
                cap[:, j] = (panel.c[:, j] / panel.f[:, j] * sh / 1e8).astype(np.float32); n_cap += 1
        except Exception:
            pass
    fv = f'{LAKE}/bronze/provider=baostock/valuation_daily_v1/{code.replace(".", "_")}.parquet'
    if os.path.exists(fv):
        try:
            V = pd.read_parquet(fv, columns=['date', 'peTTM', 'pbMRQ'])
            ix = np.searchsorted(dates, V['date'].values.astype('U10'))
            ok = (ix < nd); ok[ok] &= dates[ix[ok]] == V['date'].values.astype('U10')[ok]
            pbv = pd.to_numeric(V['pbMRQ'], errors='coerce').values; pev = pd.to_numeric(V['peTTM'], errors='coerce').values
            pb[ix[ok], j] = pbv[ok]; pe[ix[ok], j] = pev[ok]; n_val += 1
        except Exception:
            pass
    if j % 1000 == 0:
        print('load', j, round(time.time() - t_load), 's', flush=True)
print('market-cap coverage', n_cap, 'valuation coverage', n_val, 'of', nc, flush=True)
feats['流通市值'] = cap
feats['PB'] = np.where(pb > 0, pb, np.nan).astype(np.float32)
feats['PE(TTM>0)'] = np.where(pe > 0, pe, np.nan).astype(np.float32)
NP = int(os.environ.get('NPERM', 10)); out = []
for name, x in feats.items():
    if only and name not in only.split(','):
        continue
    lab = quintiles(x)
    cover = (lab >= 0).mean()
    print(f'--- {name}: 五分位, 平均每天已分组 {int((lab >= 0).sum(1).mean())} 只', flush=True)
    rng = np.random.default_rng(9)
    for s in ('any', 'idio'):
        r = run(panel, f'{name} 五分位', lab, s, quiet=True)
        perm = []
        for k in range(NP):
            p = lab.copy()
            for t in range(nd):
                m = np.nonzero(lab[t] >= 0)[0]
                if len(m) > 5:
                    p[t, m] = lab[t, rng.permutation(m)]
            perm.append(run(panel, 'p', p, s, quiet=True))
        cg = np.array([q['cagr'] for q in perm]); sh = np.array([q['sharpe'] for q in perm])
        print(f"{name:10s} {s:4s} 真实: 年化{r['cagr']*100:+5.1f}% 夏普{r['sharpe']:+.2f} 回撤{r['mdd']*100:4.0f}% 仓位{r['expo']*100:3.0f}% 触发{r['gate_days']}天 笔{r['n']} | "
              f"打乱{NP}次年化均{cg.mean()*100:+5.1f}% [{cg.min()*100:+.1f},{cg.max()*100:+.1f}] 夏普均{sh.mean():+.2f} | 真实比{(cg < r['cagr']).mean()*100:.0f}%的打乱高 | 前半{r['first']} 后半{r['second']}", flush=True)
        out.append(dict(name=name, scope=s, real=r, perm_cagr=cg.tolist(), perm_sharpe=sh.tolist()))
    del lab
json.dump(out, open('grp3_' + (only or 'all').replace(',', '_') + '.json', 'w'), ensure_ascii=False)
print('done', round(time.time() - T0), 's')
