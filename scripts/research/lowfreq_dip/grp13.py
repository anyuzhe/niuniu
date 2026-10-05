"""Catch-up (补涨) in greedy markets: hot market / hot industry, buy stocks that lag their industry but are not 'landmines'. Research only.
gap = industry 20d return - stock 20d return. Landmine screens: 20d return floor, no big-drop day in 20d, drawdown from 60d high floor."""
import sys, time
from grp7 import *
T0 = time.time()
R, A = ind_series(l1); Z = zscore(R)
# industry 20d return and rank
s = pd.DataFrame(np.log1p(np.nan_to_num(R))); r20i = (np.exp(s.rolling(20, min_periods=20).sum()) - 1).to_numpy(); r20i[~np.isfinite(R)] = np.nan
rk20i = rank_pct(r20i)
ind20 = np.full((nd, nc), np.nan, np.float32); m = np.nonzero(l1 >= 0)[0]; ind20[:, m] = r20i[:, l1[m]]
ret20 = cand.ret20; gap = ind20 - ret20
c = panel.c
dd60 = np.full((nd, nc), np.nan, np.float32); big = np.zeros((nd, nc), np.int16); r60 = np.full((nd, nc), np.nan, np.float32)
for j0 in range(0, nc, 600):
    cc = pd.DataFrame(c[:, j0:j0 + 600].astype(np.float64)); dd60[:, j0:j0 + 600] = (cc / cc.rolling(60, min_periods=40).max() - 1).to_numpy()
    d1 = cc.pct_change(fill_method=None); big[:, j0:j0 + 600] = (d1 <= -0.095).rolling(20, min_periods=1).sum().to_numpy().astype(np.int16)
    r60[:, j0:j0 + 600] = (cc / cc.shift(60) - 1).to_numpy()
del cc, d1
# universe EW forward 20d return (for excess)
fw = np.full(nd, np.nan)
for t in range(nd - 20):
    u = cand.uni[t]; x = c[t + 20, u] / c[t, u] - 1; fw[t] = np.nanmean(x) if np.isfinite(x).any() else np.nan
didx = {d: i for i, d in enumerate(panel.dates)}
mz = market.z
def clean(level):
    if level == 0: return np.ones((nd, nc), bool)
    ok = np.isfinite(ret20) & (ret20 >= -0.05) & (big == 0) & (dd60 >= -0.20)
    if level >= 2: ok &= np.isfinite(r60) & (r60 >= -0.10)
    return ok
def go(label, gate_ind, mktcond=None, laggard=0.05, level=1, hold=20, key='gap', quiet=False, prange=None):
    """gate_ind[nd,31] bool industries considered hot on day t; stock eligible if in a hot industry, gap>=laggard (None = no laggard filter), passes landmine level."""
    inH = np.zeros((nd, nc), bool); inH[:, m] = gate_ind[:, l1[m]]
    pool = cand.uni & inH & np.isfinite(ret20) & clean(level)
    if laggard is not None: pool &= np.isfinite(gap) & (gap >= laggard)
    if prange is not None:
        pr = np.full((nd, nc), np.nan, np.float32)
        for t in np.nonzero(pool.sum(1) >= 25)[0]:
            idx = np.nonzero(pool[t])[0]; pr[t, idx] = pd.Series(gap[t, idx]).rank(pct=True).to_numpy()
        pool &= np.isfinite(pr) & (pr >= prange[0]) & (pr <= prange[1])
    day = pool.any(1)
    if mktcond is not None: day &= mktcond; pool &= mktcond[:, None]
    kk = {'gap': -gap, 'weak': ret20, 'strong': gap, 'rand': ret20}[key]
    fm = Market(mret=market.mret, mk20=market.mk20, z=np.where(day, -9.0, 9.0), count=market.count)
    fc = Candidates(uni=cand.uni, e6=pool, buyok=cand.buyok, ret20=np.where(np.isfinite(kk), kk, 9.0).astype(np.float32))
    cfg = DipConfig(leverage=1.0, hold_days=hold, rank='random' if key == 'rand' else 'drop20')
    r = simulate(panel, fm, fc, cfg); sm = summarize(panel, fm, r, cfg); st = sm['stats'] or {}; h = halves(panel, r['eq'])
    tr = r['trades']; ex = [t['ret'] - fw[didx[t['signal']]] for t in tr if np.isfinite(fw[didx[t['signal']]])]
    n = len(tr); mean = np.mean([t['ret'] for t in tr]) * 1e4 if n else 0; exm = np.mean(ex) * 1e4 if ex else 0
    if not quiet:
        print(f"{label:58s} 触发{int(day.sum()):4d}天 笔{n:5d} 笔均{mean:+5.0f}bp 超额{exm:+5.0f}bp | 年化{st.get('cagr',0)*100:+5.1f}% 夏普{st.get('sharpe',0):+.2f} 回撤{st.get('max_drawdown',0)*100:4.0f}% 仓位{st.get('exposure',0)*100:3.0f}% | {h}", flush=True)
    return r
