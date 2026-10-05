"""(1) Greedy market (z>=1.5): exclude 'leaders' (industry-gap / peer-gap) vs include. (2) Donchian channel breakout in greedy market, event level with matched controls. Research only."""
import sys
from grp16 import *
mz = market.z
g15 = np.isfinite(mz) & (mz >= 1.5); g10 = np.isfinite(mz) & (mz >= 1.0)
if sys.argv[1] == 'a':
    # --- leaders: industry gap (20d) and peers gap (5d)
    R_, A_ = ind_series(l1); s_ = pd.DataFrame(np.log1p(np.nan_to_num(R_))); r20i = (np.exp(s_.rolling(20, min_periods=20).sum()) - 1).to_numpy(); r20i[~np.isfinite(R_)] = np.nan
    mm = np.nonzero(l1 >= 0)[0]; ind20 = np.full((nd, nc), np.nan, np.float32); ind20[:, mm] = r20i[:, l1[mm]]
    gapI = ind20 - ret20; gapP = peer5 - ret5
    def qrank(x, pool):
        q = np.full((nd, nc), np.nan, np.float32)
        for t in np.nonzero(pool.sum(1) >= 25)[0]:
            idx = np.nonzero(pool[t] & np.isfinite(x[t]))[0]
            if len(idx) >= 25: q[t, idx] = pd.Series(x[t, idx]).rank(pct=True).to_numpy()
        return q
    base_pool = cand.uni & clean
    didx = {d: i for i, d in enumerate(panel.dates)}
    def go(label, pool, hold=20):
        day = pool.any(1)
        fm = Market(mret=market.mret, mk20=market.mk20, z=np.where(day, -9.0, 9.0), count=market.count)
        fc = Candidates(uni=cand.uni, e6=pool, buyok=cand.buyok, ret20=ret20)
        cfg = DipConfig(leverage=1.0, hold_days=hold, rank='random')
        r = simulate(panel, fm, fc, cfg); sm = summarize(panel, fm, r, cfg); s2 = sm['stats'] or {}; h = halves(panel, r['eq'])
        tr = r['trades']; b = base[20]; ex = [t['ret'] - b[didx[t['signal']]] for t in tr if np.isfinite(b[didx[t['signal']]])]
        print(f"{label:46s} 触发{int(day.sum()):4d}天 笔{len(tr):5d} 笔均{np.mean([t['ret'] for t in tr])*1e4:+5.0f}bp 超额{np.mean(ex)*1e4:+5.0f}bp | 年化{s2.get('cagr',0)*100:+5.1f}% 夏普{s2.get('sharpe',0):+.2f} 回撤{s2.get('max_drawdown',0)*100:4.0f}% 仓位{s2.get('exposure',0)*100:3.0f}% | {h}", flush=True)
    for gname, gate in (('z>=1.5', g15), ('z>=1.0', g10)):
        gp = base_pool & gate[:, None]
        qi = qrank(-gapI, gp)        # high = most leading (smallest gap)
        qp = qrank(-gapP, gp)
        print(f'=== 大盘 {gname}：随机取20只，1x，持有20日，扣成本（领涨 = 行业内 / 同伴内最强的一档）', flush=True)
        go(f'{gname} 全部无雷股', gp)
        go(f'{gname} 剔除行业领涨前20%', gp & ~(qi >= 0.8))
        go(f'{gname} 仅行业领涨前20%（对照）', gp & (qi >= 0.8))
        go(f'{gname} 剔除同伴领涨前20%', gp & ~(qp >= 0.8))
        go(f'{gname} 仅同伴领涨前20%（对照）', gp & (qp >= 0.8))
        go(f'{gname} 剔除两者领涨前20%', gp & ~(qi >= 0.8) & ~(qp >= 0.8))
        go(f'{gname} 行业和同伴都落后(后40%)', gp & (qi < 0.4) & (qp < 0.4))
if sys.argv[1] == 'b':
    uni = cand.uni; cc = c.astype(np.float64)
    def roll_hi(n): return pd.DataFrame(cc).shift(1).rolling(n, min_periods=n).max().to_numpy().astype(np.float32)
    def roll_lo(n): return pd.DataFrame(cc).shift(1).rolling(n, min_periods=n).min().to_numpy().astype(np.float32)
    ma20 = pd.DataFrame(cc).rolling(20).mean().to_numpy(); ma60 = pd.DataFrame(cc).rolling(60).mean().to_numpy()
    trend = (cc > ma20) & (cc > ma60)
    def first_after(flag):
        """nxt[t,j] = first index >= t where flag, else big"""
        idx = np.where(flag, np.arange(nd)[:, None], 32000).astype(np.int32)
        return np.minimum.accumulate(idx[::-1], axis=0)[::-1]
    ok = cand.buyok & uni
    fee_rt = 0.004
    def evaluate(entry, nxt, gate, label, maxh=60, ctrl=None):
        E = entry & ok & gate[:, None]; E[-3:] = False
        ts, js = np.nonzero(E); out = []
        e = ts + 1; ex_ = np.minimum(nxt[np.minimum(ts + 2, nd - 1), js] + 1, np.minimum(e + maxh, nd - 1))
        px_e = o[e, js]; px_x = o[np.minimum(ex_, nd - 1), js]
        net = px_x / px_e - 1 - fee_rt; okm = np.isfinite(net) & (np.abs(net) < 3)
        net, ts_ = net[okm], ts[okm]; hold = (ex_ - e)[okm]
        # by-day average to remove cluster weighting
        df = pd.DataFrame({'t': ts_, 'r': net}); byd = df.groupby('t')['r'].mean()
        half = [byd[byd.index < nd // 2].mean(), byd[byd.index >= nd // 2].mean()]
        print(f'{label:52s} 笔{len(net):6d} 日{len(byd):4d} 笔均{net.mean()*1e4:+5.0f}bp 日均{byd.mean()*1e4:+5.0f}bp 中位{np.median(net)*1e4:+5.0f} 胜率{(net>0).mean()*100:3.0f}% 持有{hold.mean():4.1f}天 | 前后半(日均) {half[0]*1e4:+4.0f}/{half[1]*1e4:+4.0f}', flush=True)
        return byd
    for N in (20, 55):
        hi = roll_hi(N); brk = (cc > hi) & uni
        first = brk & ~np.vstack([np.zeros((1, nc), bool), brk[:-1]])
        for M in (10, 20):
            lo = roll_lo(M); nxt = first_after(cc < lo)
            for gname, gate in (('z>=1.5', g15), ('z>=1.0', g10), ('任何日子', np.ones(nd, bool))):
                a = evaluate(first, nxt, gate, f'突破{N}日高点, 破{M}日低点出, {gname}')
                ctrl = trend & ~brk & uni
                b = evaluate(ctrl, nxt, gate, f'  对照: 趋势股(在MA20/60上)未突破, 同出场, {gname}')
                print(f'  → 突破日均 − 对照日均 = {(a.reindex(b.index).mean()-b.mean())*1e4:+.0f}bp', flush=True)
