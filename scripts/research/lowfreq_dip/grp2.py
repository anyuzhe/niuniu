"""Permutation null for group panic: shuffle the group labels across stocks (same group-size distribution), 30 draws each. Research only."""
import json, time
from grp_lib import *
T0 = time.time()
panel = load_panel(); nc = panel.shape[1]; codes = panel.codes; sym = np.array([str(c).split('.')[-1] for c in codes])
D = pd.read_parquet(f'{LAKE}/bronze/provider=swsresearch/industry_classification_history/2026-09-23.parquet')
D = D.sort_values(['code', 'start_date']).groupby('code').tail(1).set_index('code')
def lab_from(m):
    raw = np.array([m.get(s, '') for s in sym]); u = sorted(set(raw) - {''}); ix = {k: i for i, k in enumerate(u)}
    return np.array([ix.get(x, -1) for x in raw], np.int16)
B = pd.read_parquet(f'{LAKE}/bronze/provider=baostock/industry/industry.parquet')
B = B[B['industry'].astype(str).str.len() > 0].drop_duplicates('code', keep='last').set_index('code')['industry'].astype(str)
bm = dict(zip([c.split('.')[-1] for c in B.index], B.values))
board = np.array([0 if str(c).startswith('sh.688') else 1 if str(c).startswith('sz.30') else 2 if str(c).startswith('sh.6') else 3 if str(c).startswith('sz.0') else -1 for c in codes], np.int16)
ALL = [('申万一级', lab_from(D['l1_code'].to_dict())), ('申万二级', lab_from(D['l2_code'].to_dict())),
        ('证监会门类', lab_from({k: v[0] for k, v in bm.items()})), ('证监会大类', lab_from({k: v[:3] for k, v in bm.items()})),
        ('板块4类', board)]
ONLY = os.environ.get('ONLY', '').split(',') if os.environ.get('ONLY') else None
sets = [x for x in ALL if ONLY is None or x[0] in ONLY]
NP = int(os.environ.get('NPERM', 30))
res = {}
for name, lab in sets:
    real = {s: run(panel, f'{name} 真实 {s}', lab, s, quiet=True) for s in ('any', 'idio')}
    for s in ('any', 'idio'):
        rng = np.random.default_rng(5)
        perm = []
        for k in range(NP):
            p = lab.copy(); m = np.nonzero(lab >= 0)[0]; p[m] = lab[rng.permutation(m)]
            perm.append(run(panel, 'p', p, s, quiet=True))
        cg = np.array([x['cagr'] for x in perm]); sh = np.array([x['sharpe'] for x in perm]); dd = np.array([x['mdd'] for x in perm])
        r = real[s]
        print(f"{name:10s} {s:4s} 真实: 年化{r['cagr']*100:+5.1f}% 夏普{r['sharpe']:+.2f} 回撤{r['mdd']*100:4.0f}% 触发{r['gate_days']}天 | "
              f"打乱{NP}次: 年化 均值{cg.mean()*100:+5.1f}% sd{cg.std()*100:.1f} [{cg.min()*100:+.1f},{cg.max()*100:+.1f}] 夏普均{sh.mean():+.2f} 回撤均{dd.mean()*100:.0f}% 触发均{np.mean([x['gate_days'] for x in perm]):.0f}天 | "
              f"真实年化排名: 比{(cg < r['cagr']).mean()*100:.0f}%的打乱更高; 夏普比{(sh < r['sharpe']).mean()*100:.0f}%更高", flush=True)
        res[f'{name}-{s}'] = dict(real=r, perm_cagr=cg.tolist(), perm_sharpe=sh.tolist())
json.dump(res, open('grp2_' + os.environ.get('TAG', 'all') + '.json', 'w'), ensure_ascii=False)
# market-weakness controls: no groups, pool = all tradable, gate on the market z only
print('--- 大盘偏弱对照（不分组，候选=全市场可交易，按20日跌幅取20只，1x；闸门=大盘z）', flush=True)
market, cand = compute_features(panel, 5e7, 3.0)
for lo, hi in ((-9, -1.5), (-9, -1.0), (-9, -0.5), (-1.5, -1.0), (-1.5, -0.5), (-1.0, -0.5)):
    g = np.isfinite(market.z) & (market.z > lo) & (market.z <= hi)
    fm = Market(mret=market.mret, mk20=market.mk20, z=np.where(g, -9.0, 9.0), count=market.count)
    fc = Candidates(uni=cand.uni, e6=cand.uni & np.isfinite(cand.ret20), buyok=cand.buyok, ret20=cand.ret20)
    cfg = DipConfig(leverage=1.0)
    raw = simulate(panel, fm, fc, cfg); s = summarize(panel, fm, raw, cfg); st = s['stats']; tr = s['trades']; h = halves(panel, raw['eq'])
    print(f"大盘z in ({lo},{hi}] 触发{int(g.sum()):5d}天 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:+.2f} 回撤{st['max_drawdown']*100:4.0f}% 仓位{st['exposure']*100:3.0f}% 笔{tr['n']} 笔均{tr['mean']*1e4:+.0f}bp | 前半{h[0]} 后半{h[1]}", flush=True)
print('done', round(time.time() - T0), 's')
