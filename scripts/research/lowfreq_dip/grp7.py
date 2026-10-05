"""Industry panic + industry-level trend/heat filters ('dip in hot / uptrend industries, skip structurally falling ones') and holding-period sweep.
Trend = SW L1 equal-weight index return over [t-L, t-20] (excludes the dip itself); rank among the 31 industries. Research only."""
import time
from grp_lib import *
T0 = time.time()
panel = load_panel(); nd, nc = panel.shape
market, cand = compute_features(panel, 5e7, 3.0)
D = pd.read_parquet(f'{LAKE}/bronze/provider=swsresearch/industry_classification_history/2026-09-23.parquet')
D = D.sort_values(['code', 'start_date']).groupby('code').tail(1).set_index('code')['l1_code'].to_dict()
sym = [str(c).split('.')[-1] for c in panel.codes]; raw = np.array([D.get(s, '') for s in sym]); u = sorted(set(raw) - {''}); ix = {k: i for i, k in enumerate(u)}
l1 = np.array([ix.get(x, -1) for x in raw], np.int16); ng = len(u)
def ind_series(lab):
    """daily EW return (prior-day tradable members, >=8) and amount per group."""
    ng_ = int(lab.max()) + 1
    uni_prev = np.vstack([np.zeros((1, nc), bool), cand.uni[:-1]])
    R = np.full((nd, ng_), np.nan); A = np.zeros((nd, ng_))
    for g in range(ng_):
        cols = np.nonzero(lab == g)[0]
        c = panel.c[:, cols].astype(np.float64); r = np.full(c.shape, np.nan); r[1:] = c[1:] / c[:-1] - 1
        ok = uni_prev[:, cols] & np.isfinite(r); n = ok.sum(1)
        R[:, g] = np.where(n >= MIN_MEMBERS, np.where(ok, r, 0).sum(1) / np.maximum(n, 1), np.nan)
        A[:, g] = np.nansum(panel.a[:, cols], 1)
    return R, A
def zscore(R):
    z = np.full(R.shape, np.nan)
    for g in range(R.shape[1]):
        s = pd.Series(R[:, g]); c20 = np.exp(np.log1p(s).rolling(20, min_periods=20).sum()) - 1; sd = s.rolling(60, min_periods=40).std()
        z[:, g] = (c20 / (sd * np.sqrt(20))).to_numpy()
    return z
def lagret(R, a, b):
    """index return from t-a to t-b (b<a)."""
    idx = np.cumprod(1 + np.nan_to_num(R), 0); out = np.full(R.shape, np.nan)
    out[a:] = idx[a - b:nd - b] / idx[:nd - a] - 1
    valid = np.isfinite(R); cnt = np.cumsum(valid, 0); okk = np.zeros(R.shape, bool); okk[a:] = (cnt[a:] - cnt[:nd - a]) >= int(a * 0.8)
    return np.where(okk, out, np.nan)
def rank_pct(x):
    return pd.DataFrame(x).rank(axis=1, pct=True).to_numpy()
def build(trig, lab):
    inT = np.zeros((nd, nc), bool); m = np.nonzero(lab >= 0)[0]; inT[:, m] = trig[:, lab[m]]
    pool = cand.uni & inT & np.isfinite(cand.ret20)
    anyd = trig.any(1)
    return Market(mret=market.mret, mk20=market.mk20, z=np.where(anyd, -9.0, 9.0), count=market.count), Candidates(uni=cand.uni, e6=pool, buyok=cand.buyok, ret20=cand.ret20)
