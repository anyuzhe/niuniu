from wf import *
# market trend known before the open: 16-stock average of the previous 20 days' return (per stock, via close series)
ret_d=C[:,-1]/pc-1
def roll_prev_sum(x,n):
    out=np.full(len(x),np.nan)
    for s in np.unique(sym):
        ix=np.flatnonzero(sym==s); v=np.nan_to_num(x[ix]); cs=np.r_[0,np.cumsum(v)]
        for k in range(len(ix)):
            if k>=n: out[ix[k]]=cs[k]-cs[k-n]
    return out
tr20=dmean(roll_prev_sum(ret_d,20)); tr5=dmean(roll_prev_sum(ret_d,5))
times=['10:00','10:30']
# full-train fitted models, in-sample (train) — split by regime
net,tk,_=run(times,20,periods=[(train,train)])
for lab,m in (('mkt 20d up (>+2%)',tr20>0.02),('mkt 20d flat',(tr20>=-0.02)&(tr20<=0.02)),('mkt 20d down (<-2%)',tr20<-0.02),('nan',np.isnan(tr20))):
    mm=tk&m; mean,tt,n=clustered(net,mm)
    print('full-train in-sample',lab,n,round(mean,1),round(tt,2),' '.join(f"{y[2:]}:{np.nanmean(net[mm&(year==y)]):+.0f}({(mm&(year==y)).sum()})" for y in ('2019','2020','2021','2022')))
for lab,m in (('mkt 5d up',tr5>0.01),('mkt 5d flat',(tr5>=-0.01)&(tr5<=0.01)),('mkt 5d down',tr5<-0.01)):
    mm=tk&m; mean,tt,n=clustered(net,mm); print('full-train in-sample',lab,n,round(mean,1),round(tt,2))
print('share of stock-days by regime in years:',{y:(np.nanmean(tr20[year==y]>0.02).round(2),np.nanmean(tr20[year==y]<-0.02).round(2)) for y in np.unique(year)})
