import sys; sys.argv=['x','core']
exec(open('states2.py').read().split("P=run(")[0])
P=run('恐慌 E6 2x',zv<=-1.5,e6,L=2.0)
g2=(zv>-1.5)&(zv<=-1.0)
for nm,pool in (('最弱10%',loser),('E6池',e6)):
    for L in (1.0,2.0):
        W=run(f'(-1.5,-1.0] {nm} {L:g}x',g2,pool,L=L)
        rP=dr(P); rW=dr(W); m=np.isfinite(rP)&np.isfinite(rW)
        cstats(np.where(m,rP+rW,np.nan),f'   合并：恐慌2x + 该子策略{L:g}x (相关{np.corrcoef(rP[m],rW[m])[0,1]:.2f})')
# halves for the (-1.5,-1.0] loser 1x
W=run('(-1.5,-1.0] 最弱10% 1x 前半 2008-2016',g2,loser,start='2008-01-01')
yr=np.array([int(d[:4]) for d in dates]); r=dr(W)
for a,b in ((2008,2016),(2017,2026)):
    mm=(yr>=a)&(yr<=b)&np.isfinite(r); x=r[mm]; cum=np.cumprod(1+x); print(f'  {a}-{b}: 年化{(cum[-1]**(245/len(x))-1)*100:+.1f}% 夏普{x.mean()/x.std()*np.sqrt(245):+.2f} 回撤{(cum/np.maximum.accumulate(cum)-1).min()*100:.0f}%')