def run2(label, fm, fc, hold=20, start='2008-01-01', L=1.0, slip=0.0, quiet=False):
    cfg = DipConfig(leverage=L, hold_days=hold, start=start, slippage_bp=slip)
    r = simulate(panel, fm, fc, cfg); s = summarize(panel, fm, r, cfg); st = s['stats'] or {}; tr = s['trades']; h = halves(panel, r['eq'])
    if not quiet:
        print(f"{label:50s} 触发{s['gate_days']:5d}天 年化{st.get('cagr',0)*100:+5.1f}% 夏普{st.get('sharpe',0):+.2f} 回撤{st.get('max_drawdown',0)*100:4.0f}% 仓位{st.get('exposure',0)*100:3.0f}% 笔{tr['n']:5d} 笔均{(tr['mean'] or 0)*1e4:+4.0f}bp | 前半{h[0]} 后半{h[1]}", flush=True)
    return st.get('cagr', 0), st.get('sharpe', 0), s['gate_days']
if __name__ == '__main__':
    R, A = ind_series(l1); Z = zscore(R)
    base = np.isfinite(Z) & (Z <= -1.5)
    feats = {}
    for L_ in (120, 250):
        f = lagret(R, L_, 20); feats[f'趋势{L_}日'] = f; feats[f'趋势{L_}日排名'] = rank_pct(f)
    # heat: industry share of market amount, 60d avg vs 250d avg (>1 = gaining attention); measured before the last 20 days
    tot = A.sum(1, keepdims=True); share = A / np.maximum(tot, 1)
    s60 = pd.DataFrame(share).rolling(60, min_periods=40).mean().shift(20).to_numpy(); s250 = pd.DataFrame(share).rolling(250, min_periods=150).mean().shift(20).to_numpy()
    heat = s60 / s250; feats['热度(成交额占比)'] = heat; feats['热度排名'] = rank_pct(heat)
    filters = {
        '无过滤(基准)': np.ones_like(base),
        '趋势120日>0': feats['趋势120日'] > 0,
        '趋势120日排名前一半': feats['趋势120日排名'] >= 0.5,
        '趋势120日排名前三分之一': feats['趋势120日排名'] >= 2 / 3,
        '趋势120日排名后三分之一剔除': feats['趋势120日排名'] > 1 / 3,
        '趋势250日>0': feats['趋势250日'] > 0,
        '趋势250日排名前一半': feats['趋势250日排名'] >= 0.5,
        '趋势250日排名前三分之一': feats['趋势250日排名'] >= 2 / 3,
        '趋势250日排名后三分之一剔除': feats['趋势250日排名'] > 1 / 3,
        '热度>1': feats['热度(成交额占比)'] > 1,
        '热度排名前一半': feats['热度排名'] >= 0.5,
        '趋势120日>0 且 热度>1': (feats['趋势120日'] > 0) & (feats['热度(成交额占比)'] > 1),
        '反向:趋势120日排名后一半(对照)': feats['趋势120日排名'] < 0.5,
        '反向:趋势250日排名后一半(对照)': feats['趋势250日排名'] < 0.5,
    }
    ST = '2009-07-01'
    print('=== 同一窗口 2009-07 起（250 日趋势需要一年历史，所以去掉了 2008），持有20日，1x', flush=True)
    for name, f in filters.items():
        fm, fc = build(base & np.nan_to_num(f.astype(float)).astype(bool), l1)
        run2(name, fm, fc, start=ST)
    print('--- 基准全样本（2008 起）', flush=True)
    fm, fc = build(base, l1); run2('无过滤 全样本', fm, fc)
    print('=== 持有期扫描（1x，2009-07 起）', flush=True)
    sel = {'无过滤': np.ones_like(base), '趋势120日>0': feats['趋势120日'] > 0, '趋势120日排名前一半': feats['趋势120日排名'] >= 0.5, '趋势250日>0': feats['趋势250日'] > 0, '趋势250日排名前一半': feats['趋势250日排名'] >= 0.5, '热度排名前一半': feats['热度排名'] >= 0.5}
    for name, f in sel.items():
        fm, fc = build(base & np.nan_to_num(f.astype(float)).astype(bool), l1)
        for hd in (3, 5, 10, 15, 20, 30, 40, 60):
            run2(f'{name} 持有{hd}日', fm, fc, hold=hd, start=ST)
        print(flush=True)
    print('done', round(time.time() - T0), 's')
