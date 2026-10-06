"""Idle-cash overlay of D with low-correlation ETFs (gold, Nasdaq, 10y bond, CSI300, money ETF). Research only. Uses grp30_streams.npz (rD, ex)."""
import os, numpy as np, pandas as pd
Z = np.load('grp30_streams.npz'); rD, ex = Z['rD'], Z['ex']
dates = np.load('panel_ext.npz', allow_pickle=True)['dates'].astype(str); nd = len(dates); di = {d: i for i, d in enumerate(dates)}
B = os.path.expanduser('~/mnt/lake/bronze/provider=tdx/etf_kline_daily/')
def etf(sym):
    x = pd.read_parquet(B + sym.replace('.', '_') + '.parquet', columns=['date', 'close']); x['date'] = x['date'].astype(str)
    c = np.full(nd, np.nan)
    for d, v in zip(x['date'], x['close']):
        if d in di: c[di[d]] = v
    # forward-fill gaps (suspensions) then daily returns
    c = pd.Series(c).ffill().to_numpy(); r = np.full(nd, np.nan); r[1:] = c[1:] / c[:-1] - 1; return r
ETF = {'黄金 518880': 'sh.518880', '纳指 159941': 'sz.159941', '十年国债 511260': 'sh.511260', '沪深300 510300': 'sh.510300', '中证500 510500': 'sh.510500', '银华日利（货基）511880': 'sh.511880', '城投债 511220': 'sh.511220'}
R = {k: etf(v) for k, v in ETF.items()}
CY = 0.02 / 245; COST = 0.0005
def stat(r, valid, label):
    x = r[valid]; cum = np.cumprod(1 + x); n = len(x); cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    print(f'{label:46s} 年化{cagr*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% 卡玛{cagr/abs(dd):4.2f}', flush=True); return cagr, sh, dd
idle = 1 - np.r_[0, ex[:-1]]
def combo(s, k):
    a = k * idle; da = np.abs(np.diff(np.r_[0, a])); return rD + a * np.nan_to_num(s) - COST * da + (idle - a) * CY
def window(label, series):
    valid = np.isfinite(rD) & np.all([np.isfinite(s) for s in series], 0) & np.isfinite(ex)
    print(f'=== {label}：{dates[np.nonzero(valid)[0][0]]} ~ {dates[np.nonzero(valid)[0][-1]]}', flush=True)
    stat(rD + idle * CY, valid, 'D 单独（闲置 2%）')
    return valid
for name, s in R.items():
    v = window(name, [s]); cor = np.corrcoef(rD[v], s[v])[0, 1]; stat(s, v, f'[单独] {name}（与 D 相关 {cor:+.2f}）')
    for k in (0.5, 1.0): stat(combo(s, k), v, f'D + {name} k={k:g}')
mix = (R['黄金 518880'] + R['纳指 159941'] + R['十年国债 511260']) / 3
v = window('黄金 / 纳指 / 十年国债 各 1/3（每日再平衡）', [mix]); cor = np.corrcoef(rD[v], mix[v])[0, 1]; stat(mix, v, f'[单独] 三资产混合（与 D 相关 {cor:+.2f}）')
for k in (0.5, 1.0): stat(combo(mix, k), v, f'D + 三资产混合 k={k:g}')
mix2 = (R['黄金 518880'] + R['十年国债 511260']) / 2
v = window('黄金 / 十年国债 各 1/2', [mix2]); cor = np.corrcoef(rD[v], mix2[v])[0, 1]; stat(mix2, v, f'[单独]（与 D 相关 {cor:+.2f}）')
for k in (0.5, 1.0): stat(combo(mix2, k), v, f'D + 黄金/国债 k={k:g}')
print('=== 逐年（%）：黄金 518880 自身 / D 单独 / D+黄金 k=1 / D+黄金·国债 k=1（2018 起）')
yr = np.array([int(d[:4]) for d in dates]); g_ = R['黄金 518880']
for y in range(2014, 2027):
    m = (yr == y) & np.isfinite(rD)
    f = lambda r: (np.prod(1 + r[m]) - 1) * 100
    row = f(g_), f(rD + idle * CY), f(combo(g_, 1.0))
    extra = f(combo(mix2, 1.0)) if y >= 2018 else float('nan')
    print(f'{y}  黄金 {row[0]:+6.1f}  D {row[1]:+6.1f}  D+黄金 {row[2]:+6.1f}  D+黄金/国债 {extra:+6.1f}')
