import numpy as np
import grp56 as m
for lab, ev in (('B 平 A+C', {'B': 'AC'}), ('A:B C:B B:AC', {'A': 'B', 'C': 'B', 'B': 'AC'}), ('A 平 C+B (对照)', {'A': 'BC'})):
    el, tl = [], []; eq, ex, n, ntr = m.fused3(evict=ev, evlog=el, tlog=tl); s = m.stats(eq, ex)
    print(f'\n=== {lab}: 年化{s["cagr"]*100:+.1f}% 夏普{s["sharpe"]:.2f} 回撤{s["dd"]*100:.0f}% 提前平仓{n} 笔 / 自然到期 {len(tl)} 笔', flush=True)
    e = np.array([(x[2] == 'A', x[2] == 'C', x[2] == 'B', x[3], x[4], x[5] if x[5] is not None else np.nan, x[6]) for x in el], float)
    for k, nm in enumerate('ACB'):
        z = e[e[:, k] == 1]
        if len(z): print(f'  被平的 {nm} 仓位 {len(z):5d} 笔  平均已持有 {z[:,3].mean():4.1f} 天  平仓时累计 {z[:,4].mean()*1e4:+5.0f}bp  卖出实得(扣成本) {z[:,6].mean()*1e4:+5.0f}bp  若持有到期本应 {np.nanmean(z[:,5])*1e4:+5.0f}bp')
    t = np.array([(x[0], x[1], x[2]) for x in tl if x[1] is not None], dtype=object)
    for nm in 'ACB':
        z = [x[1] for x in tl if x[0] == nm and x[1] is not None]; d = [x[2] for x in tl if x[0] == nm and x[1] is not None]
        if z: print(f'  自然到期的 {nm} 仓位 {len(z):5d} 笔  持有 {np.mean(d):4.1f} 天  平均收益 {np.mean(z)*1e4:+5.0f}bp')
    ages = e[:, 3]; print(f'  被平仓位持有天数分布: 0-2天 {np.mean(ages<=2)*100:.0f}%  3-5天 {np.mean((ages>2)&(ages<=5))*100:.0f}%  6-10天 {np.mean((ages>5)&(ages<=10))*100:.0f}%  >10天 {np.mean(ages>10)*100:.0f}%')
