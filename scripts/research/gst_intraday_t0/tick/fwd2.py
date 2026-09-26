"""Per stock: after a 9-second volume sprint (volume >= 5x the 5-minute average, price up >= 1 tick), buy at the next
snapshot's ask; forward mid move in ticks and in bp, and net bp when selling at the bid after 15 s / 1 min / 5 min.
Research only."""
import numpy as np, sys, os
TK=0.01
f=sys.argv[1]; z=np.load(f); sym=os.path.basename(f)[:9]
acc=dict(n=0,tk=np.zeros(3),bp=np.zeros(3),net=np.zeros(3),win=np.zeros(3),spread=0.0,price=0.0,rn=0,rnet=np.zeros(3))
HZ=(5,20,100)
for dd in np.unique(z['date']):
    m=z['date']==dd
    if m.sum()<500: continue
    p=z['last'][m];b=z['bid1_px'][m];a=z['ask1_px'][m];cv=z['cum_volume'][m]; n=len(p)
    ok=(a>0)&(b>0)&(a>b); mid=(a+b)/2
    dv=np.r_[0,np.diff(cv)].clip(0); cs=np.r_[0,np.cumsum(dv)]; idx=np.arange(n); lo=np.maximum(idx-100,0)
    avg=(cs[idx]-cs[lo])/np.maximum(idx-lo,1)
    s=((cs[idx+1]-cs[np.maximum(idx-2,0)])>=15*np.maximum(avg,1))&(p-np.r_[np.full(3,np.nan),p[:-3]]>=TK-1e-9)&(idx>=100)&(idx<n-101)
    for kind,sig in (('s',s),('r',(idx%97==0)&(idx>=100)&(idx<n-101))):
        i=np.flatnonzero(sig)
        i=i[ok[i]&ok[np.minimum(i+1,n-1)]]
        good=np.all([ok[i+1+h] for h in HZ],0); i=i[good]
        if len(i)==0: continue
        e=a[i+1]
        nets=np.array([(b[i+1+h]/e-1)*1e4-10.2 for h in HZ])
        if kind=='s':
            acc['n']+=len(i); acc['spread']+=((a[i+1]-b[i+1])/TK).sum(); acc['price']+=p[i].sum()
            acc['tk']+=np.array([((mid[i+1+h]-mid[i])/TK).sum() for h in HZ]); acc['bp']+=np.array([((mid[i+1+h]/mid[i]-1)*1e4).sum() for h in HZ])
            acc['net']+=nets.sum(1); acc['win']+=(nets>0).sum(1)
        else:
            acc['rn']+=len(i); acc['rnet']+=nets.sum(1)
N=acc['n']; R=acc['rn']
print(f"{sym} 价{acc['price']/N:6.1f} 1价位={100/(acc['price']/N):5.1f}bp 次数{N:6d} 买入价差{acc['spread']/N:.2f}价位 | 中间价 15秒/1分/5分: "
      +'/'.join(f"{x/N:+.2f}" for x in acc['tk'])+'价位 = '+'/'.join(f"{x/N:+.1f}" for x in acc['bp'])+'bp | 卖在买一净: '
      +'/'.join(f"{x/N:+.1f}" for x in acc['net'])+'bp 胜率 '+'/'.join(f"{x/N*100:.0f}%" for x in acc['win'])+' | 随机买入净: '+'/'.join(f"{x/R:+.1f}" for x in acc['rnet']))
