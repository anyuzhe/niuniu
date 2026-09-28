"""Day-level market features known at 10:30 (from the yearly top-500 5-minute grid) and the target:
equal-weight return of the sample from 10:30 to the close. Research only."""
import sys, os, numpy as np, json
sys.path.insert(0,os.path.dirname(__file__)); import lib5
H=os.environ['HOME']; yr=int(sys.argv[1])
z=np.load(f'{H}/research/brk/g{yr}.npz'); U=json.load(open(f'{H}/research/mkt/universe.json'))[str(yr)]
rank={c:i for i,c in enumerate(U)}
code=z['code']; date=z['date']
O,Hh,L,C,V,A=(z[k].astype(float) for k in 'O H L C V A'.split())
for i in range(48):
    mm=np.isnan(C[:,i]); C[mm,i]=O[mm,i] if i==0 else C[mm,i-1]
O=np.where(np.isnan(O),C,O); Hh=np.where(np.isnan(Hh),C,Hh); L=np.where(np.isnan(L),C,L); V=np.nan_to_num(V); A=np.nan_to_num(A)
same=np.r_[False,code[1:]==code[:-1]]
pc=np.where(same,np.r_[np.nan,C[:-1,-1]],np.nan); pc[~(pc>0)]=np.nan; C[~(C>0)]=np.nan; O[~(O>0)]=np.nan
lim=np.where([ (c.startswith('sz.30') and d>='2020-08-24') or c.startswith('sh.688') for c,d in zip(code,date)],0.2,0.1)
dn=np.round(pc*(1-lim)+1e-9,2); up=np.round(pc*(1+lim)+1e-9,2)
# same-slot 20-day average volume per stock (prior days only)
cs0=np.r_[np.zeros((1,48)),np.cumsum(V,0)]; n=len(C); r=np.arange(n); vs20=np.full((n,48),np.nan)
k=r[20:]; vs20[k]=(cs0[k]-cs0[k-20])/20; vs20[np.r_[np.ones(20,bool),code[20:]!=code[:-20]]]=np.nan
big=np.array([rank.get(c,999)<100 for c in code])
days=np.unique(date); F={}
T=11  # 10:30 bar
ret=C/pc[:,None]-1; ret[~np.isfinite(ret)]=np.nan
for d in days:
    ix=np.flatnonzero((date==d)&np.isfinite(pc)&np.isfinite(C[:,T])&np.isfinite(C[:,47])&np.isfinite(O[:,0])&(V.sum(1)>0))
    if len(ix)<100: continue
    rt=ret[ix]; c=C[ix]; o=O[ix]
    f={}
    f['y']=np.mean(c[:,47]/c[:,T]-1)
    f['day']=np.mean(rt[:,47])
    f['m_pc']=np.mean(rt[:,T]); f['m_open']=np.mean(c[:,T]/o[:,0]-1); f['gap']=np.mean(o[:,0]/pc[ix]-1)
    f['m30']=np.mean(c[:,T]/c[:,5]-1); f['m15']=np.mean(c[:,T]/c[:,8]-1)
    f['up_share']=np.mean(rt[:,T]>0); f['dn3']=np.mean(rt[:,T]<-0.03); f['up3']=np.mean(rt[:,T]>0.03)
    f['near_ld']=np.mean(c[:,T]<=dn[ix]*1.02); f['near_lu']=np.mean(c[:,T]>=up[ix]*0.98)
    lowT=L[ix,:T+1].min(1); hiT=Hh[ix,:T+1].max(1)
    f['at_low']=np.mean(c[:,T]<=lowT*1.002); f['at_high']=np.mean(c[:,T]>=hiT*0.998)
    vw=A[ix,:T+1].sum(1)/np.maximum(V[ix,:T+1].sum(1),1); f['below_vwap']=np.mean(c[:,T]<vw)
    f['disp']=np.std(rt[:,T]); f['rng']=np.mean((hiT-lowT)/pc[ix])
    f['vr']=V[ix,:T+1].sum()/max(np.nansum(vs20[ix,:T+1]),1)
    br=np.c_[o[:,0]/pc[ix]-1,c[:,1:T+1]/c[:,:T]-1]; vv=V[ix,:T+1]; f['down_vol']=(vv*(br<0)).sum()/max(vv.sum(),1)
    b=big[ix]; f['big_small']=np.mean(rt[b,T])-np.mean(rt[~b,T]) if b.any() and (~b).any() else 0.
    F[d]=f
# previous-day features from the EW daily series (includes warm-up rows)
ds=sorted(F); dd=np.array(ds)
allday={d:(np.nanmean(ret[(date==d),47]), np.nanmean(C[date==d,47]/C[date==d,41]-1), np.nanmean(C[date==d,47]/C[date==d,T]-1)) for d in np.unique(date)}
alld=sorted(allday); pos={d:i for i,d in enumerate(alld)}
for d in ds:
    i=pos[d]; prev=[allday[alld[j]] for j in range(max(0,i-20),i)]
    F[d]['p_ret']=prev[-1][0] if prev else np.nan; F[d]['p_last30']=prev[-1][1] if prev else np.nan; F[d]['p_rest']=prev[-1][2] if prev else np.nan
    F[d]['p_5d']=np.nansum([p[0] for p in prev[-5:]]) if len(prev)>=5 else np.nan
    F[d]['p_vol20']=np.nanstd([p[0] for p in prev]) if len(prev)>=15 else np.nan
    import datetime as dt; F[d]['wd']=dt.date.fromisoformat(d).weekday()
keys=sorted(next(iter(F.values())).keys())
out={'date':np.array([d for d in ds if d>=f'{yr}-01-01'])}
for k2 in keys: out[k2]=np.array([F[d][k2] for d in out['date']])
np.savez(f'{H}/research/brk/mf_{yr}.npz',**out); print(yr,len(out['date']))
