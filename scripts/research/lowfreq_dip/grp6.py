"""Industry panic with the E6 (Bollinger lower-band reclaim) candidate filter, on the product engine. Research only."""
from grp_lib import *
panel = load_panel(); market, cand = compute_features(panel, 5e7, 3.0)
D = pd.read_parquet(f'{LAKE}/bronze/provider=swsresearch/industry_classification_history/2026-09-23.parquet')
D = D.sort_values(['code', 'start_date']).groupby('code').tail(1).set_index('code')['l1_code'].to_dict()
sym = [str(c).split('.')[-1] for c in panel.codes]; raw = np.array([D.get(s, '') for s in sym]); u = sorted(set(raw) - {''}); ix = {k: i for i, k in enumerate(u)}
l1 = np.array([ix.get(x, -1) for x in raw], np.int16)
def go(label, lab, scope, L=1.0, e6=True):
    cfg = DipConfig(leverage=L); fm, fc, _ = inputs(panel, cfg, lab, scope)
    pool = fc.e6 & cand.e6 if e6 else fc.e6
    fc = Candidates(uni=fc.uni, e6=pool, buyok=fc.buyok, ret20=fc.ret20)
    r = simulate(panel, fm, fc, cfg); s = summarize(panel, fm, r, cfg); st = s['stats']; tr = s['trades']; h = halves(panel, r['eq'])
    print(f"{label:44s} 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:+.2f} 回撤{st['max_drawdown']*100:4.0f}% 仓位{st['exposure']*100:3.0f}% 笔{tr['n']:5d} 笔均{tr['mean']*1e4:+4.0f}bp | 前半{h[0]} 后半{h[1]}", flush=True)
    return st['cagr'], st['sharpe']
for scope in ('any', 'idio'):
    for L in (1.0, 2.0):
        go(f'申万一级 + E6 [{scope}] {L:g}x', l1, scope, L)
go('申万一级 不用E6 [any] 1x（对照）', l1, 'any', 1.0, e6=False)
rng = np.random.default_rng(5); res = []
for k in range(20):
    p = l1.copy(); m = np.nonzero(l1 >= 0)[0]; p[m] = l1[rng.permutation(m)]
    cfg = DipConfig(leverage=1.0); fm, fc, _ = inputs(panel, cfg, p, 'any'); fc = Candidates(uni=fc.uni, e6=fc.e6 & cand.e6, buyok=fc.buyok, ret20=fc.ret20)
    r = simulate(panel, fm, fc, cfg); st = summarize(panel, fm, r, cfg)['stats']; res.append((st['cagr'], st['sharpe']))
a = np.array(res); print(f'打乱20次 + E6 [any] 1x: 年化均{a[:,0].mean()*100:+.1f}% [{a[:,0].min()*100:+.1f},{a[:,0].max()*100:+.1f}] 夏普均{a[:,1].mean():+.2f}')
