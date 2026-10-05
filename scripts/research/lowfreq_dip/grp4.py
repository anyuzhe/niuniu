"""Unions of group-panic signals (SW L1, liquidity quintile, board, PB quintile) + impact-cost sensitivity + leverage. Research only."""
import json, time
from grp_lib import *
T0 = time.time()
panel = load_panel(); nd, nc = panel.shape; codes = [str(c) for c in panel.codes]; sym = np.array([c.split('.')[-1] for c in codes])
market, cand = compute_features(panel, 5e7, 3.0); uni = cand.uni
D = pd.read_parquet(f'{LAKE}/bronze/provider=swsresearch/industry_classification_history/2026-09-23.parquet')
D = D.sort_values(['code', 'start_date']).groupby('code').tail(1).set_index('code')['l1_code'].to_dict()
raw = np.array([D.get(s, '') for s in sym]); u = sorted(set(raw) - {''}); ix = {k: i for i, k in enumerate(u)}
l1 = np.array([ix.get(x, -1) for x in raw], np.int16)
board = np.array([0 if c.startswith('sh.688') else 1 if c.startswith('sz.30') else 2 if c.startswith('sh.6') else 3 if c.startswith('sz.0') else -1 for c in codes], np.int16)
def quintiles(x, nq=5):
    out = np.full((nd, nc), -1, np.int8)
    for a in range(0, nd, 400):
        b = min(nd, a + 400); v = np.where(uni[a:b] & np.isfinite(x[a:b]), x[a:b], np.nan)
        pct = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
        out[a:b] = np.where(np.isfinite(pct), np.minimum((pct * nq).astype(np.int16), nq - 1), -1).astype(np.int8)
    return out
a = np.nan_to_num(panel.a, nan=0.0).astype(np.float64); cs = np.cumsum(a, 0); amt60 = np.full((nd, nc), np.nan, np.float32); amt60[60:] = ((cs[60:] - cs[:-60]) / 60).astype(np.float32); del a, cs
liq = quintiles(amt60); del amt60
dates = np.array(panel.dates); pb = np.full((nd, nc), np.nan, np.float32)
for j, code in enumerate(codes):
    fv = f'{LAKE}/bronze/provider=baostock/valuation_daily_v1/{code.replace(".", "_")}.parquet'
    if os.path.exists(fv):
        V = pd.read_parquet(fv, columns=['date', 'pbMRQ']); d = V['date'].values.astype('U10'); i = np.searchsorted(dates, d)
        ok = i < nd; ok[ok] &= dates[i[ok]] == d[ok]; pb[i[ok], j] = pd.to_numeric(V['pbMRQ'], errors='coerce').values[ok]
pbq = quintiles(np.where(pb > 0, pb, np.nan).astype(np.float32)); del pb
print('features ready', round(time.time() - T0), 's', flush=True)
LAB = {'申万一级': l1, '成交额五分位': liq, '板块': board, 'PB五分位': pbq}
def combo(names, scope, cfg):
    parts = [inputs(panel, cfg, LAB[n], scope) for n in names]
    z = np.where(np.isfinite(parts[0][0].z), parts[0][0].z, np.inf)
    pool = parts[0][1].e6.copy()
    for fm, fc, _ in parts[1:]:
        z = np.minimum(z, np.where(np.isfinite(fm.z), fm.z, np.inf)); pool |= fc.e6
    z = np.where(np.isfinite(z), z, np.nan)
    return Market(mret=market.mret, mk20=market.mk20, z=z, count=market.count), Candidates(uni=uni, e6=pool, buyok=cand.buyok, ret20=cand.ret20)
def report(label, names, scope, **kw):
    cfg = replace(DipConfig(leverage=1.0), **kw)
    fm, fc = combo(names, scope, cfg)
    raw_ = simulate(panel, fm, fc, cfg); s = summarize(panel, fm, raw_, cfg); st = s['stats']; tr = s['trades']; h = halves(panel, raw_['eq']); i = s['info']
    mr = i['min_margin_ratio']
    print(f"{label:52s} 触发{s['gate_days']:5d}天 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:+.2f} 回撤{st['max_drawdown']*100:4.0f}% 仓位{st['exposure']*100:3.0f}% 笔{tr['n']:5d} 笔均{tr['mean']*1e4:+4.0f}bp"
          f"{'' if mr is None else f' 最低担保{mr*100:.0f}%'} | 前半{h[0]} 后半{h[1]}", flush=True)
    return dict(label=label, cagr=st['cagr'], sharpe=st['sharpe'], mdd=st['max_drawdown'], expo=st['exposure'], n=tr['n'])
out = []
for names in (['申万一级'], ['成交额五分位'], ['板块'], ['PB五分位'], ['申万一级', '成交额五分位'], ['申万一级', '成交额五分位', '板块'], ['申万一级', '成交额五分位', '板块', 'PB五分位']):
    for scope in ('any', 'idio'):
        out.append(report('+'.join(names) + f' [{scope}]', names, scope))
print('--- 冲击成本敏感性（每边额外基点），任一触发', flush=True)
for names in (['申万一级'], ['成交额五分位'], ['申万一级', '成交额五分位'], ['申万一级', '成交额五分位', '板块', 'PB五分位']):
    for bp in (10, 20):
        out.append(report('+'.join(names) + f' 冲击{bp}bp/边', names, 'any', slippage_bp=float(bp)))
print('--- 杠杆（并集：申万一级+成交额五分位）', flush=True)
for L in (1.5, 2.0):
    out.append(report(f'申万一级+成交额五分位 {L}x', ['申万一级', '成交额五分位'], 'any', leverage=L))
json.dump(out, open('grp4.json', 'w'), ensure_ascii=False)
print('done', round(time.time() - T0), 's')
