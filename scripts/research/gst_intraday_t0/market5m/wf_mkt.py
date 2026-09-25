"""Morning score with whole-market context (DATA's 5-minute bars of all A-shares) vs the 16-stock average.
Both variants are walk-forward from 2020 (the 5-minute data start): each year is traded with models fitted on
2020..previous year only. Decision times 10:00 and 10:30, sell first when the prediction <= -20 bp."""
from wf import *
import duckdb, glob, os
H=os.environ['HOME']
M=duckdb.connect().execute(f"select date::varchar, hhmm, ew_pc, ew_open, up_share, down_share from read_parquet('{H}/research/mkt/mkt5_*.parquet')").fetchall()
mk={(d,h):(a,b,u,dn) for d,h,a,b,u,dn in M}
first_bar={}
for d,h,a,b,u,dn in M:
    if h=='0935': first_bar[d]=(a,b)
def whole(t):
    h=t.replace(':','')
    arr=np.array([mk.get((d,h),(np.nan,)*4) for d in date],dtype=float)
    fb=np.array([first_bar.get(d,(np.nan,np.nan)) for d in date],dtype=float)
    mgap=(1+fb[:,0])/(1+fb[:,1])-1          # whole-market average opening gap (approx.)
    return arr[:,0],arr[:,1],arr[:,2],mgap
def run_variant(variant,times=('10:00','10:30'),thr=20,years=('2021','2022','2023','2024'),lam=0.01):
    n=len(sym); net=np.full(n,np.nan); taken=np.zeros(n,bool)
    cache={}
    for t in times:
        i=T(t); X,names=feats(i); p=C[:,i]; o=np.where(np.isnan(O[:,i+1]),p,O[:,i+1]); y=(C[:,-1]/o-1)*1e4
        if variant!='16':
            ew,ewo,up,mg=whole(t)
            X=X.copy(); X[:,names.index('mkt')]=ew; X[:,names.index('mkt_open')]=ewo; X[:,names.index('mgap')]=mg
            if variant=='whole+breadth': X=np.column_stack([X,up])
        ok=np.isfinite(X).all(1)&np.isfinite(y)&px8&(p>lim_dn+0.011)&(p<lim_up-0.011)&(date>='2020-01-01')
        cache[t]=(X,y,ok,o)
    for yr in years:
        fitm=(date<f'{yr}-01-01')&(date>='2020-01-01'); trade=year==yr
        for t in times:
            X,y,ok,o=cache[t]; mo=fit(X,y,ok&fitm,lam); pr=pred(mo,X)
            s=ok&trade&~taken&(pr<=-thr)
            net[s]=((o[s]-tick)/C[s,-1]-1)*1e4-fees[s]; taken|=s
    return net,taken
for v in ('16','whole','whole+breadth'):
    net,tk=run_variant(v)
    show(f'{v:14s} WF 2021-24',net,tk,None,years=('2021','2022','2023','2024'))
    for part,ys in (('2021-22',('2021','2022')),('2023-24',('2023','2024'))):
        m=tk&np.isin(year,ys); mean,tt,nn=clustered(net,m); b=net[m]; w=b[b>0]; l=b[b<=0]
        print(f'      {part}: n={nn} trip={mean:+.1f} t={tt:+.2f} win={len(w)/len(b):.2f} payoff={w.mean()/-l.mean():.2f}')
