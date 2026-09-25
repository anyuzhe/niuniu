"""Close-auction exit scan: decide at the close of minute t, enter next minute open ±1 tick, exit at the close auction. Train only."""
from lib import *
fees=5+stamp+0.2
ud,inv=np.unique(date,return_inverse=True)
def dmean(x):
    s=np.bincount(inv,np.nan_to_num(x)*np.isfinite(x));n=np.bincount(inv,np.isfinite(x)); return (s/np.maximum(n,1))[inv]
gap=first_open/pc-1; mgap=dmean(gap)
rows=[]
for t in ['09:31','09:45','10:00','10:30','11:00','13:05','13:30','14:00','14:30']:
    i=T(t); p=C[:,i]
    o=np.where(np.isnan(O[:,i+1]),p,O[:,i+1])
    tot=cumB[:,i]+cumS[:,i]
    F={'ret_pc':p/pc-1,'ret_open':p/first_open-1,'vwap_dev':p/VW[:,i]-1,'mkt':dmean(p/pc-1),'mkt_open':dmean(p/first_open-1),
       'rel':p/pc-1-dmean(p/pc-1),'imb':np.where(tot>0,(cumB[:,i]-cumS[:,i])/np.maximum(tot,1),np.nan),'gap':gap,'mgap':mgap}
    tradable=(p>lim_dn+0.011)&(p<lim_up-0.011)
    for side in (1,-1):
        net=side*(C[:,-1]/(o+side*tick)-1)*1e4-fees
        for name,x in F.items():
            ok=train&tradable&np.isfinite(x)
            q=np.nanquantile(x[ok],[.05,.1,.9,.95])
            for lab,m in (('<=p5',x<=q[0]),('<=p10',x<=q[1]),('>=p90',x>=q[2]),('>=p95',x>=q[3])):
                mm=ok&m; mean,tt,n=clustered(net,mm)
                yrs=[np.nanmean(net[mm&(year==y)]) for y in ('2019','2020','2021','2022')]
                rows.append((t,'buy' if side>0 else 'sell',name,lab,n,mean,tt,sum(v>0 for v in yrs),np.nansum(net[mm])/ok.sum()))
rows.sort(key=lambda r:-r[6])
print('tests',len(rows))
for r in rows[:30]: print(r[0],r[1],r[2],r[3],'n',r[4],f'net={r[5]:+.1f} t={r[6]:+.1f} years+={r[7]}/4 per_stockday={r[8]:+.2f}')
