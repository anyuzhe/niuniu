"""Which intraday windows are choppy? Per 30/60-minute window: efficiency ratio |net move| / sum |5-min moves|,
lag-1 autocorrelation of 5-minute returns inside the window, and how often a 1% dip from the window start is
recovered to the start price by the close. Yearly top-500, 5-minute bars. Research only."""
import sys, os, numpy as np
sys.path.insert(0,os.path.dirname(__file__)); import lib5
W={'09:35-10:00':(0,5),'10:00-10:30':(6,11),'10:30-11:30':(12,23),'13:00-13:30':(24,29),'13:30-14:00':(30,35),'14:00-14:30':(36,41),'14:30-15:00':(42,47)}
acc={k:[] for k in W}
for yr in (2020,2022,2024,2026):
    D=lib5.load(yr); C=D['C']; L=D['L']; O=D['O']
    prev=np.c_[O[:,0],C[:,:-1]]; r=np.log(C/prev)
    for k,(s,e) in W.items():
        seg=r[:,s:e+1]; net=np.abs(seg.sum(1)); path=np.abs(seg).sum(1); er=np.where(path>0,net/path,np.nan)
        a=seg[:,:-1].ravel(); b=seg[:,1:].ravel(); ok=np.isfinite(a)&np.isfinite(b); ac=np.corrcoef(a[ok],b[ok])[0,1]
        ref=prev[:,s]; dip=(L[:,s:e+1].min(1)<=ref*0.99)
        hit=np.argmax(L[:,s:e+1]<=ref[:,None]*0.99,1)+s
        rec=np.array([ (D['H'][i,hit[i]+1:]>=ref[i]).any() if dip[i] else False for i in range(len(C))])
        acc[k].append((yr,np.nanmean(er),ac,dip.mean(),rec[dip].mean()))
print('时段        | 效率比(越低越震荡) | 5分钟收益前后相关(负=来回) | 跌1%的比例 | 跌1%后收盘前回到起点的比例')
for k,v in acc.items():
    print(k,' | '.join(f"{y}: {er:.2f} {ac:+.3f} {dp*100:4.1f}% {rc*100:3.0f}%" for y,er,ac,dp,rc in v))
