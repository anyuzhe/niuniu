"""Combined 'first sell signal of the day' across decision times; one trip per stock-day; exit in the closing auction."""
from ridge_multi import *
import itertools
def combined(times,thr,models,period,buy_thr=None):
    n=len(sym); taken=np.zeros(n,bool); net=np.full(n,np.nan); when=np.full(n,'',object)
    for t in times:
        i=T(t); X=feats(i); p=C[:,i]; o=np.where(np.isnan(O[:,i+1]),p,O[:,i+1])
        ok=np.isfinite(X).all(1)&px8&(p>lim_dn+0.011)&(p<lim_up-0.011)&period&~taken
        pr=pred(models[t],X)
        s=ok&(pr<=-thr)
        net[s]=((o[s]-tick)/C[s,-1]-1)*1e4-fees[s]; taken|=s; when[s]=t
        if buy_thr:
            b=ok&(pr>=buy_thr)&~s
            net[b]=(C[b,-1]/(o[b]+tick)-1)*1e4-fees[b]; taken|=b; when[b]=t+'b'
    return net,taken,when
def summary(tag,net,taken,period):
    mean,tt,n=clustered(net,taken)
    ys=' '.join(f"{y[2:]}:{np.nanmean(net[taken&(year==y)]):+.0f}({(taken&(year==y)).sum()})" for y in np.unique(year[period]))
    print(f'{tag:40s} trips={n} per_trip={mean:+.1f} t={tt:+.1f} per_stockday={np.nansum(net[taken])/period.sum():+.2f}bp {ys}',flush=True)
if __name__=='__main__':
    # models fitted on 2019-2021 only, evaluated on 2022
    m21={}
    for t in TIMES:
        i=T(t); X=feats(i); p=C[:,i]; o=np.where(np.isnan(O[:,i+1]),p,O[:,i+1]); y=(C[:,-1]/o-1)*1e4
        ok=np.isfinite(X).all(1)&np.isfinite(y)&px8&(p>lim_dn+0.011)&(p<lim_up-0.011)
        m21[t]=fit(X,y,ok&(date<='2021-12-31'))
    val=train&(date>='2022-01-01'); fitp=date<='2021-12-31'
    for times in (TIMES,['10:00','10:30','13:30','14:00','14:30'],['13:30','14:00','14:30'],['14:00']):
        for thr in (20,30):
            for part,per in (('fit19-21',fitp),('val2022',val)):
                net,taken,_=combined(times,thr,m21,per)
                summary(f'{part} {",".join(times)} thr{thr}',net,taken,per)
