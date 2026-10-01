"""Stage 1: factor rows + forward labels on deep-panic days (market EW 20d return <= -6%). Research only."""
import numpy as np, warnings; warnings.filterwarnings('ignore')
import swingbook as S
from swingbook import *
mk=np.load('mkreg.npz'); mk20=mk['mk20']; mret=mk['mret']; assert (mk['dates']==dates).all()
import gc
for nm in ('ent','sigb','golden','dead','body','shadow','hl','align','sd20','dif','dea','lo20p','hi20p','minL3','vma3p','c4','m5','m10','E6','lim','early','eff20','mom20','bo','valid','buy_ok','rng_'):
    if hasattr(S,nm): delattr(S,nm)
    globals().pop(nm,None)
gc.collect()
Dsel=np.nonzero((mk20<=-0.06)&(np.arange(nd)<nd-26)&(np.arange(nd)>260))[0]
print('panic days',len(Dsel),flush=True)
cand_t=(uni&lst250&(R>=3)&~limdn_close)[Dsel]
e=Dsel+1
okbuy=(fin[e]&~limup_open[e]&~ldo[e])
cand=cand_t&okbuy
print('candidates/day',cand.sum(1).mean(),flush=True)
jj=np.arange(nc)[None,:]
lab={}
for H in (10,20):
    x=e+H-1; xi=np.repeat(x[:,None],nc,1)
    for _ in range(3):
        bad=~fin[np.minimum(xi,nd-1),jj]|limdn_close[np.minimum(xi,nd-1),jj]
        xi=np.where(bad&(xi<nd-1),xi+1,xi)
    Cx=C[np.minimum(xi,nd-1),jj]; o=O[e]; rawE=Ro[e]; rawX=rawE*Cx/o
    gross=Cx/o-1; net=Cx*(1-0.01/rawX)/(o*(1+0.01/rawE))-1-FEE
    lab[f'gross{H}']=gross.astype(np.float32); lab[f'net{H}']=net.astype(np.float32)
for nm in ('O','Hh','L','V','Ro','ret1','limup_open','limdn_close','ldo','fin','TS' ):
    pass
del O,Hh,V,Ro,ldo,limup_open,limdn_close,fin,uni
gc.collect()
def X(p): return np.asarray(p[Dsel],dtype=np.float32)
F={}
c3=sh(c,3); c5=sh(c,5); c10=sh(c,10); c20=sh(c,20); c25=sh(c,25); c60=sh(c,60)
F['ret1']=X(c/c1-1); F['ret3']=X(c/c3-1); F['ret5']=X(c/c5-1); F['ret10']=X(c/c10-1); F['ret20']=X(c/c20-1); F['ret60']=X(c/c60-1)
F['mom_old(t-25→t-5)']=X(c5/c25-1)
F['dist_hi20']=X(c/hi20-1); F['dist_lo20']=X(c/lo20-1)
h60=rmax(h,60); F['dist_hi60']=X(c/h60-1); del h60
F['dist_ma20']=X(c/m20-1); F['dist_ma60']=X(c/m60-1); F['dist_ma120']=X(c/m120-1)
F['rsi3']=X(rsi3); F['rsi14']=X(rsi14); F['pctB']=X((c-blo)/np.where(bup>blo,bup-blo,np.nan))
F['vol20']=X(vol20); F['atr14%']=X(rmean(h-l,14)/c)
F['logamt20']=X(np.log(amt20.astype(np.float32)+1)); F['logprice']=X(np.log(R.astype(np.float32)))
F['volratio_today']=X(v/vma20p); F['volratio5/60']=X(rmean(v,5)/rmean(v,60))
F['cloc']=X(cloc); hl_=h-l; F['lower_shadow']=X((np.minimum(c,o_)-l)/np.where(hl_>0,hl_,np.nan)); F['gap_open']=X(o_/c1-1)
F['age']=X(np.log(np.cumsum(np.isfinite(C),0).astype(np.float32)+1))
# beta60 / downside beta
r=ret1.astype(np.float64); mm=np.repeat(mret[:,None],nc,1); rz=np.where(np.isfinite(r),r,0.0); n=60
Er=roll(rz,n)/n; Em=roll(mm,n)/n; Erm=roll(rz*mm,n)/n; Emm=roll(mm*mm,n)/n
beta=(Erm-Er*Em)/np.maximum(Emm-Em*Em,1e-12); F['beta60']=X(np.clip(beta,-1,4)); 
# idiosyncratic vol
resid2=(rz-beta*mm)**2; F['idiovol60']=X(np.sqrt(roll(resid2,n)/n)); del Er,Em,Erm,Emm,beta,resid2,rz,mm,r
# relative drawdown vs market: stock ret20 minus market ret20 is same ordering as ret20 -> skipped
# market (all-stock EW incl. everything valid) path for reference
np.savez_compressed('pp_feat.npz',Dsel=Dsel,cand=cand,dates=dates[Dsel],mk20=mk20[Dsel],codes=codes,fnames=np.array(list(F.keys())),**{'F_'+k:v for k,v in F.items()},**lab)
print('saved',list(F.keys()),flush=True)
