"""Research only: per-year returns, D vs D + idle cash in gold/bond-half ETFs (cap 100% / 40% / 30% of equity), 2017-08 on."""
import sys, io, contextlib, numpy as np
VAR = sys.argv[1] if len(sys.argv) > 1 else 'D'
sys.argv = [sys.argv[0], VAR]
with contextlib.redirect_stdout(io.StringIO()):
    exec(open('grp58.py', encoding='utf-8').read())
s = (R['GOLD'] + R['BOND']) / 2
v = base & np.isfinite(s) & (np.arange(nd) >= int(np.searchsorted(dates, '2017-08-07')))
def run(f, thr=0.2, cost=0.0005, s=s):
    w = 0.0; wt = np.zeros(nd)
    for t in range(nd):
        a = min(idle[t], f)
        if w > idle[t] + 1e-12: w = idle[t]
        elif a - w > thr + 1e-12: w = a
        wt[t] = w
    dw = np.abs(np.diff(np.r_[0.0, wt])); return rD + wt * np.nan_to_num(s) - cost * dw + (idle - wt) * CY
cols = {f'{VAR} 单独': rD + idle * CY, f'{VAR}+ETF 上限40%': run(0.4), f'{VAR}+仅国债 上限40%': run(0.4, s=R['BOND']), f'{VAR}+ETF 上限30%': run(0.3), f'{VAR}+ETF 不设上限': run(1.0), '纯持有黄金/国债': s, '纯持有沪深300': R['HS300']}
R_ = None
print(f'######## {VAR}  闲置资金放 黄金/国债各一半；2017-08 起；单边成本 5bp')
print('年份 ' + ' '.join(f'{k:>16s}' for k in cols))
tot = {k: 1.0 for k in cols}
for y in range(2017, 2027):
    m = (yr == y) & v
    if not m.any(): continue
    vals = {k: np.prod(1 + np.nan_to_num(r[m])) - 1 for k, r in cols.items()}
    for k in cols: tot[k] *= 1 + vals[k]
    tag = f'{y}' + ('(8月起)' if y == 2017 else '(1-9月)' if y == 2026 else '')
    print(f'{tag:10s} ' + ' '.join(f'{vals[k]*100:+15.1f}%' for k in cols))
n = v.sum()
print('全期年化   ' + ' '.join(f'{(np.prod(1+np.nan_to_num(r[v]))**(245/n)-1)*100:+15.1f}%' for r in cols.values()))
print('最大回撤   ' + ' '.join(f'{(np.cumprod(1+np.nan_to_num(r[v]))/np.maximum.accumulate(np.cumprod(1+np.nan_to_num(r[v])))-1).min()*100:+15.0f}%' for r in cols.values()))
for k in (f'{VAR}+ETF 上限40%',):
    a = cols[k]; b = cols[f'{VAR} 单独']
    d = [(np.prod(1+a[(yr==y)&v])-np.prod(1+b[(yr==y)&v]))*100 for y in range(2017, 2027) if ((yr==y)&v).any()]
    print('ETF 上限40% 相对 D 单独的逐年差（点）：', ' '.join(f'{x:+.1f}' for x in d), f'| 赢 {sum(x>0 for x in d)} 年 / 输 {sum(x<0 for x in d)} 年')
