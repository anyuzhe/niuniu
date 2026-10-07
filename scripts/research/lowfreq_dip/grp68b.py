"""grp68b: D / D2 闲置资金放宽基 ETF（沪深300 / 中证500 / 中证1000，各自可带 200 日线开关），逐年与落后段对比。"""
import os, sys, json
import numpy as np, pandas as pd
NAV = os.path.expanduser('~/mnt/lake/bronze/provider=eastmoney/etf_nav/')
Z = {v: np.load(f'grp68_{v}.npz') for v in ('D', 'D2')}
dates = Z['D']['dates'].astype(str); nd = len(dates); di = {d: i for i, d in enumerate(dates)}; yr = np.array([int(d[:4]) for d in dates])
def ret(sym):
    x = pd.read_parquet(NAV + sym + '.parquet', columns=['date', 'acc_nav']); x['date'] = x['date'].astype(str); x = x[x.date.isin(di)]
    a = np.full(nd, np.nan); a[x.date.map(di).to_numpy()] = x.acc_nav.to_numpy(); a = pd.Series(a).ffill().to_numpy()
    r = np.full(nd, np.nan); r[1:] = a[1:] / a[:-1] - 1
    first = int(np.nonzero(np.isfinite(a))[0][0]); r[:first + 1] = np.nan
    r[np.abs(r) > 0.12] = 0.0; return r
CY = 0.02 / 245; COST = 0.0005
def trend(r, L=200):
    idx = np.cumprod(1 + np.nan_to_num(r)); ma = pd.Series(idx).rolling(L, min_periods=L).mean().to_numpy()
    pos = np.r_[0.0, (idx[:-1] > ma[:-1]).astype(float)]; pos[~np.isfinite(np.r_[np.nan, ma[:-1]])] = 0.0
    out = pos * np.nan_to_num(r) + (1 - pos) * CY - COST * np.abs(np.diff(np.r_[0.0, pos]))
    out[~np.isfinite(r)] = np.nan; return out
raw = {'沪深300': ret('sh_510300'), '中证500': ret('sh_510500'), '中证1000': ret('sh_512100')}
S = {}
for k, r in raw.items():
    S[k + ' 一直持有'] = r; S[k + ' +200日线'] = trend(r)
S['三者等权 +200日线'] = (trend(raw['沪深300']) + trend(raw['中证500']) + trend(raw['中证1000'])) / 3
S['沪深300+中证500 +200日线'] = (trend(raw['沪深300']) + trend(raw['中证500'])) / 2
def stat(x):
    cum = np.cumprod(1 + x); n = len(x); cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    return cagr, sh, dd
out = {}
def window(V, name, start, keys):
    r, ex = Z[V]['r'], Z[V]['ex']; idle = 1 - np.r_[0, ex[:-1]]
    v = np.isfinite(r) & np.isfinite(ex) & (np.arange(nd) >= int(np.searchsorted(dates, start)))
    for k in keys: v &= np.isfinite(S[k])
    cols = {f'{V} 单独（闲置2%）': r + idle * CY}
    for k in keys:
        cols[f'{V} + {k}'] = r + idle * np.nan_to_num(S[k]) - COST * np.abs(np.diff(np.r_[0, idle])) + 0
    # 注：与 §96 同口径，ETF 仓位 = 闲置资金，随 D 的仓位每天调整，单边 5bp
    for k in keys:
        a = idle; da = np.abs(np.diff(np.r_[0, a])); cols[f'{V} + {k}'] = r + a * np.nan_to_num(S[k]) - COST * da
    print(f'\n===== {V} 窗口：{name}  {dates[np.nonzero(v)[0][0]]} ~ {dates[np.nonzero(v)[0][-1]]}（{int(v.sum())} 天）', flush=True)
    res = {}
    for lab, x in cols.items():
        c, s, d = stat(x[v]); res[lab] = x
        print(f'  {lab:34s} 年化{c*100:+6.1f}% 夏普{s:5.2f} 回撤{d*100:5.0f}%', flush=True)
    for k in keys:
        c, s, d = stat(S[k][v]); print(f'  [纯持有] {k:26s} 年化{c*100:+6.1f}% 夏普{s:5.2f} 回撤{d*100:5.0f}%')
    return v, res
W1 = ['沪深300 +200日线', '中证500 +200日线', '沪深300+中证500 +200日线', '沪深300 一直持有']
W2 = ['沪深300 +200日线', '中证500 +200日线', '中证1000 +200日线', '三者等权 +200日线', '中证1000 一直持有']
allres = {}
for V in ('D', 'D2'):
    allres[(V, 1)] = window(V, '2013-02 起（有中证500）', '2013-02-06', W1)
    allres[(V, 2)] = window(V, '2017 年中起（有中证1000，200 日线算满）', '2016-09-29', W2)
def yearly(V, w, keys):
    v, res = allres[(V, w)]
    labs = [f'{V} 单独（闲置2%）'] + [f'{V} + {k}' for k in keys]
    print(f'\n===== 逐年（%）{V}  窗口{w}', flush=True)
    print('年份 ' + ' '.join(f'{l.replace(V + " ", "")[:16]:>16s}' for l in labs))
    tbl = {}
    for y in range(2012, 2027):
        m = (yr == y) & v
        if m.sum() < 5: continue
        row = [(np.prod(1 + res[l][m]) - 1) * 100 for l in labs]; tbl[y] = row
        print(f'{y} ' + ' '.join(f'{x:+16.1f}' for x in row))
    out[f'{V}_{w}'] = dict(labels=labs, table={str(k): v_ for k, v_ in tbl.items()})
yearly('D2', 1, ['沪深300 +200日线', '中证500 +200日线', '沪深300+中证500 +200日线'])
yearly('D2', 2, ['沪深300 +200日线', '中证500 +200日线', '中证1000 +200日线', '三者等权 +200日线'])
# 落后段
SEG = [('D 2013-11-29~2015-06-30', 'D', 1, '2013-11-29', '2015-06-30'), ('D2 2013-11-29~2015-01-06', 'D2', 1, '2013-11-29', '2015-01-06'),
       ('D2 2025-04-21~2025-12-19', 'D2', 1, '2025-04-21', '2025-12-19')]
print('\n===== 落后段：同一段里 D / D2 单独 与 叠加 ETF 的区间收益（%）')
for lab, V, w, a, b in SEG:
    v, res = allres[(V, w)]
    m = np.zeros(nd, bool); m[int(np.searchsorted(dates, a)) + 1:int(np.searchsorted(dates, b)) + 1] = True
    print(lab, flush=True)
    for l, x in res.items():
        mm = m & np.isfinite(x)
        if mm.sum() > 0.9 * m.sum(): print(f'  {l:34s} {(np.prod(1 + x[mm]) - 1) * 100:+7.1f}')
    for k, s in S.items():
        mm = m & np.isfinite(s)
        if mm.sum() > 0.9 * m.sum() and ('一直' in k): print(f'  [纯持有] {k:26s} {(np.prod(1 + s[mm]) - 1) * 100:+7.1f}')
json.dump(out, open('grp68.json', 'w'), ensure_ascii=False, indent=1)
