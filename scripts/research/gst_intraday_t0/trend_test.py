"""One pre-registered trend-breakout rule, chosen on 2019-2022 only: 30-minute opening-range breakdown (sell first)
when the 16-stock average is down >= 1% and the breakout minute's volume >= 3x yesterday's average minute volume;
buy back in the closing auction. Evaluated once on 2023-2024."""
from trend import *
px8=tick_bp<=12.5
r=np.arange(len(sym))
hit=events('or30',-1); net=trade(hit,-1); ok=hit>=0; i=np.where(ok,hit,0)
m=px8&ok&(-mkt_pc[r,i]>0.01)&filt(hit,-1,'vol')
for lab,per,ys in (('train',train,('2019','2020','2021','2022')),('test',test,('2023','2024'))):
    rep(f'or30 short mkt<-1% vol3x {lab}',net,per&m,ys)
    mm=per&m&np.isfinite(net); b=net[mm]; w=b[b>0]; l=b[b<=0]
    print('   win',round(len(w)/len(b)*100),'% payoff',round(w.mean()/-l.mean(),2))
