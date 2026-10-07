import json, numpy as np
d = json.load(open('grp62_exec.json'))
YEARS = 6.7
def pct(x): return f'{x*100:+.2f}%'
for name in ('D', 'D1'):
    R = d[name]; n = len(R)
    A = lambda k: np.array([r[k] if r[k] is not None else np.nan for r in R], float)
    REL = {'A': 0.08, 'C': 0.08, 'B': 0.025}
    w = np.array([REL[r['sleeve']] for r in R]); ret, op = A('ret'), A('op')
    print(f'===== {name}  n={n}  年数≈{YEARS}')
    print('一致性：分钟开盘/日线开盘-1 中位数', np.nanmedian(A('o_match')), ' |差|>0.5%占比', np.nanmean(np.abs(A('o_match')) > 0.005),
          '| 分钟收盘/日线收盘-1 |差|>0.5%占比', np.nanmean(np.abs(A('c_match')) > 0.005))
    print('基准：开盘买 平均每笔(扣成本后回测) ', pct(np.mean(ret)),)
    for lab, k in (('09:35收盘', 'c0935'), ('10:00收盘', 'p1000'), ('前30分VWAP', 'vw30'), ('全天VWAP', 'vwd'), ('收盘价', 'cl')):
        X = A(k); ok = np.isfinite(X) & (X > 0)
        # entry-price ratio effect: (1+r_X) = (1+r)*op/X
        dr = (1 + ret) * op / X - 1 - ret
        print(f'  买入改在{lab:8s}: 每笔Δ {pct(np.mean(dr[ok]))}  (价格比开盘 {pct(np.mean((X/op-1)[ok]))})  组合年化Δ ≈ {np.sum((w*dr)[ok])/YEARS*100:+.2f} 点/年  n={ok.sum()}')
    # intraday low
    lo = A('lo'); print(f'  参考：当天最低价比开盘 {pct(np.mean(lo/op-1))}（做不到，只说明恐慌日开盘后平均回落多深）')
    # per sleeve open vs 10:00 / close
    for s in ('A', 'C', 'B'):
        m = np.array([r['sleeve'] == s for r in R])
        if m.sum() < 10: continue
        print(f'  sleeve {s}: n={m.sum()}  开盘→10:00 {pct(np.mean((A("p1000")/op-1)[m]))}  开盘→收盘 {pct(np.mean((A("cl")/op-1)[m]))}')
    # fill realism
    gap, lim = A('gap'), A('lim')
    near = gap >= lim - 0.03
    print(f'  开盘离涨停不足3%的买入: {near.sum()} 笔 ({near.mean()*100:.1f}%)，其中平均开盘→收盘 {pct(np.mean((A("cl")/op-1)[near])) if near.any() else "-"}')
    b1 = A('bar1_amt'); size = w * 400000
    part = size / b1
    print(f'  开盘首根5分钟成交额中位数 {np.median(b1)/1e4:.0f} 万；按 40 万本金下单占比 中位数 {np.median(part)*100:.2f}% p95 {np.percentile(part,95)*100:.2f}% 最大 {part.max()*100:.2f}%  >5%的笔数 {(part>0.05).sum()}  >20%的笔数 {(part>0.2).sum()}')
    for cap in (400000, 4000000, 40000000):
        pp = (w*cap)/b1
        print(f'    本金 {cap/1e4:.0f} 万：占首根5分钟成交额 中位数 {np.median(pp)*100:.1f}% p95 {np.percentile(pp,95)*100:.1f}%  >20%的笔数 {(pp>0.2).sum()}')
    # exit limit-down
    ld = np.array([r['ld'] for r in R]); nx = A('nx_open')
    print(f'  卖出日收盘跌停: {ld.sum()} 笔 ({ld.mean()*100:.1f}%)；顺延到次日开盘卖的平均价差 {pct(np.nanmean(nx[ld])) if ld.any() else "-"}；组合年化Δ ≈ {np.nansum((w*nx)[ld])/YEARS*100:+.2f} 点/年')
    # by year
    yrs = sorted(set(r['year'] for r in R))
    print('  逐年(开盘→10:00 / 开盘→收盘 / 前30分VWAP相对开盘) :', end=' ')
    for y in yrs:
        m = np.array([r['year'] == y for r in R])
        print(f"{y}[{m.sum()}]: {np.mean((A('p1000')/op-1)[m])*100:+.2f}/{np.mean((A('cl')/op-1)[m])*100:+.2f}/{np.mean((A('vw30')/op-1)[m])*100:+.2f}", end='  ')
    print()
    # significance: t-stat of op->vw30 and op->p1000
    for lab, k in (('10:00', 'p1000'), ('前30分VWAP', 'vw30'), ('收盘', 'cl')):
        z = (A(k) / op - 1); z = z[np.isfinite(z)]
        print(f'  t({lab} vs 开盘) = {np.mean(z)/ (np.std(z, ddof=1)/np.sqrt(len(z))):.2f}', end='; ')
    print()
