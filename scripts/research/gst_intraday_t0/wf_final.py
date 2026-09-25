"""Final walk-forward: morning score (10:00, 10:30), sell-first when prediction <= -20 bp, exit in the closing auction.
Each year is traded with models fitted on all earlier years only. 2021-2022 chose the design; 2023-2024 are the test."""
from wf import *
import json
times=['10:00','10:30']
Y=('2021','2022','2023','2024')
net,tk,_=run(times,20,years=Y)
show('walk-forward morning thr20',net,tk,None,years=Y)
for part,ys in (('2021-22 (design)',('2021','2022')),('2023-24 (test)',('2023','2024'))):
    m=tk&np.isin(year,ys); mean,tt,n=clustered(net,m); print(part,n,round(mean,1),'t',round(tt,2),'per stock-day bp',round(np.nansum(net[m])/np.isin(year,ys).sum(),2))
# models for the product: fitted on all data before each year of use
out={}
for use in ('2021','2022','2023','2024','2025'):
    out[use]={}
    for t in times:
        i=T(t); X,names=feats(i); p=C[:,i]; o=np.where(np.isnan(O[:,i+1]),p,O[:,i+1]); y=(C[:,-1]/o-1)*1e4
        ok=np.isfinite(X).all(1)&np.isfinite(y)&px8&(p>lim_dn+0.011)&(p<lim_up-0.011)
        mu,sd,w,b=fit(X,y,ok&(date<f'{use}-01-01'))
        out[use][t]={'mu':[float('%.10g'%v) for v in mu],'sd':[float('%.10g'%v) for v in sd],'w':[float('%.10g'%v) for v in w],'b':float('%.10g'%b)}
json.dump({'names':names,'models':out},open('morning_wf_models.json','w'))
print('saved models for years',list(out))
