"""Catch-up via correlation peers (no industry labels): each month, for every stock pick the 10 stocks whose market-adjusted daily returns
over the past 250 days correlate most with it. Signal = peers' 5d return - own 5d return. Cross-section diagnostic + same-day control + portfolio. Research only."""
import sys, os, time
from grp7 import *
T0 = time.time()
c, o = panel.c, panel.o
r1 = np.full((nd, nc), np.nan, np.float32); r1[1:] = c[1:] / c[:-1] - 1; r1[np.abs(r1) > 0.25] = np.nan
mret = np.nanmean(np.where(cand.uni, r1, np.nan), 1).astype(np.float32)
ra = r1 - mret[:, None]
K = 10; step = 21
cache = 'peers.npz'
months = list(range(260, nd, step))
if os.path.exists(cache):
    P = np.load(cache)['P']
else:
    P = np.full((len(months), nc, K), -1, np.int16)
    for mi, t in enumerate(months):
        w = ra[t - 249:t + 1]; ok = cand.uni[t] & (np.isfinite(w).sum(0) >= 200)
        idx = np.nonzero(ok)[0]
        if len(idx) <= K + 1: continue
        x = w[:, idx]; x = x - np.nanmean(x, 0); x = np.nan_to_num(x); x /= np.maximum(np.sqrt((x ** 2).sum(0)), 1e-9)
        C = x.T @ x; np.fill_diagonal(C, -9)
        top = np.argpartition(-C, K, axis=1)[:, :K]
        P[mi, idx] = idx[top]
        if mi % 40 == 0: print('peers', mi, len(months), len(idx), round(time.time() - T0), 's', flush=True)
    np.savez(cache, P=P)
ret5 = np.full((nd, nc), np.nan, np.float32); ret5[5:] = c[5:] / c[:-5] - 1
peer5 = np.full((nd, nc), np.nan, np.float32)
for mi, t0 in enumerate(months):
    t1 = min(nd, t0 + step + 1) if mi + 1 < len(months) else nd
    a = t0 + 1; pp = P[mi]; has = pp[:, 0] >= 0
    if a >= t1: continue
    blk = ret5[a:t1]; g = blk[:, np.where(has[:, None], pp, 0)]           # (T, nc, K)
    with np.errstate(all='ignore'): pm = np.nanmean(g, 2)
    pm[:, ~has] = np.nan; peer5[a:t1] = pm
print('peer5 ready', round(time.time() - T0), 's', flush=True)
big = np.zeros((nd, nc), np.int16); dd60 = np.full((nd, nc), np.nan, np.float32)
for j0 in range(0, nc, 600):
    cc = pd.DataFrame(c[:, j0:j0 + 600].astype(np.float64)); dd60[:, j0:j0 + 600] = (cc / cc.rolling(60, min_periods=40).max() - 1).to_numpy()
    big[:, j0:j0 + 600] = (cc.pct_change(fill_method=None) <= -0.095).rolling(20, min_periods=1).sum().to_numpy().astype(np.int16)
ret20 = cand.ret20
clean = np.isfinite(ret20) & (ret20 >= -0.05) & (big == 0) & (dd60 >= -0.20)
H = (5, 10, 20); fwd = {}; base = {}
for h in H:
    f_ = np.full((nd, nc), np.nan, np.float32); f_[:-h] = c[h:] / o[1:nd - h + 1] - 1; f_[~np.isfinite(f_) | (np.abs(f_) > 3)] = np.nan
    fwd[h] = f_; u = cand.uni & np.isfinite(f_); base[h] = np.where(u, f_, 0).sum(1) / np.maximum(u.sum(1), 1)
yrs = np.array([int(d[:4]) for d in panel.dates]); mg10 = np.isfinite(market.z) & (market.z >= 1.0)
def diag(name, pool, score, min_n=25):
    q = np.full((nd, nc), -1, np.int8)
    for t in np.nonzero(pool.sum(1) >= min_n)[0]:
        idx = np.nonzero(pool[t] & np.isfinite(score[t]))[0]
        if len(idx) < min_n: continue
        q[t, idx] = np.minimum((pd.Series(score[t, idx]).rank(pct=True).to_numpy() * 5).astype(int), 4)
    parts = []
    for h in H:
        ex = fwd[h] - base[h][:, None]; row = [np.mean(ex[(q == k) & np.isfinite(ex)]) * 1e4 for k in range(5)]
        sp = [ex[(q == 4) & (yrs == y)[:, None] & np.isfinite(ex)].mean() - ex[(q == 0) & (yrs == y)[:, None] & np.isfinite(ex)].mean() for y in range(2009, 2027)]
        parts.append(f'{h}日: ' + ' '.join(f'{v:+4.0f}' for v in row) + f' 差{row[4]-row[0]:+4.0f} 年胜{np.mean(np.array(sp) > 0)*100:3.0f}%')
    print(f'{name:34s} | ' + ' | '.join(parts), flush=True)
def pool_ex(name, pool, ctrl):
    out = []
    for h in H:
        ex = fwd[h] - base[h][:, None]; a_ = ex[pool & np.isfinite(ex)].mean() * 1e4; b_ = ex[ctrl & np.isfinite(ex)].mean() * 1e4; out.append(f'{h}日 {a_:+4.0f} 对照{b_:+4.0f} 差{a_-b_:+4.0f}')
    ex = fwd[20] - base[20][:, None]
    yy = [ex[pool & (yrs == y)[:, None] & np.isfinite(ex)].mean() - ex[ctrl & (yrs == y)[:, None] & np.isfinite(ex)].mean() for y in range(2009, 2027)]
    print(f'{name:40s} 样本{int(pool.sum()):7d} | ' + ' | '.join(out) + f' | 20日差为正年份 {np.mean(np.array(yy) > 0)*100:.0f}%', flush=True)
if __name__ == '__main__':
    gap = peer5 - ret5; base_pool = cand.uni & clean & np.isfinite(gap)
    print('=== 相关性同伴补涨：分数 = 同伴5日涨幅 - 自己5日涨幅（档5=最落后），超额 bp 未扣成本', flush=True)
    diag('全部日子 无雷', base_pool, gap)
    diag('大盘 z>=1.0 无雷', base_pool & mg10[:, None], gap)
    diag('同伴5日>=5% 无雷', base_pool & (peer5 >= 0.05), gap)
    print('=== 池整体 vs 同日对照（同伴没大涨的无雷股）', flush=True)
    sig = base_pool & (peer5 >= 0.05) & (ret5 <= peer5); day = sig.any(1)
    ctrl = base_pool & (peer5 < 0.02) & day[:, None]
    pool_ex('同伴5日>=5% 且自己没跟上', sig, ctrl)
    pool_ex('  同上 & 大盘 z>=1.0', sig & mg10[:, None], ctrl & mg10[:, None])
    sig8 = base_pool & (peer5 >= 0.08) & (ret5 <= peer5 - 0.04)
    pool_ex('同伴5日>=8% 且自己落后>=4个点', sig8, base_pool & (peer5 < 0.02) & sig8.any(1)[:, None])
    print('done', round(time.time() - T0), 's', flush=True)
