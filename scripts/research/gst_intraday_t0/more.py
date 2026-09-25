from family import *
fees=5+stamp+0.2
def event(tag,m,side,i,exit_slot=None):
    """side=-1 sell first at next open-1tick, buy back at close auction (or slot close+1tick); side=+1 buy first"""
    entry=Onext(i)+side*tick
    ex=C[:,-1] if exit_slot is None else C[:,exit_slot]-side*tick
    gross=side*(ex/entry-1)*1e4
    net=gross-fees
    mean,tt,n=clustered(net,m)
    ys=' '.join(f"{y}:{np.nanmean(net[m&(year==y)]):+.0f}({(m&(year==y)).sum()})" for y in np.unique(year[m]))
    print(f'{tag:45s} n={n:4d} gross={np.nanmean(gross[m]):+6.1f} net={mean:+6.1f} t={tt:+.1f}  {ys}')
i0=T('09:35')
gap=first_open/pc-1
tr=(C[:,i0]>lim_dn+0.011)&(C[:,i0]<lim_up-0.011)
base=train&px8&tr
for g in (.02,.03,.05):
    event(f'gap>=+{g:.0%} sell@09:35 buy close',base&(gap>=g),-1,i0)
    event(f'gap<=-{g:.0%} buy@09:35 sell close',base&(gap<=-g),+1,i0)
event('prev day ret>=9% sell@09:35',base&(prev_ret>=.09),-1,i0)
event('prev day ret<=-7% buy@09:35',base&(prev_ret<=-.07),+1,i0)
# volatility regimes for the 14:00 weak rule
i=T('14:00'); x=C[:,i]/pc-1
tr=(C[:,i]>lim_dn+0.011)&(C[:,i]<lim_up-0.011)
q=np.nanquantile(vol20[train],[1/3,2/3])
for lab,vm in (('low vol',vol20<=q[0]),('mid vol',(vol20>q[0])&(vol20<=q[1])),('high vol',vol20>q[1])):
    event(f'14:00 ret<=-3% {lab}',train&px8&tr&(x<=-.03)&vm,-1,i)
for k in (1.0,1.5,2.0):
    event(f'14:00 ret<=-{k} x avg range',train&px8&tr&(x<=-k*vol20),-1,i)
    event(f'10:30 ret<=-{k} x avg range',train&px8&((C[:,T("10:30")]>lim_dn+0.011))&((C[:,T("10:30")]/pc-1)<=-k*vol20),-1,T('10:30'))
print('vol20 terciles',q)
