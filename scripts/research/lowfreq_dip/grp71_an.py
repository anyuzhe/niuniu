import json, os, sys, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np, pandas as pd
T = json.load(open('grp71_trades.json')); R = json.load(open('grp71_indlevel.json'))
BAD = ['国防军工', '环保', '煤炭', '基础化工', '家用电器', '美容护理']; GOOD = ['计算机', '医药生物', '有色金属', '公用事业', '食品饮料', '农林牧渔', '电子', '银行']
order = ['差(6)', '房地产', '其余', '好(8)']
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40); pd.set_option('display.float_format', lambda x: f'{x:.3f}')
FE = ['r20', 'r60', 'r120', 'r250', 'dd250', 'vol60', 'ladv', 'price', 'z_ind', 'r20_ind', 'n_ind', 'chronic', 'r120_ind', 'r250_ind', 'mkt_gap120', 'mkt_z']
for V in ('D', 'D2'):
    df = pd.DataFrame(T[V]); print(f'\n########## {V}  B 层成交 {len(df)} 笔')
    print('--- 各组触发时的特征（中位数）；ret=单笔净收益均值')
    g = df.groupby('grp')[FE].median().reindex(order); g['n'] = df.groupby('grp').size().reindex(order); g['ret均值%'] = df.groupby('grp')['ret'].mean().reindex(order) * 100
    g['mae中位%'] = df.groupby('grp')['mae'].median().reindex(order) * 100; g['r5中位%'] = df.groupby('grp')['r5'].median().reindex(order) * 100; g['r10中位%'] = df.groupby('grp')['r10'].median().reindex(order) * 100
    print(g.T.to_string())
    print('--- 特征与单笔收益的秩相关（全部 B 层成交）')
    cor = {k: df[k].rank().corr(df['ret'].rank()) for k in FE if df[k].notna().sum() > 100}
    print('  ' + '  '.join(f'{k}:{v:+.2f}' for k, v in sorted(cor.items(), key=lambda kv: kv[1])))
# 行业整体视角
d = pd.DataFrame(R); d['grp'] = d.ind.map(lambda n: '差(6)' if n in BAD else '房地产' if n == '房地产' else '好(8)' if n in GOOD else '其余')
print('\n########## 行业整体视角：全部触发日，该行业全部可交易成员的 20 日前向收益均值（不受名额限制）', len(d), '个行业-触发日')
print('总体', f'{d.fwd.mean()*100:+.2f}%', ' 各组:', {k: f'{d[d.grp==k].fwd.mean()*100:+.2f}% (n={int((d.grp==k).sum())})' for k in order})
# 按段
def episodes(x):
    x = x.sort_values('t'); seg = (x.t.diff().fillna(99) > 25).cumsum(); return x.groupby(seg).agg(date=('date', 'first'), fwd=('fwd', 'mean'), r120=('r120_ind', 'mean'), z=('z', 'min'), gap=('gap120', 'mean'), days=('t', 'size'))
ep = pd.concat({k: episodes(v) for k, v in d.groupby('ind')}).reset_index(level=0).rename(columns={'level_0': 'ind'}); ep['grp'] = ep.ind.map(lambda n: '差(6)' if n in BAD else '房地产' if n == '房地产' else '好(8)' if n in GOOD else '其余')
tab = ep.groupby('ind').agg(段数=('fwd', 'size'), 按段前向=('fwd', 'mean'), 前期120日涨跌=('r120', 'mean'), 最深z=('z', 'mean'), 触发日数=('days', 'sum'), 触发时大盘离高点=('gap', 'mean')).sort_values('按段前向')
tab['按段前向'] *= 100; tab['前期120日涨跌'] *= 100; tab['触发时大盘离高点'] *= 100
print(tab.to_string())
print('\n各组（按段）：')
G = ep.groupby('grp').agg(段数=('fwd', 'size'), 前向=('fwd', 'mean'), 前期120日涨跌=('r120', 'mean'), 最深z=('z', 'mean'), 持续天数=('days', 'mean'), 大盘离高点=('gap', 'mean')).reindex(order)
for k in ('前向', '前期120日涨跌', '大盘离高点'): G[k] *= 100
print(G.to_string())
print('\n--- 触发前行业 120 日趋势分档 → 触发日行业前向收益（行业-触发日）')
d['q'] = pd.qcut(d.r120_ind, 5, labels=['最差五分之一', '较差', '中间', '较好', '最好五分之一'])
print((d.groupby('q', observed=True).agg(n=('fwd', 'size'), 前向=('fwd', 'mean'), 触发深度z=('z', 'mean'), 大盘离高点=('gap120', 'mean'), r120均值=('r120_ind', 'mean')) * [1, 100, 1, 100, 100]).to_string())
print('\n--- 同样分档下，各组的构成（差(6) 的触发日有多少落在“前期趋势最差”的两档）')
print(pd.crosstab(d.grp, d.q, normalize='index').reindex(order).to_string())
# 行业静态特征
import pickle
from quantlab.dipbuy import industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
labels = np.asarray(cls.labels); names = cls.names
c = panel.c.astype(np.float32); r = np.full(c.shape, np.nan, np.float32); r[1:] = c[1:] / c[:-1] - 1; r[np.abs(r) > 0.25] = np.nan
inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb')); mk = np.nan_to_num(inp.market.mret)
rows = []
for gi, n in enumerate(names):
    cols = np.nonzero(labels == gi)[0]
    if len(cols) < 8: continue
    ew = np.nanmean(r[:, cols], axis=0 if False else 1); ok = np.isfinite(ew) & (np.arange(len(ew)) > 250)
    beta = np.cov(ew[ok], mk[ok])[0, 1] / np.var(mk[ok]); vol = np.nanstd(ew[ok]) * np.sqrt(245) * 100
    idv = np.nanmean(np.nanstd(r[250:, cols], axis=0)) * np.sqrt(245) * 100       # 成员个股平均年化波动
    disp = np.nanmean(np.nanstd(r[250:, cols], axis=1)) * 100                      # 成员间日收益离散度（%）
    rows.append(dict(ind=n, 成员数=len(cols), 行业指数波动=vol, beta=beta, 个股平均波动=idv, 成员间日离散度=disp, 与大盘相关=np.corrcoef(ew[ok], mk[ok])[0, 1]))
S = pd.DataFrame(rows).set_index('ind'); S['grp'] = [('差(6)' if n in BAD else '房地产' if n == '房地产' else '好(8)' if n in GOOD else '其余') for n in S.index]
print('\n########## 行业静态特征（全时期）各组中位数')
print(S.groupby('grp').median(numeric_only=True).reindex(order).to_string())
print(S.loc[BAD + ['房地产']].to_string())
S.to_json('grp71_static.json', force_ascii=False)
