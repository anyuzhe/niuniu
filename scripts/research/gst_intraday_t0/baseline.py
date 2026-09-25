from lib import *
fees=5+stamp+0.2
px8=tick_bp<=12.5
for t in ['10:00','14:00']:
    i=T(t); o=np.where(np.isnan(O[:,i+1]),C[:,i],O[:,i+1])
    net=((o-tick)/C[:,-1]-1)*1e4-fees; raw=(o/C[:,-1]-1)*1e4
    for part,m in (('train',train),('test',test)):
        mm=m&px8
        print(t,'sell-first every day',part,'net',np.nanmean(net[mm]).round(1),'raw (no cost)',np.nanmean(raw[mm]).round(1),
              ' by year',' '.join(f"{y}:{np.nanmean(raw[mm&(year==y)]):+.0f}" for y in np.unique(year[mm])))
