"""Reference rows on the product engine: original market-panic E6 strategy vs simple 'market z<=th, weakest-20d stocks, no E6' at 1x/2x. Research only."""
from grp_lib import *
panel = load_panel(); market, cand = compute_features(panel, 5e7, 3.0)
def show(label, cfg, fm, fc):
    raw = simulate(panel, fm, fc, cfg); s = summarize(panel, fm, raw, cfg); st = s['stats']; tr = s['trades']; h = halves(panel, raw['eq']); mr = s['info']['min_margin_ratio']
    print(f"{label:46s} 触发{s['gate_days']:5d}天 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:+.2f} 回撤{st['max_drawdown']*100:4.0f}% 仓位{st['exposure']*100:3.0f}% 笔{tr['n']:5d} 笔均{tr['mean']*1e4:+4.0f}bp{'' if mr is None else f' 最低担保{mr*100:.0f}%'} | 前半{h[0]} 后半{h[1]}", flush=True)
for L in (1.0, 2.0):
    cfg = DipConfig(leverage=L); show(f'原策略 大盘z<=-1.5 + E6 {L:g}x', cfg, market, cand)
for th in (-1.5, -1.0):
    for L in (1.0, 1.5, 2.0):
        cfg = DipConfig(leverage=L)
        g = np.isfinite(market.z) & (market.z <= th)
        fm = Market(mret=market.mret, mk20=market.mk20, z=np.where(g, -9.0, 9.0), count=market.count)
        fc = Candidates(uni=cand.uni, e6=cand.uni & np.isfinite(cand.ret20), buyok=cand.buyok, ret20=cand.ret20)
        show(f'简单对照 大盘z<={th:g}, 无E6, 最弱20只 {L:g}x', cfg, fm, fc)
