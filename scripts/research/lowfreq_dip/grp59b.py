"""Step 5 (research only): cap the ETF sleeve at a fixed fraction f of equity (rest stays cash earning 2%); forced sells only when D needs more than the cash buffer; buy back when gap>thr."""
import sys, io, contextlib, numpy as np
VAR = sys.argv[1] if len(sys.argv) > 1 else 'D'
sys.argv = [sys.argv[0], VAR]
with contextlib.redirect_stdout(io.StringIO()):
    exec(open('grp58.py', encoding='utf-8').read())
S['黄金/国债 各1/2'] = (R['GOLD'] + R['BOND']) / 2
s = S['黄金/国债 各1/2']; v = base & np.isfinite(s) & (np.arange(nd) >= int(np.searchsorted(dates, '2017-08-07'))); yrs = v.sum() / 245
def run(f, thr, cost):
    w = 0.0; wt = np.zeros(nd)
    for t in range(nd):
        a = min(idle[t], f)
        if w > idle[t] + 1e-12: w = idle[t]                      # must free cash for D (sell exactly what D needs)
        elif a - w > thr + 1e-12: w = a                          # buy back only when the gap is big enough
        wt[t] = w
    dw = np.abs(np.diff(np.r_[0.0, wt])); tot = rD + wt * np.nan_to_num(s) - cost * dw + (idle - wt) * CY
    return tot, dw, wt
print(f'######## {VAR}  闲置资金放 黄金/国债 各1/2，2017-08 起；基线 D 单独'); stat(rD + idle * CY, v, f'{VAR} 单独（闲置2%）')
for cost in (0.0005, 0.0010):
    print(f'--- 单边成本 {cost*1e4:.0f}bp')
    for f in (1.0, 0.6, 0.5, 0.4, 0.3, 0.2):
        for thr in (0.10, 0.20):
            tot, dw, wt = run(f, thr, cost); c, sh, dd = stat(tot, v, '', False)
            print(f'ETF 上限{f*100:3.0f}% 缺口>{thr*100:.0f}%买回  年化{c*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% | 平均仓位{wt[v].mean()*100:3.0f}% 每年单边换手{dw[v].sum()/yrs*100:4.0f}% 每年交易{int(np.sum((dw>1e-9)&v)/yrs):3d}天')
