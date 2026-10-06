"""Cross-asset time-series trend (long-only, ETFs, total-return acc_nav): MA / momentum signals, inverse-vol weights, cash 2%; vs buy&hold; correlation with D and overlay on D idle cash. Research only."""
import os, numpy as np, pandas as pd
Z = np.load('grp30_streams.npz'); rD, ex = Z['rD'], Z['ex']
dates = np.load('panel_ext.npz', allow_pickle=True)['dates'].astype(str); nd = len(dates); di = {d: i for i, d in enumerate(dates)}
NAV = os.path.expanduser('~/mnt/lake/bronze/provider=eastmoney/etf_nav/')
def ret(sym):
    x = pd.read_parquet(NAV + sym.replace('.', '_') + '.parquet', columns=['date', 'acc_nav']); x['date'] = x['date'].astype(str); x = x[x.date.isin(di)]
    a = np.full(nd, np.nan); a[x.date.map(di).to_numpy()] = x.acc_nav.to_numpy(); a = pd.Series(a).ffill().to_numpy()
    r = np.full(nd, np.nan); r[1:] = a[1:] / a[:-1] - 1
    first = int(np.nonzero(np.isfinite(a))[0][0]); r[:first + 1] = np.nan
    bad = np.abs(r) > 0.12                                  # drop obvious NAV glitches
    r[bad] = 0.0; return r
CORE = ['sh.510300', 'sh.510500', 'sz.159941', 'sh.518880', 'sh.511260']
BROAD = ['sh.510050', 'sh.510300', 'sh.510500', 'sz.159915', 'sh.512100', 'sh.518880', 'sz.159941', 'sh.513050', 'sh.511260', 'sh.511220', 'sh.512880', 'sh.512800', 'sh.512400', 'sh.512690', 'sh.512480', 'sh.511030']
CY = 0.02 / 245; COST = 0.0005
def build(uni, rule, hold_always=False):
    R = np.vstack([ret(s) for s in uni]).T; Rz = np.nan_to_num(R); n = R.shape[1]
    idx = np.cumprod(1 + Rz, 0); avail = np.isfinite(R)
    ma = lambda L: pd.DataFrame(np.where(avail, idx, np.nan)).rolling(L, min_periods=L).mean().to_numpy()
    sig = {}
    for L in (60, 120, 200): sig[f'MA{L}'] = (idx > ma(L)).astype(float) * np.isfinite(ma(L))
    mom = np.full_like(idx, np.nan); mom[245:] = idx[245:] / idx[:-245] - 1; sig['MOM12'] = (mom > 0).astype(float) * np.isfinite(mom)
    sig['ENS'] = (sig['MA60'] + sig['MA120'] + sig['MA200']) / 3
    S = np.ones_like(idx) * avail if hold_always else sig[rule]
    vol = pd.DataFrame(R).rolling(60, min_periods=40).std().to_numpy()
    iv = np.where(avail & np.isfinite(vol) & (vol > 0), 1 / vol, 0.0); W = iv / np.maximum(iv.sum(1, keepdims=True), 1e-12)   # inverse-vol among available assets, sums to 1
    pos = W * S; pos = np.vstack([np.zeros((1, n)), pos[:-1]])     # signal at close t -> position from t+1
    out = (pos * Rz).sum(1) + (1 - pos.sum(1)) * CY - COST * np.abs(np.diff(np.vstack([np.zeros((1, n)), pos]), axis=0)).sum(1)
    started = np.cumsum(avail.any(1)) > 0; first_pos = int(np.nonzero(pos.sum(1) > 0)[0][0]) if (pos.sum(1) > 0).any() else nd
    out[:first_pos] = np.nan
    return out, pos.sum(1)
def stat(r, v, label):
    x = r[v]; cum = np.cumprod(1 + x); n = len(x); cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    print(f'{label:52s} 年化{cagr*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% 卡玛{cagr/abs(dd):4.2f}', flush=True)
idle = 1 - np.r_[0, ex[:-1]]
def combo(s, k): a = k * idle; da = np.abs(np.diff(np.r_[0, a])); return rD + a * np.nan_to_num(s) - COST * da + (idle - a) * CY
for uname, uni in (('核心 5 资产（沪深300 / 中证500 / 纳指 / 黄金 / 十年国债）', CORE), ('16 只分散 ETF（宽基 / 行业 / 海外 / 黄金 / 债券）', BROAD)):
    print(f'######## {uname}', flush=True)
    bh, e_bh = build(uni, None, hold_always=True)
    sigs = {}
    for rule in ('MA60', 'MA120', 'MA200', 'MOM12', 'ENS'): sigs[rule] = build(uni, rule)
    allr = [bh] + [v[0] for v in sigs.values()]
    v = np.isfinite(rD) & np.isfinite(ex) & np.all([np.isfinite(a) for a in allr], 0)
    print(f'窗口 {dates[np.nonzero(v)[0][0]]} ~ {dates[np.nonzero(v)[0][-1]]}', flush=True)
    stat(rD + idle * CY, v, 'D 单独')
    cor = np.corrcoef(rD[v], bh[v])[0, 1]; stat(bh, v, f'买入持有（逆波动加权，满仓）（与 D 相关 {cor:+.2f}）')
    for k in (0.5, 1.0): stat(combo(bh, k), v, f'   D + 买入持有 k={k:g}')
    for rule, (s, e) in sigs.items():
        cor = np.corrcoef(rD[v], s[v])[0, 1]; stat(s, v, f'趋势 {rule}（平均持仓 {e[v].mean()*100:.0f}%，与 D 相关 {cor:+.2f}）')
        for k in (0.5, 1.0): stat(combo(s, k), v, f'   D + 趋势 {rule} k={k:g}')
