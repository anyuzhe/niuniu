"""Catch-up, second round: short-window gap (5d), big-cap lead -> small-cap lag within industry, volume confirmation.
Cross-sectional diagnostic: daily quintiles of a score inside a pool; forward return from next open to close t+h minus universe EW same window. Research only."""
import sys, time
from grp7 import *
T0 = time.time()
R, A = ind_series(l1); Z = zscore(R)
def roll(R_, n):
    s = pd.DataFrame(np.log1p(np.nan_to_num(R_))); x = (np.exp(s.rolling(n, min_periods=n).sum()) - 1).to_numpy(); x[~np.isfinite(R_)] = np.nan; return x
r5i = roll(R, 5); r20i = roll(R, 20); rk5i = rank_pct(r5i)
m = np.nonzero(l1 >= 0)[0]
def to_stock(x):
    out = np.full((nd, nc), np.nan, np.float32); out[:, m] = x[:, l1[m]]; return out
c, o = panel.c, panel.o
ret5 = np.full((nd, nc), np.nan, np.float32); ret5[5:] = c[5:] / c[:-5] - 1
ret20 = cand.ret20
capq = np.load('capq.npy')
# big-cap (cap quintile 4) EW 5d return per industry
big5 = np.full((nd, 31), np.nan)
for g in range(31):
    cols = np.nonzero(l1 == g)[0]
    if not len(cols): continue
    x = ret5[:, cols]; b = (capq[:, cols] == 4) & cand.uni[:, cols] & np.isfinite(x); n = b.sum(1)
    big5[:, g] = np.where(n >= 3, np.where(b, x, 0).sum(1) / np.maximum(n, 1), np.nan)
# volume ratio
a = np.nan_to_num(panel.a, nan=0.0).astype(np.float64); cs = np.cumsum(a, 0)
v5 = np.full((nd, nc), np.nan, np.float32); v5[5:] = (cs[5:] - cs[:-5]) / 5; v60 = np.full((nd, nc), np.nan, np.float32); v60[60:] = (cs[60:] - cs[:-60]) / 60
vr = v5 / np.where(v60 > 0, v60, np.nan); del a, cs
# landmine screen (price based)
big = np.zeros((nd, nc), np.int16); dd60 = np.full((nd, nc), np.nan, np.float32)
for j0 in range(0, nc, 600):
    cc = pd.DataFrame(c[:, j0:j0 + 600].astype(np.float64)); dd60[:, j0:j0 + 600] = (cc / cc.rolling(60, min_periods=40).max() - 1).to_numpy()
    big[:, j0:j0 + 600] = (cc.pct_change(fill_method=None) <= -0.095).rolling(20, min_periods=1).sum().to_numpy().astype(np.int16)
clean = np.isfinite(ret20) & (ret20 >= -0.05) & (big == 0) & (dd60 >= -0.20)
# forward returns from next open
H = (5, 10, 20)
fwd = {}; base = {}
for h in H:
    f_ = np.full((nd, nc), np.nan, np.float32); f_[:-h] = c[h:] / o[1:nd - h + 1] - 1
    f_[~np.isfinite(f_) | (np.abs(f_) > 3)] = np.nan
    fwd[h] = f_; u = cand.uni & np.isfinite(f_); base[h] = np.where(u, f_, 0).sum(1) / np.maximum(u.sum(1), 1)
mz = market.z; mg10 = np.isfinite(mz) & (mz >= 1.0)
def diag(name, pool, score, min_n=25):
    q = np.full((nd, nc), -1, np.int8); days = np.nonzero(pool.sum(1) >= min_n)[0]
    for t in days:
        idx = np.nonzero(pool[t] & np.isfinite(score[t]))[0]
        if len(idx) < min_n: continue
        pct = pd.Series(score[t, idx]).rank(pct=True).to_numpy(); q[t, idx] = np.minimum((pct * 5).astype(int), 4)
    parts = []
    for h in H:
        ex = fwd[h] - base[h][:, None]; row = []
        for k in range(5):
            mk_ = (q == k) & np.isfinite(ex); row.append(np.mean(ex[mk_]) * 1e4 if mk_.any() else np.nan)
        # yearly hit: share of years where top-bottom > 0
        sp = []
        yrs = np.array([int(d[:4]) for d in panel.dates])
        for y in range(2008, 2027):
            ky = yrs == y
            a5 = ((q == 4) & ky[:, None] & np.isfinite(ex)); a1 = ((q == 0) & ky[:, None] & np.isfinite(ex))
            if a5.sum() > 50 and a1.sum() > 50: sp.append(ex[a5].mean() - ex[a1].mean())
        parts.append(f'{h}日: ' + ' '.join(f'{v:+4.0f}' for v in row) + f' 档5-档1 {row[4]-row[0]:+4.0f} 年胜{np.mean(np.array(sp) > 0)*100:3.0f}%')
    print(f'{name:40s} 天数{len(days):4d} | ' + ' | '.join(parts), flush=True)
