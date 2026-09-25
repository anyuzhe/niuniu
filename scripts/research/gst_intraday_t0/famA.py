from family import *
res=[]
for t in ['13:30','14:00','14:30']:
    for mc in (-.01,-.015,-.02):
        for thr in (0.0,-.02,-.03):
            m,net=run(t,thr,mc,show=False)
            mean,tt,n=clustered(net,m)
            yrs=[np.nanmean(net[m&(year==y)]) for y in ('2019','2020','2021','2022')]
            res.append((t,mc,thr,n,mean,tt,min(yrs),yrs))
res.sort(key=lambda r:-r[5])
for r in res: print(r[0],f'mkt<={r[1]:.1%}',f'stock<={r[2]:.0%}',f'n={r[3]}',f'net={r[4]:+.1f}',f't={r[5]:+.1f}','years',' '.join(f'{v:+.0f}' for v in r[7]))
