"""Step 2 (research only): idle capital of D (with-delisted panel) held in ETFs; includes costs, buy&hold comparisons, by-year table."""
import os, numpy as np, pandas as pd
import sys
VAR = sys.argv[1] if len(sys.argv) > 1 else 'D'
Z = np.load('grp57_D.npz', allow_pickle=True); rD, ex, dates = Z['r' + VAR], Z['ex' + VAR], Z['dates'].astype(str)
print('######## 策略', VAR)
nd = len(dates); di = {d: i for i, d in enumerate(dates)}; yr = np.array([int(d[:4]) for d in dates])
NAV = os.path.expanduser('~/mnt/lake/bronze/provider=eastmoney/etf_nav/')
def ret(sym):
    x = pd.read_parquet(NAV + sym.replace('.', '_') + '.parquet', columns=['date', 'acc_nav']); x['date'] = x['date'].astype(str); x = x[x.date.isin(di)]
    a = np.full(nd, np.nan); a[x.date.map(di).to_numpy()] = x.acc_nav.to_numpy(); a = pd.Series(a).ffill().to_numpy()
    r = np.full(nd, np.nan); r[1:] = a[1:] / a[:-1] - 1
    first = int(np.nonzero(np.isfinite(a))[0][0]); r[:first + 1] = np.nan
    r[np.abs(r) > 0.12] = 0.0; return r
CY = 0.02 / 245; COST = 0.0005
R = {k: ret(v) for k, v in {'HS300': 'sh.510300', 'ZZ500': 'sh.510500', 'GOLD': 'sh.518880', 'BOND': 'sh.511260'}.items()}
def trend(r, L=200):
    idx = np.cumprod(1 + np.nan_to_num(r)); ma = pd.Series(idx).rolling(L, min_periods=L).mean().to_numpy()
    pos = np.r_[0.0, (idx[:-1] > ma[:-1]).astype(float)]; pos[~np.isfinite(np.r_[np.nan, ma[:-1]])] = 0.0
    out = pos * np.nan_to_num(r) + (1 - pos) * CY - COST * np.abs(np.diff(np.r_[0.0, pos]))
    out[~np.isfinite(r)] = np.nan; return out
S = {'沪深300': R['HS300'], '沪深300 趋势(MA200)': trend(R['HS300']), '中证500': R['ZZ500'], '黄金': R['GOLD'], '十年国债': R['BOND'],
     '沪深300/黄金/国债 各1/3': (R['HS300'] + R['GOLD'] + R['BOND']) / 3, '趋势沪深300/黄金/国债 各1/3': (trend(R['HS300']) + R['GOLD'] + R['BOND']) / 3,
     '沪深300+黄金 各1/2': (R['HS300'] + R['GOLD']) / 2}
idle = 1 - np.r_[0, ex[:-1]]
def combo(s, k=1.0):
    a = k * idle; da = np.abs(np.diff(np.r_[0, a])); return rD + a * np.nan_to_num(s) - COST * da + (idle - a) * CY
def stat(r, v, label, show=True):
    x = r[v]; cum = np.cumprod(1 + x); n = len(x); cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    if show: print(f'{label:46s} 年化{cagr*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% 卡玛{cagr/abs(dd):4.2f}', flush=True)
    return cagr, sh, dd
base = np.isfinite(rD) & np.isfinite(ex)
print('校验 D 含退市 闲置2%（2008 起，应约 +15.9% / 0.77 / -42%）')
stat(rD + idle * CY, base, 'D 单独（2008 起）')
def window(name, keys, start):
    v = base & np.all([np.isfinite(S[k]) for k in keys], 0) & (np.arange(nd) >= int(np.searchsorted(dates, start)))
    print(f'\n===== {name}：{dates[np.nonzero(v)[0][0]]} ~ {dates[np.nonzero(v)[0][-1]]}（{v.sum()} 天）', flush=True)
    res = {}
    res['D 单独（闲置2%）'] = (rD + idle * CY, stat(rD + idle * CY, v, 'D 单独（闲置2%）'))
    for k in keys:
        cor = np.corrcoef(rD[v], S[k][v])[0, 1]
        res['[持有] ' + k] = (S[k], stat(S[k], v, f'[纯持有] {k}（与D相关{cor:+.2f}）'))
        c = combo(S[k]); res['D+' + k] = (c, stat(c, v, f'D + 闲置放 {k}'))
    return v, res
v1, r1 = window('窗口一（沪深300 起）', ['沪深300', '沪深300 趋势(MA200)', '中证500'], '2012-05-07')
v2, r2 = window('窗口二（黄金起）', ['沪深300', '黄金', '沪深300+黄金 各1/2'], '2013-07-19')
v3, r3 = window('窗口三（国债起）', ['沪深300', '沪深300 趋势(MA200)', '十年国债', '沪深300/黄金/国债 各1/3', '趋势沪深300/黄金/国债 各1/3'], '2017-08-07')
print('\n===== 逐年（%）窗口一：D 单独 / 纯持有沪深300 / D+沪深300 / D+沪深300趋势')
dcol = r1['D 单独（闲置2%）'][0]; hs = r1['[持有] 沪深300'][0]; dh = r1['D+沪深300'][0]; dt = r1['D+沪深300 趋势(MA200)'][0]
for y in range(2012, 2027):
    m = (yr == y) & v1
    if not m.any(): continue
    f = lambda r: (np.prod(1 + r[m]) - 1) * 100
    print(f'{y}  D {f(dcol):+6.1f}  持有沪深300 {f(hs):+6.1f}  D+沪深300 {f(dh):+6.1f}  D+沪深300趋势 {f(dt):+6.1f}')
print('\n===== 最大回撤出现的区间（窗口一）')
for lab, r in (('D 单独', dcol), ('纯持有沪深300', hs), ('D+沪深300', dh), ('D+沪深300趋势', dt)):
    idx = np.nonzero(v1)[0]; cum = np.cumprod(1 + r[idx]); peak = np.maximum.accumulate(cum); dd = cum / peak - 1; j = dd.argmin(); i0 = cum[:j + 1].argmax()
    print(f'{lab:16s} {dates[idx[i0]]} → {dates[idx[j]]}  {dd[j]*100:.0f}%')
print('\n===== D 买股票时 ETF 同时在亏钱吗：D 仓位>30% 的日子里，沪深300 的平均日收益（bp）与全部日子对比')
hi = v1 & (np.r_[0, ex[:-1]] > 0.3)
print(f'D 仓位>30% 的日子 {hi.sum()} 天：沪深300 日均 {np.nanmean(R["HS300"][hi])*1e4:+.1f}bp；全部 {np.nanmean(R["HS300"][v1])*1e4:+.1f}bp；D 日均 {np.nanmean(rD[hi])*1e4:+.1f}bp')
