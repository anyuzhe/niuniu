"""Fine holding-period sweep for industry panic (is 20 days a sharp peak?), also on the market-panic E6 strategy and the simple z<=-1 control. Research only."""
from grp7 import *
R, A = ind_series(l1); Z = zscore(R); base = np.isfinite(Z) & (Z <= -1.5)
fm, fc = build(base, l1)
print('=== 行业恐慌(无过滤) 1x，持有期细扫；2009-07 起 / 2008 起', flush=True)
for hd in (10, 12, 14, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 28, 30, 35, 40, 50, 60):
    a = run2('', fm, fc, hold=hd, start='2009-07-01', quiet=True); b = run2('', fm, fc, hold=hd, quiet=True)
    print(f'持有{hd:2d}日  2009-07起 年化{a[0]*100:+5.1f}% 夏普{a[1]:+.2f}  | 2008起 年化{b[0]*100:+5.1f}% 夏普{b[1]:+.2f}', flush=True)
print('=== 原策略(大盘z<=-1.5 + E6) 1x', flush=True)
for hd in (5, 10, 15, 20, 25, 30, 40, 60):
    cfg = DipConfig(leverage=1.0, hold_days=hd); r = simulate(panel, market, cand, cfg); st = summarize(panel, market, r, cfg)['stats']
    print(f'持有{hd:2d}日 年化{st["cagr"]*100:+5.1f}% 夏普{st["sharpe"]:+.2f} 回撤{st["max_drawdown"]*100:4.0f}% 仓位{st["exposure"]*100:3.0f}%', flush=True)
print('=== 简单对照(大盘z<=-1.0, 无E6, 最弱20只) 1x', flush=True)
g = np.isfinite(market.z) & (market.z <= -1.0)
fm2 = Market(mret=market.mret, mk20=market.mk20, z=np.where(g, -9.0, 9.0), count=market.count); fc2 = Candidates(uni=cand.uni, e6=cand.uni & np.isfinite(cand.ret20), buyok=cand.buyok, ret20=cand.ret20)
for hd in (5, 10, 15, 20, 25, 30, 40, 60):
    cfg = DipConfig(leverage=1.0, hold_days=hd); r = simulate(panel, fm2, fc2, cfg); st = summarize(panel, fm2, r, cfg)['stats']
    print(f'持有{hd:2d}日 年化{st["cagr"]*100:+5.1f}% 夏普{st["sharpe"]:+.2f} 回撤{st["max_drawdown"]*100:4.0f}% 仓位{st["exposure"]*100:3.0f}%', flush=True)