if __name__ == '__main__':
    st = sys.argv[1]
    hot15 = np.isfinite(Z) & (Z >= 1.5); hot10 = np.isfinite(Z) & (Z >= 1.0); top5 = np.isfinite(rk20i) & (rk20i >= 1 - 5 / 31 + 1e-9)
    mg10 = np.isfinite(mz) & (mz >= 1.0); mg15 = np.isfinite(mz) & (mz >= 1.5)
    print(f'触发统计: 大盘 z>=1.0 {int(mg10.sum())} 天, >=1.5 {int(mg15.sum())} 天; 行业 z>=1.5 的日子 {int(hot15.any(1).sum())} 天', flush=True)
    if st == 'a':
        print('=== 热门行业 (行业 z>=1.5) 内补涨：落后行业 >=5 个点，无雷(20日>=-5%、20日无大跌日、60日回撤<=20%)，按落后幅度排序', flush=True)
        go('补涨 行业z>=1.5 gap>=5% 无雷', hot15)
        go('  对照: 同池不要求落后，随机买', hot15, laggard=None, key='rand')
        go('  对照: 同池不筛雷，按落后幅度', hot15, level=0)
        go('  对照: 买领涨(行业内最强)', hot15, laggard=None, key='strong')
        go('补涨 行业z>=1.0', hot10)
        go('补涨 行业top5 20日涨幅', top5)
    if st == 'b':
        print('=== 叠加“市场贪婪”：大盘 z>=1.0 / >=1.5', flush=True)
        go('补涨 大盘z>=1.0 & 行业top5', top5, mktcond=mg10)
        go('补涨 大盘z>=1.5 & 行业top5', top5, mktcond=mg15)
        go('补涨 大盘z>=1.0 & 行业z>=1.0', hot10, mktcond=mg10)
        go('  对照: 大盘z>=1.0 & 行业top5 随机买全部成员', top5, mktcond=mg10, laggard=None, key='rand')
        go('  对照: 大盘z>=1.0 买领涨', top5, mktcond=mg10, laggard=None, key='strong')
    if st == 'c':
        print('=== 持有期 5 / 10 / 20 日（补涨更像短线）', flush=True)
        for hd in (5, 10):
            go(f'补涨 行业z>=1.5 gap>=5% 无雷 持有{hd}日', hot15, hold=hd)
            go(f'补涨 大盘z>=1.0 & 行业top5 持有{hd}日', top5, mktcond=mg10, hold=hd)
        print('=== 贪婪更极端 / 落后更多 / 更严的无雷', flush=True)
        go('补涨 行业z>=2.0 gap>=8% 无雷', np.isfinite(Z) & (Z >= 2.0), laggard=0.08)
        go('补涨 行业z>=1.5 gap>=5% 严无雷(60日>=-10%)', hot15, level=2)
        go('补涨 大盘z>=1.5 & 行业z>=1.0 gap>=8%', hot10, mktcond=mg15, laggard=0.08)
    if st == 'd':
        print('=== 截面诊断：热门行业成员，按落后幅度(gap)当天分五档，未来20日收盘到收盘收益减全市场等权（bp，均值 / 样本天数）', flush=True)
        fwd = np.full((nd, nc), np.nan, np.float32); fwd[:-20] = c[20:] / c[:-20] - 1
        for name, gate_, mc in (('行业z>=1.5', hot15, None), ('大盘z>=1.0&行业top5', top5, mg10), ('大盘z>=1.5&行业z>=1.0', hot10, mg15)):
            inH = np.zeros((nd, nc), bool); inH[:, m] = gate_[:, l1[m]]
            for lvl in (0, 1):
                pool = cand.uni & inH & np.isfinite(ret20) & np.isfinite(gap) & clean(lvl)
                if mc is not None: pool &= mc[:, None]
                q = np.full((nd, nc), -1, np.int8); days = np.nonzero(pool.sum(1) >= 25)[0]
                for t in days:
                    idx = np.nonzero(pool[t])[0]; pct = pd.Series(gap[t, idx]).rank(pct=True).to_numpy(); q[t, idx] = np.minimum((pct * 5).astype(int), 4)
                out = []
                for k in range(5):
                    mk_ = (q == k) & np.isfinite(fwd); ex_ = (fwd - fw[:, None])[mk_]
                    out.append(f'{np.mean(ex_)*1e4:+5.0f}')
                print(f'{name:22s} 无雷={lvl} 档1(最领涨)..档5(最落后): ' + ' '.join(out) + f' | 天数 {len(days)}', flush=True)
    if st == 'e':
        print('=== 不取最极端的落后股：热门池内当天 gap 百分位限定在区间内，区间内随机取（避免全市场只买 gap 最大的 20 只）', flush=True)
        for rng_ in ((0.4, 0.9), (0.6, 1.0), (0.2, 0.8)):
            go(f'行业z>=1.5 无雷 gap分位{rng_}', hot15, laggard=None, prange=rng_, key='rand')
            go(f'大盘z>=1.0&行业top5 无雷 gap分位{rng_}', top5, mktcond=mg10, laggard=None, prange=rng_, key='rand')
        go('对照: 行业z>=1.5 无雷 全池随机(不分档)', hot15, laggard=None, key='rand')
