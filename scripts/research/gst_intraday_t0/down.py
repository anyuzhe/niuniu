from lib import *
cost=cost_bp()
e=T('14:50')
print('cost (1 tick/side, 万2.5) by price filter: all',np.nanmean(cost[train]).round(1),' price>=8:',np.nanmean(cost[train&(tick_bp<=12.5)]).round(1))
for t in ['10:00','10:30','11:00','13:30','14:00']:
    i=T(t); r=fwd(i,e); x=(C[:,i]/pc-1)*100; xz=(C[:,i]/pc-1)/vol20
    tradable=(C[:,i]>lim_dn+0.011)&(C[:,i]<lim_up-0.011)
    for thr in (-2,-3,-4,-5):
        for filt,fm in (('all',np.ones(len(sym),bool)),('px>=8',tick_bp<=12.5)):
            m=train&(x<=thr)&tradable&fm
            mean,tt,n=clustered(-r,m)   # sell first: gain = -r
            net=mean-np.nanmean(cost[m]) if n else np.nan
            ys=' '.join(f"{y}:{np.nanmean(-r[m&(year==y)]):+.0f}({(m&(year==y)).sum()})" for y in ('2019','2020','2021','2022'))
            print(t,f'ret<={thr}%',filt,n,f'{mean:+.1f} t={tt:+.1f} net={net:+.1f}',ys)
