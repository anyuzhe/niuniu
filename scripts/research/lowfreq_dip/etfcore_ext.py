"""Low-frequency rules on real ETFs with real costs (commission 2bp round trip, no stamp duty, 1 tick=0.001 each side). Research only.
Raw daily bars (tdx etf_kline_daily); any window touching a distribution/split day (+-1 day, from etf_nav) is dropped."""
import numpy as np, os, re, glob
import pyarrow.parquet as pq
H=os.environ['HOME']; LK=f'{H}/mnt/lake'
U=pq.read_table(f'{LK}/bronze/provider=tdx/etf_universe/latest.parquet').to_pandas()
U=U[U.selected&U.category.isin(['broad','sector','cross_border','gold'])&~U.symbol.isin(['sh.511220','sz.159398'])]
syms=list(U.symbol); cat=dict(zip(U.symbol,U.category))
def events(sym):
    f=f"{LK}/bronze/provider=eastmoney/etf_nav/{sym.replace('.','_')}.parquet"; ev=[]
    if not os.path.exists(f): return ev
    t=pq.read_table(f,columns=['date','distribution']).to_pandas()
    for d,s in zip(t.date.astype(str),t.distribution):
        if isinstance(s,str) and s and (re.search(r'派现金',s) or re.search(r'(分拆|折算)',s)): ev.append(d)
    return ev
tabs={}
for s in syms:
    t=pq.read_table(f"{LK}/bronze/provider=tdx/etf_kline_daily/{s.replace('.','_')}.parquet",columns=['date','open','high','low','close','volume','amount']).to_pandas()
    t['date']=t.date.astype(str); tabs[s]=t
dates=np.array(sorted(set().union(*[set(t.date) for t in tabs.values()]))); dates=dates[dates>='2007-01-04']
nd,nc=len(dates),len(syms); di={d:i for i,d in enumerate(dates)}
def mk(): return np.full((nd,nc),np.nan)
O,Hh,L,C,V,A=[mk() for _ in range(6)]; BAD=np.zeros((nd,nc),bool)
for j,s in enumerate(syms):
    t=tabs[s]; t=t[t.date.isin(di)]; ix=np.array([di[d] for d in t.date])
    O[ix,j]=t.open;Hh[ix,j]=t.high;L[ix,j]=t.low;C[ix,j]=t.close;V[ix,j]=t.volume;A[ix,j]=t.amount
    for d in events(s):
        k=np.searchsorted(dates,d)
        for q in (k-1,k,k+1,k+2):
            if 0<=q<nd: BAD[q,j]=True
fin=np.isfinite(C)&np.isfinite(O)&(V>0)
def shift(a,k): o=np.full_like(a,np.nan); o[k:]=a[:-k]; return o
def roll(a,n):
    z=np.where(np.isfinite(a),a,0.0); cnt=np.isfinite(a).astype(float)
    cs=np.vstack([np.zeros((1,nc)),np.cumsum(z,0)]); cc=np.vstack([np.zeros((1,nc)),np.cumsum(cnt,0)])
    s=np.full((nd,nc),np.nan); c=np.zeros((nd,nc)); s[n-1:]=cs[n:]-cs[:-n]; c[n-1:]=cc[n:]-cc[:-n]; s[c<n]=np.nan; return s
ret1=C/shift(C,1)-1; mom20=C/shift(C,20)-1; ret5=C/shift(C,5)-1; ret10=C/shift(C,10)-1
step=np.abs(C-shift(C,1)); eff20=(C-shift(C,20))/roll(step,20)
s1=roll(ret1,20); s2=roll(ret1**2,20); vol20=np.sqrt(np.maximum(s2-s1*s1/20,0)/19)
rng=Hh-L; cloc=np.where(rng>1e-9,(C-L)/np.where(rng>1e-9,rng,1),0.5)
amt20=roll(A,20)/20; listed=np.cumsum(np.isfinite(C),0)>=60
uni=fin&listed&(amt20>=3e7)
base=(mom20<-0.10)&(eff20<0)
r5=np.where(uni,ret5,np.nan); r20=np.where(uni,mom20,np.nan)
def topn(x,n,low=True):
    out=np.zeros_like(x,bool)
    for i in range(nd):
        r=x[i]; ok=np.isfinite(r)
        if ok.sum()<8: continue
        idx=np.argsort(r[ok] if low else -r[ok])[:n]; out[i,np.nonzero(ok)[0][idx]]=True
    return out
rules={'V1基准(20日跌>10%)':base,'V1候选(+效率>-0.5)':base&(eff20>-0.5),'R2收盘位置(<0.3)':base&(cloc<0.3),'R2低波动(<1.5%)':base&(vol20<0.015),
 'ETF尺度:5日跌≥3%':ret5<=-0.03,'ETF尺度:5日跌≥5%':ret5<=-0.05,'ETF尺度:10日跌≥5%':ret10<=-0.05,
 '截面反转:5日跌幅最大5只':topn(r5,5,True),'截面动量:20日涨幅最大5只':topn(r20,5,False)}
per={'2020-22':('2020-01-01','2022-12-31'),'2023-24':('2023-01-01','2024-12-31'),'2025-26':('2025-01-01','2026-12-31')}
lim=np.where(np.array([cat[s] for s in syms])=='xx',0.2,0.1)[None,:]
limup_open=(O/shift(C,1)-1)>=0.097; limdn_close=ret1<=-0.097
badc=np.cumsum(BAD,0)
mon=np.array([d[:7] for d in dates]); FEE=2e-4
def cl_t(x,g):
    u,inv=np.unique(g,return_inverse=True); m=x.mean(); s=np.bincount(inv,x-m); return m/(np.sqrt((s**2).sum())/len(x)+1e-18)