if __name__ == '__main__':
    st = sys.argv[1]
    hot5 = to_stock(np.where(np.isfinite(rk5i), rk5i, 0)) >= 1 - 5 / 31 + 1e-9
    gap5 = to_stock(r5i) - ret5
    lead = to_stock(big5) - ret5
    smallmid = (capq >= 0) & (capq <= 2)
    print('说明：分档按分数从低到高（档5=分数最高=最落后），数值为扣除全市场等权后的超额 bp（未扣交易成本，往返成本约 30~50bp）', flush=True)
    if st == 'a':
        print('=== 1. 短窗口补涨：5 日热门行业（5 日涨幅前 5）内，按 5 日落后幅度分档', flush=True)
        diag('全部日子, 无雷', cand.uni & hot5 & clean, gap5)
        diag('大盘 z>=1.0, 无雷', cand.uni & hot5 & clean & mg10[:, None], gap5)
        diag('全部日子, 不筛雷', cand.uni & hot5, gap5)
        print('=== 2. 龙头带动：同行业大市值(第5档)近5日涨幅 - 个股5日涨幅，只看中小市值(1~3档)', flush=True)
        diag('全部日子, 中小市值, 无雷', cand.uni & smallmid & clean & np.isfinite(lead), lead)
        diag('龙头5日涨>=5%, 中小市值, 无雷', cand.uni & smallmid & clean & (to_stock(big5) >= 0.05), lead)
        diag('大盘 z>=1.0, 龙头5日涨>=5%', cand.uni & smallmid & clean & (to_stock(big5) >= 0.05) & mg10[:, None], lead)
    if st == 'b':
        print('=== 3. 放量确认：5 日热门行业、5 日落后 >=3 个点、无雷，按量比(5日/60日成交额)分档', flush=True)
        pool = cand.uni & hot5 & clean & np.isfinite(gap5) & (gap5 >= 0.03)
        diag('落后股按量比分档', pool, vr)
        diag('落后股按量比分档, 大盘 z>=1.0', pool & mg10[:, None], vr)
        print('=== 对照：不分热门行业，全市场无雷股按 5 日涨幅分档（看是否只是普通短期反转）', flush=True)
        diag('全市场无雷 按 -5日涨幅(越跌越高)', cand.uni & clean, -ret5)
        diag('全市场无雷 按行业内5日落后(全部行业)', cand.uni & clean, gap5)
    if st == 'c':
        B5 = to_stock(big5); I5 = to_stock(r5i)
        print('=== 龙头带动 vs 普通行业动量：池内所有股票（不分档）未来超额', flush=True)
        def pool_ex(name, pool):
            out = []
            for h in H:
                ex = fwd[h] - base[h][:, None]; k = pool & np.isfinite(ex); out.append(f'{h}日 {ex[k].mean()*1e4:+5.0f}bp')
            yrs = np.array([int(d[:4]) for d in panel.dates]); ex = fwd[20] - base[20][:, None]
            yy = [ex[pool & (yrs == y)[:, None] & np.isfinite(ex)].mean() for y in range(2008, 2027) if (pool & (yrs == y)[:, None]).sum() > 100]
            print(f'{name:52s} 样本{int(pool.sum()):7d} | ' + ' '.join(out) + f' | 20日超额为正的年份 {np.mean(np.array(yy) > 0)*100:.0f}% ({len(yy)}年)', flush=True)
        base_pool = cand.uni & clean
        pool_ex('龙头(大市值)5日>=5%, 中小市值, 无雷', base_pool & smallmid & (B5 >= 0.05))
        pool_ex('  同上且个股5日 <= 龙头5日（还没跟上）', base_pool & smallmid & (B5 >= 0.05) & (ret5 <= B5))
        pool_ex('  对照: 行业等权5日>=5%, 中小市值', base_pool & smallmid & (I5 >= 0.05))
        pool_ex('  对照: 行业等权5日>=5%, 但龙头5日<2%（小票自己涨）', base_pool & smallmid & (I5 >= 0.05) & (B5 < 0.02))
        pool_ex('  对照: 龙头5日>=5% 的大市值股本身', base_pool & (capq == 4) & (B5 >= 0.05))
        pool_ex('龙头5日>=5% & 大盘z>=1.0, 中小市值, 无雷, 未跟上', base_pool & smallmid & (B5 >= 0.05) & (ret5 <= B5) & mg10[:, None])
        pool_ex('龙头5日>=8%, 中小市值, 无雷, 未跟上', base_pool & smallmid & (B5 >= 0.08) & (ret5 <= B5))
    if st == 'd':
        B5 = to_stock(big5); bp = cand.uni & clean & smallmid
        sig = (B5 >= 0.05) & (ret5 <= B5); dayany = (bp & sig).any(1)
        sigM = sig & mg10[:, None]
        def ex_of(pool, h=20):
            ex = fwd[h] - base[h][:, None]; k = pool & np.isfinite(ex); return ex[k].mean() * 1e4
        print('=== 关键对照：同一天、中小市值无雷股，但不在“龙头大涨”的行业里（去掉规模 / 无雷筛选本身的效应）', flush=True)
        for h in H:
            a_ = ex_of(bp & sig, h); b_ = ex_of(bp & ~(B5 >= 0.05) & dayany[:, None], h)
            a2 = ex_of(bp & sigM, h); b2 = ex_of(bp & ~(B5 >= 0.05) & (dayany & mg10)[:, None], h)
            print(f'{h:2d}日  信号池 {a_:+5.0f}bp  同日对照 {b_:+5.0f}bp  差 {a_-b_:+5.0f} | 大盘z>=1.0: 信号池 {a2:+5.0f} 对照 {b2:+5.0f} 差 {a2-b2:+5.0f}', flush=True)
    if st == 'e':
        B5 = to_stock(big5); bp = cand.uni & clean & smallmid & np.isfinite(ret20)
        sig = bp & (B5 >= 0.05) & (ret5 <= B5)
        didx = {d: i for i, d in enumerate(panel.dates)}
        def go(label, pool, hold=20, key=None, N=20):
            day = pool.any(1)
            kk = np.where(np.isfinite(key), key, 9.0).astype(np.float32) if key is not None else ret20
            fm = Market(mret=market.mret, mk20=market.mk20, z=np.where(day, -9.0, 9.0), count=market.count)
            fc = Candidates(uni=cand.uni, e6=pool, buyok=cand.buyok, ret20=kk)
            cfg = DipConfig(leverage=1.0, hold_days=hold, positions=N, rank='drop20' if key is not None else 'random')
            r = simulate(panel, fm, fc, cfg); sm = summarize(panel, fm, r, cfg); s_ = sm['stats'] or {}; h = halves(panel, r['eq'])
            tr = r['trades']; b = base[20] if hold == 20 else base[min(H, key=lambda x: abs(x - hold))]
            ex = [t['ret'] - b[didx[t['signal']]] for t in tr if np.isfinite(b[didx[t['signal']]])]
            print(f"{label:50s} 触发{int(day.sum()):4d}天 笔{len(tr):5d} 笔均{np.mean([t['ret'] for t in tr])*1e4:+5.0f}bp 超额{np.mean(ex)*1e4:+5.0f}bp | 年化{s_.get('cagr',0)*100:+5.1f}% 夏普{s_.get('sharpe',0):+.2f} 回撤{s_.get('max_drawdown',0)*100:4.0f}% 仓位{s_.get('exposure',0)*100:3.0f}% | {h}", flush=True)
        print('=== 组合回测：龙头带动补涨（中小市值、无雷、行业大市值5日>=5%、自己还没跟上），随机取，1x', flush=True)
        go('龙头带动 持有20日', sig)
        go('龙头带动 持有10日', sig, hold=10)
        go('龙头带动 & 大盘z>=1.0 持有20日', sig & mg10[:, None])
        go('  对照: 同日中小市值无雷、非龙头大涨行业 随机', bp & ~(B5 >= 0.05) & sig.any(1)[:, None])
        go('  对照: 大盘z>=1.0 同日中小市值无雷 随机', bp & ~(B5 >= 0.05) & (sig.any(1) & mg10)[:, None])
