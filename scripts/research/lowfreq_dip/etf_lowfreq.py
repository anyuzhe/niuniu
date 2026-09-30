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
dates=np.array(sorted(set().union(*[set(t.date) for t in tabs.values()]))); dates=dates[dates>='2019-06-03']
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
print('ETF数',nc,'日期',dates[0],dates[-1],'每日可交易ETF均值',round(uni.sum(1)[100:].mean(),1), '其中2020-22/2023-24/2025-26:',[round(uni[(dates>=a)&(dates<=b)].sum(1).mean(),1) for a,b in per.values()])
tickrel=0.001/np.where(np.isfinite(C),C,np.nan); print('每边1个价位占价格：中位',np.nanmedian(tickrel[uni])*1e4,'bp  (往返+佣金 ≈',np.nanmedian(tickrel[uni])*2e4+2,'bp)')
T=np.arange(nd); jj=np.arange(nc)[None,:]
for Hd in (3,5,10,20):
    ei=np.tile(np.minimum(T+Hd,nd-1)[:,None],(1,nc)); okx=(T+Hd<nd)
    for _ in range(3):
        bad=~fin[ei,jj]|limdn_close[ei,jj]; ei=np.where(bad&(ei<nd-1),ei+1,ei)
    exC=C[ei,jj]
    enO=np.full((nd,nc),np.nan); enO[:-1]=O[1:]; enC1=np.full((nd,nc),np.nan); enC1[:-1]=C[1:]
    buy_ok=np.zeros((nd,nc),bool); buy_ok[:-1]=fin[1:]&~limup_open[1:]
    winbad=(badc[np.minimum(ei,nd-1),jj]-badc[np.maximum(T-1,0)[:,None],jj])>0
    valid=uni&buy_ok&okx[:,None]&np.isfinite(exC)&np.isfinite(enO)&~winbad
    gross=exC/enO-1
    net=(exC-0.001)/(enO+0.001)-1-FEE
    bm=np.nanmean(np.where(valid,gross,np.nan),1)
    print(f'\n===== 持有 {Hd} 天（次日开盘买、第{Hd}天收盘卖；佣金2bp+每边1个价位）=====')
    for name,rm in rules.items():
        line=[]
        for pn,(a,b) in per.items():
            dm=(dates>=a)&(dates<=b); mm=valid&rm&dm[:,None]
            if mm.sum()<30: line.append(f'{pn}: 样本不足({mm.sum()}笔)'); continue
            di_,ci_=np.nonzero(mm); x=net[di_,ci_]; xe=x-bm[di_]; g=mon[di_]; w=x>0
            pay=x[w].mean()/-x[~w].mean() if w.any() and (~w).any() else np.nan
            line.append(f'{pn}: {len(x):5d}笔/{len(np.unique(di_)):3d}天 净{x.mean()*1e4:+6.0f}bp(t{cl_t(x,g):+.1f}) 超额{xe.mean()*1e4:+6.0f}(t{cl_t(xe,g):+.1f}) 胜率{w.mean()*100:.0f}% 赔率{pay:.2f}')
        print(name+'\n    '+'\n    '.join(line))
    line=[]
    for pn,(a,b) in per.items():
        dm=(dates>=a)&(dates<=b); mm=valid&dm[:,None]; di_,ci_=np.nonzero(mm)
        line.append(f'{pn}: 平均毛{gross[di_,ci_].mean()*1e4:+.0f}bp 扣成本{net[di_,ci_].mean()*1e4:+.0f}bp')
    print('  ETF随机持有 '+' | '.join(line))
