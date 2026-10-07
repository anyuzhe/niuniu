import sys, io, contextlib, numpy as np
sys.argv = [sys.argv[0], 'D']
with contextlib.redirect_stdout(io.StringIO()):
    exec(open('grp58.py', encoding='utf-8').read())
s = (R['GOLD'] + R['BOND']) / 2
w = 0.0; wt = np.zeros(nd)
for t in range(nd):
    a = min(idle[t], 0.4)
    if w > idle[t] + 1e-12: w = idle[t]
    elif a - w > 0.2 + 1e-12: w = a
    wt[t] = w
mo = np.array([d[:7] for d in dates])
print('月份   黄金   国债   ETF平均仓位  D仓位  ETF贡献(占净值)  D收益  ')
for m in sorted(set(mo[(yr == 2026)])):
    k = (mo == m) & np.isfinite(rD)
    g = np.prod(1 + np.nan_to_num(R['GOLD'][k])) - 1; b = np.prod(1 + np.nan_to_num(R['BOND'][k])) - 1
    contrib = np.sum(wt[k] * np.nan_to_num(s[k])); dret = np.prod(1 + rD[k]) - 1
    print(f'{m} {g*100:+6.1f}% {b*100:+6.1f}%  {wt[k].mean()*100:5.0f}%  {np.r_[0,ex[:-1]][k].mean()*100:5.0f}%  {contrib*100:+6.2f}%  {dret*100:+6.1f}%')
k = (yr == 2026) & np.isfinite(rD)
print('2026 黄金', (np.prod(1+np.nan_to_num(R['GOLD'][k]))-1)*100, '国债', (np.prod(1+np.nan_to_num(R['BOND'][k]))-1)*100)
# worst single days of gold in 2026
gi = np.nonzero(k)[0]; o = gi[np.argsort(R['GOLD'][gi])[:5]]; print('黄金最差5日', [(dates[i], round(R['GOLD'][i]*100,1), round(wt[i]*100)) for i in o])
