"""Step 4 (research only): threshold rebalancing of the ETF sleeve held with D's idle cash. Forced sells when D needs cash; buys only when idle-cash gap exceeds a threshold."""
import sys, io, contextlib, numpy as np
VAR = sys.argv[1] if len(sys.argv) > 1 else 'D'
sys.argv = [sys.argv[0], VAR]
with contextlib.redirect_stdout(io.StringIO()):
    exec(open('grp58.py', encoding='utf-8').read())
S['黄金/国债 各1/2'] = (R['GOLD'] + R['BOND']) / 2
def run(s, thr, cost, sell_buffer=0.0):
    w = 0.0; wt = np.zeros(nd); trades = 0
    for t in range(nd):
        a = idle[t]
        if w > a + 1e-12: w = max(a - sell_buffer, 0.0); trades += 1               # D needs the cash: forced sell (to a bit below, if buffer)
        elif a - w > thr + 1e-12 or (thr == 0 and a - w > 1e-12): w = a; trades += 1
        wt[t] = w
    dw = np.abs(np.diff(np.r_[0.0, wt]))
    tot = rD + wt * np.nan_to_num(s) - cost * dw + (idle - wt) * CY
    return tot, dw, wt, trades
def line(label, s, v, thr, cost, buf=0.0):
    tot, dw, wt, trades = run(s, thr, cost, buf); c, sh, dd = stat(tot, v, '', False); yrs = v.sum() / 245
    print(f'{label:34s} 年化{c*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% | ETF平均仓位{wt[v].mean()*100:3.0f}% 每年单边换手{dw[v].sum()/yrs*100:4.0f}% 每年调仓{int(np.sum((dw>1e-9)&v)/yrs):3d}次 成本拖累{dw[v].sum()/yrs*cost*1e4:3.0f}bp')
    return c
print(f'######## {VAR}')
for sname, start, extra in (('黄金/国债 各1/2', '2017-08-07', None), ('黄金', '2013-07-19', None), ('沪深300/黄金/国债 各1/3', '2017-08-07', None)):
    s = S[sname]
    if sname.startswith('沪深300/'):
        s = (trend(R['HS300']) + R['GOLD'] + R['BOND']) / 3; sname = '趋势沪深300/黄金/国债 各1/3'
    v = base & np.isfinite(s) & (np.arange(nd) >= int(np.searchsorted(dates, start)))
    print(f'\n===== 闲置资金放 {sname}：{dates[np.nonzero(v)[0][0]]} ~ {dates[np.nonzero(v)[0][-1]]}')
    stat(rD + idle * CY, v, f'{VAR} 单独（闲置2%）')
    for cost in (0.0005, 0.0010):
        print(f'--- 单边成本 {cost*1e4:.0f}bp')
        for thr in (0.0, 0.05, 0.10, 0.20, 0.30):
            line(f'每天调仓' if thr == 0 else f'缺口>{thr*100:.0f}% 才买入', s, v, thr, cost)
        line('缺口>20% 才买，卖时多卖 10%', s, v, 0.20, cost, 0.10)
