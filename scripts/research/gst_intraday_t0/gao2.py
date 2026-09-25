from gao import *
fees=5+stamp+0.2; px8=tick_bp<=12.5
b,_=ols(r8,[r1,r7],tr)
pred=(b[0]+b[1]*r1+b[2]*r7)[inv]*1e4       # bp, market last-half-hour forecast, per stock row
i=T('14:30'); o=np.where(np.isnan(O[:,i+1]),C[:,i],O[:,i+1])
sell=((o-tick)/C[:,-1]-1)*1e4-fees; buy=(C[:,-1]/(o+tick)-1)*1e4-fees
ok=px8&(C[:,i]>lim_dn+0.011)&(C[:,i]<lim_up-0.011)
for thr in (5,10,15,20):
    for part,m in (('train',train),('test',test)):
        s=ok&m&(pred<=-thr); bb=ok&m&(pred>=thr)
        ms,ts,ns=clustered(sell,s); mb,tb,nb=clustered(buy,bb)
        print(f'pred<=-{thr}bp {part}: sell-first n={ns} {ms:+.1f} t={ts:+.1f} | pred>={thr}: buy-first n={nb} {mb:+.1f} t={tb:+.1f}')
