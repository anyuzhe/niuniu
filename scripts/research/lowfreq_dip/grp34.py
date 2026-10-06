"""ETF own-panic sleeve: each ETF (non-bond/money) with own z (20d ret / (60d std * sqrt20)) <= -1.5 -> buy next open, hold 20d; sleeve weight per position, overlay on D idle. 2019+. Research only."""
import os, glob, numpy as np, pandas as pd
Z = np.load('grp30_streams.npz'); rD, ex = Z['rD'], Z['ex']
dates = np.load('panel_ext.npz', allow_pickle=True)['dates'].astype(str); nd = len(dates); di = {d: i for i, d in enumerate(dates)}
B = os.path.expanduser('~/mnt/lake/bronze/provider=tdx/'); u = pd.read_parquet(B + 'etf_universe/latest.parquet').set_index('symbol')
O = {}; C = {}
for f in sorted(glob.glob(B + 'etf_kline_daily/*.parquet')):
    s = os.path.basename(f)[:-8].replace('_', '.'); cat = u.category.get(s, '')
    if cat in ('bond', 'money'): continue
    x = pd.read_parquet(f, columns=['date', 'open', 'close']); x['date'] = x['date'].astype(str); x = x[x.date.isin(di)]
    if len(x) < 150: continue
    o = np.full(nd, np.nan); c = np.full(nd, np.nan); ii = x.date.map(di).to_numpy(); o[ii] = x.open.to_numpy(); c[ii] = x.close.to_numpy()
    # a split / share-consolidation shows up as a >30% one-day jump; drop such ETFs to avoid artefacts
    cc = pd.Series(c).ffill(); jump = (cc / cc.shift(1) - 1).abs().max()
    if jump > 0.30: print('skip (jump)', s, u.name.get(s, ''), round(jump, 2)); continue
    O[s] = o; C[s] = c
syms = list(C); print('ETFs', len(syms), flush=True)
CY = 0.02 / 245; FEE = 0.0005
def sleeve(th, wpos, maxpos, H=20, cats=None):
    ret_sleeve = np.zeros(nd); pos = []  # (sym, entry_t, exit_t, wt)
    zs = {}
    for s in syms:
        c = pd.Series(C[s]).ffill(); r1 = c.pct_change(); r20 = np.exp(np.log1p(r1).rolling(20, min_periods=20).sum()) - 1; sd = r1.rolling(60, min_periods=40).std()
        zs[s] = (r20 / (sd * np.sqrt(20))).to_numpy()
    held = {}; ntr = 0; wins = 0; tot = 0.0
    expo = np.zeros(nd)
    for t in range(nd - 1):
        # exits
        for s in [s for s, p in held.items() if p[1] == t]:
            held.pop(s)
        # entries at t+1 open from signal at close t
        if t + 1 < nd:
            cand = [s for s in syms if s not in held and np.isfinite(zs[s][t]) and zs[s][t] <= th and np.isfinite(O[s][t + 1]) and np.isfinite(C[s][min(t + H, nd - 1)])]
            cand.sort(key=lambda s: zs[s][t])
            for s in cand[:max(0, maxpos - len(held))]:
                held[s] = (t + 1, t + H); ntr += 1
                g = C[s][min(t + H, nd - 1)] / O[s][t + 1] - 1 - 2 * FEE; tot += g; wins += g > 0
        # daily sleeve return (weights fixed at wpos of sleeve-capital each)
        r = 0.0
        for s, (e, x) in held.items():
            if e <= t + 1 <= x + 0:
                pass
        ret_sleeve[t] = 0.0
    return ntr, wins, tot
# simple event-level view first, then a daily stream via per-position daily returns
def stream(th, wpos, maxpos, H=20):
    r = np.zeros(nd); ex_s = np.zeros(nd); held = {}; trades = []
    zs = {}
    for s in syms:
        c = pd.Series(C[s]).ffill(); r1 = c.pct_change(); r20 = np.exp(np.log1p(r1).rolling(20, min_periods=20).sum()) - 1; sd = r1.rolling(60, min_periods=40).std()
        zs[s] = (r20 / (sd * np.sqrt(20))).to_numpy()
    cl = {s: pd.Series(C[s]).ffill().to_numpy() for s in syms}
    for t in range(1, nd):
        # signal at close t-1 -> entry at open t if flagged
        for s in list(held):
            e, x = held[s]
            if t > x: held.pop(s)
        for s in sorted([s for s in syms if s not in held and np.isfinite(zs[s][t - 1]) and zs[s][t - 1] <= th and np.isfinite(O[s][t])], key=lambda s: zs[s][t - 1])[:max(0, maxpos - len(held))]:
            held[s] = (t, t + H - 1)
        tr = 0.0
        for s, (e, x) in held.items():
            if t == e:
                g = cl[s][t] / O[s][t] - 1 - FEE
            elif t == x:
                g = cl[s][t] / cl[s][t - 1] - 1 - FEE
            else:
                g = cl[s][t] / cl[s][t - 1] - 1
            if np.isfinite(g): tr += wpos * g
        r[t] = tr; ex_s[t] = wpos * len(held)
    return r, ex_s
def stat(rr, valid, label):
    x = rr[valid]; cum = np.cumprod(1 + x); n = len(x); cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    print(f'{label:46s} 年化{cagr*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% 卡玛{cagr/abs(dd):4.2f}', flush=True)
idle = 1 - np.r_[0, ex[:-1]]
t0 = di[[d for d in dates if d >= '2019-08-01'][0]]
valid = np.isfinite(rD) & np.isfinite(ex); valid[:t0] = False
for th in (-1.5, -2.0):
    for wpos, maxpos in ((0.05, 6), (0.10, 6), (0.10, 10)):
        r, e = stream(th, wpos, maxpos)
        cor = np.corrcoef(rD[valid], r[valid])[0, 1]
        # scale sleeve so total gross <= 1: sleeve uses only idle capital
        sc = np.minimum(1.0, idle / np.maximum(e, 1e-9))
        stat(rD + idle * CY, valid, 'D 单独（2019-08 起）')
        stat(r, valid, f'[ETF 恐慌子策略 z≤{th} 每只{wpos*100:g}% 最多{maxpos}只，单独（占总资金）] 平均仓位{e[valid].mean()*100:.0f}% 与D相关{cor:+.2f}')
        tot = rD + sc * r + (idle - sc * e) * CY
        stat(tot, valid, f'   D + 该子策略（只用闲置资金）')
