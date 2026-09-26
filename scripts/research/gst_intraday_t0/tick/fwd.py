"""After a tick-level sprint signal: forward mid-price move (ticks) and the chance that the bid later exceeds the
entry ask (needed to profit when buying at the ask and selling at the bid). Research only."""
import numpy as np, glob, os
H=os.environ['HOME']; TK=0.01
LOW={'sh.601777','sz.000563','sz.000592','sz.300040'}
HZ=(1,5,10,20,100)  # snapshots ahead (~3s,15s,30s,60s,5min)
acc={}
import sys, pickle
for f in sys.argv[1:]:
    z=np.load(f); sym=os.path.basename(f)[:9]
    for dd in np.unique(z['date']):
        m=z['date']==dd
        if m.sum()<500: continue
        p=z['last'][m];b=z['bid1_px'][m];a=z['ask1_px'][m];cv=z['cum_volume'][m]; n=len(p)
        ok=(a>0)&(b>0); mid=np.where(ok,(a+b)/2,np.nan)
        dv=np.r_[0,np.diff(cv)].clip(0); cs=np.r_[0,np.cumsum(dv)]; idx=np.arange(n); lo=np.maximum(idx-100,0)
        avg=(cs[idx]-cs[lo])/np.maximum(idx-lo,1)
        sigs={'放量5倍+价升(3秒)':(dv>=5*np.maximum(avg,1))&(p-np.r_[np.nan,p[:-1]]>=TK-1e-9),
              '放量5倍+价升(9秒)':((cs[idx+1]-cs[np.maximum(idx-2,0)])>=15*np.maximum(avg,1))&(p-np.r_[np.full(3,np.nan),p[:-3]]>=TK-1e-9),
              '随机时点':(idx%97==0)}
        for nm,s in sigs.items():
            s=s&(idx>=100)&(idx<n-101)&ok
            i=np.flatnonzero(s)
            if len(i)==0: continue
            g='低价' if sym in LOW else '其他'
            row=[np.nanmean((mid[i+h]-mid[i])/TK) for h in HZ]+[np.nanmean((mid[i+h]-mid[i+1])/TK) for h in HZ]
            # best bid within next 100 snapshots vs ask at entry (i+1)
            from numpy.lib.stride_tricks import sliding_window_view as sw
            fm=np.full(n,np.nan); fm[:n-101]=sw(b[2:],99).max(1)[:n-101]; bb=fm[i]; win=np.mean(bb>=a[i+1]+TK-1e-9); win0=np.mean(bb>=a[i+1]-1e-9)
            acc.setdefault((nm,g),[]).append((len(i),row,win,win0,np.nanmean((a[i+1]-b[i+1])/TK)))
pickle.dump(acc,open(f'{H}/research/tick/fw_{os.path.basename(sys.argv[1])[:9]}.pkl','wb'))
if 0:
 for k,v in []:
    N=sum(x[0] for x in v); w=lambda j: sum(x[0]*x[1][j] for x in v)/N
    print(f"{k[0]:14s} {k[1]} n{N:7d} | 信号后中间价变动(价位) 3秒{w(0):+.2f} 15秒{w(1):+.2f} 30秒{w(2):+.2f} 1分{w(3):+.2f} 5分{w(4):+.2f}"
          f" | 进场后 3秒{w(5):+.2f} 1分{w(8):+.2f} 5分{w(9):+.2f} | 进场价差{sum(x[0]*x[4] for x in v)/N:.2f}价位"
          f" | 5分钟内买一曾≥买入价+1价位 {sum(x[0]*x[2] for x in v)/N*100:.0f}%，≥买入价 {sum(x[0]*x[3] for x in v)/N*100:.0f}%")
