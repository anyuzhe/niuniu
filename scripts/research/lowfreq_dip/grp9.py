"""Turnover-quintile panic anatomy: which quintile triggers, by year, trade attribution, overlap with market panic. Research only."""
import time
from grp_lib import *
panel = load_panel(); nd, nc = panel.shape
market, cand = compute_features(panel, 5e7, 3.0); uni = cand.uni
a = np.nan_to_num(panel.a, nan=0.0).astype(np.float64); cs = np.cumsum(a, 0); amt60 = np.full((nd, nc), np.nan, np.float32); amt60[60:] = ((cs[60:] - cs[:-60]) / 60).astype(np.float32); del a, cs
lab = np.full((nd, nc), -1, np.int8)
for s0 in range(0, nd, 400):
    b = min(nd, s0 + 400); v = np.where(uni[s0:b] & np.isfinite(amt60[s0:b]), amt60[s0:b], np.nan)
    pct = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
    lab[s0:b] = np.where(np.isfinite(pct), np.minimum(np.nan_to_num(pct * 5).astype(np.int16), 4), -1).astype(np.int8)
cfg = DipConfig(leverage=1.0)
z, r20, cnt = group_z(panel, cand, lab)
trig = np.isfinite(z) & (z <= -1.5)
dates = np.array(panel.dates); yr = np.array([int(d[:4]) for d in dates])
mk = np.isfinite(market.z) & (market.z <= -1.5)
print('=== 各档触发天数（z<=-1.5）；档1=成交额最小…档5=最大', flush=True)
print('档', [int(trig[:, q].sum()) for q in range(5)], ' 任一档', int(trig.any(1).sum()), ' 同日大盘恐慌', int((trig.any(1) & mk).sum()), ' 大盘没恐慌', int((trig.any(1) & ~mk).sum()))
print('同时触发的档数分布', {k: int(v) for k, v in zip(*np.unique(trig.sum(1)[trig.any(1)], return_counts=True))})
print('=== 按年：任一档触发天数 | 各档天数 | 大盘恐慌天数', flush=True)
for y in range(2008, 2027):
    m = yr == y
    print(y, int(trig[m].any(1).sum()), [int(trig[m][:, q].sum()) for q in range(5)], int(mk[m].sum()))
fm, fc, _ = inputs(panel, cfg, lab, 'any')
raw = simulate(panel, fm, fc, cfg); s = summarize(panel, fm, raw, cfg); print('总体', {k: round(v, 3) for k, v in s['stats'].items()}, 'trades', s['trades']['n'])
trades = raw['trades']; print('trade keys', list(trades[0].keys()))
code_ix = {str(c): i for i, c in enumerate(panel.codes)}; didx = {d: i for i, d in enumerate(dates)}
rows = []
for t in trades:
    sd = t.get('signal'); j = code_ix[t['code']]; i = didx[sd]
    rows.append((sd[:4], int(lab[i, j]), t['ret'], bool(mk[i]), int(trig[i].sum())))
T = pd.DataFrame(rows, columns=['year', 'q', 'ret', 'mkpanic', 'ntrig'])
print('=== 交易按所属档（信号日）', flush=True)
g = T.groupby('q')['ret'].agg(['count', 'mean', lambda x: (x > 0).mean()]); g.columns = ['笔数', '笔均', '胜率']; g['笔均bp'] = (g['笔均'] * 1e4).round(0); print(g[['笔数', '笔均bp', '胜率']].round(3).to_string())
print('=== 交易按是否大盘恐慌日', flush=True)
g = T.groupby('mkpanic')['ret'].agg(['count', 'mean']); g['bp'] = (g['mean'] * 1e4).round(0); print(g[['count', 'bp']].to_string())
print('=== 逐年策略收益（1x）与交易笔数', flush=True)
eq = raw['eq']
for y in range(2008, 2027):
    ii = np.nonzero((yr == y) & np.isfinite(eq))[0]
    if len(ii) > 20:
        print(y, f'{(eq[ii[-1]] / eq[ii[0]] - 1) * 100:+5.1f}%', f'笔数{int((T.year == str(y)).sum())}', f'笔均{T[T.year == str(y)].ret.mean() * 1e4 if (T.year == str(y)).any() else 0:+.0f}bp')
print('=== 只看大盘没恐慌的日子里，各档触发时的平均大盘 z', round(float(market.z[trig.any(1) & ~mk].mean()), 2), ' 全部日平均', round(float(np.nanmean(market.z)), 2))
# overlap with original strategy days
print('原策略(大盘z<=-1.5)天数', int(mk.sum()), '其中也有档触发', int((trig.any(1) & mk).sum()))
