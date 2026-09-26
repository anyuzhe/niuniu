"""Swing exits for intraday breakout entries (正T): sell after one up-wave instead of holding to the close.
Exit rules, checked bar by bar on 5-minute bars (stop before target inside a bar, conservative):
  tp   take-profit limit at entry*(1+tp), filled at max(open, target) once high >= target + 1 tick
  sl   stop at entry*(1-sl), filled at min(open, stop) - 1 tick
  tr   (activate, giveback): once the high has reached entry*(1+activate), sell when price falls giveback from the peak
  tb   time limit in bars (sell at that bar's close - 1 tick); otherwise sell at the close.
Also records MFE/MAE (best high / worst low within 30 minutes) against same-date same-bar entries in all universe stocks.
Research only."""
import sys, os, pickle, itertools, numpy as np
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); only=sys.argv[2].split(',') if len(sys.argv)>2 else None
D=lib5.load(yr); C,O,Hh,L,V,pc,m=D['C'],D['O'],D['H'],D['L'],D['V'],D['pc'],D['mret']; n=len(C); TICK=lib5.TICK
volr=V/np.where(D['vs20']>0,D['vs20'],np.nan)
prevmaxC=np.c_[np.full((n,1),-np.inf),np.maximum.accumulate(C,1)[:,:-1]]
prevmaxH=np.c_[np.full((n,1),np.inf),np.maximum.accumulate(Hh,1)[:,:-1]]
def plat(k):
    ph=np.full((n,48),np.nan); pl=np.full((n,48),np.nan)
    for i in range(k,48): ph[:,i]=Hh[:,i-k:i].max(1); pl[:,i]=L[:,i-k:i].min(1)
    return ph,pl
ph6,pl6=plat(6); ph12,pl12=plat(12)
def mdp(N): l=D[f'pH{N}']; w=(l-D[f'pL{N}'])/D[f'pL{N}']; return (C>l[:,None])&(prevmaxC<=l[:,None]),w
b5,w5=mdp(5); b10,w10=mdp(10)
dm=np.c_[np.full((n,3),np.nan),(1+m[:,3:])/(1+m[:,:-3])-1]
fixed=lambda i: np.eye(48,dtype=bool)[i][None,:].repeat(n,0)
RULES={
 'A1 30分钟平台≤2%+放量1.5+大盘红':((((ph6-pl6)/pc[:,None]<=0.02)&(C>ph6)&(volr>=1.5)&(m>0)),6),
 'A2 60分钟平台≤1.5%+放量2':((((ph12-pl12)/pc[:,None]<=0.015)&(C>ph12)&(volr>=2)),12),
 'B1 5日平台≤6%+大盘红':((b5&(w5<=0.06)[:,None]&(m>0)),1),
 'B2 10日平台≤10%+放量2':((b10&(w10<=0.10)[:,None]&(volr>=2)),1),
 'C1 放量2倍破昨高+大盘红':(((C>D['pH1'][:,None])&(prevmaxC<=D['pH1'][:,None])&(volr>=2)&(m>0)),6),
 'C2 放量3倍创日内新高':(((C>prevmaxH)&(volr>=3)),6),
 'C3 放量3倍创新高+大盘涨≥1%':(((C>prevmaxH)&(volr>=3)&(m>=0.01)),6),
 'D1 大盘15分钟急涨≥0.5%':(((dm>=0.005)&(np.cumsum(dm>=0.005,1)==1)),3),
 'Z1 10:05随机买':(fixed(6),6),
 'Z2 11:05随机买':(fixed(18),18),
}
if only: RULES={k:v for k,v in RULES.items() if k.split()[0] in only}
# same-date same-bar reference MFE/MAE (all stocks)
fut=6
Hf=np.full((n,48),np.nan); Lf=np.full((n,48),np.nan)
for e in range(48):
    Hf[:,e]=Hh[:,e:min(e+fut,48)].max(1)/O[:,e]-1; Lf[:,e]=L[:,e:min(e+fut,48)].min(1)/O[:,e]-1
ud,inv=np.unique(D['date'],return_inverse=True)
refH=np.zeros((len(ud),48)); refL=np.zeros((len(ud),48)); cnt=np.bincount(inv)
for e in range(48): refH[:,e]=np.bincount(inv,np.nan_to_num(Hf[:,e]))/cnt; refL[:,e]=np.bincount(inv,np.nan_to_num(Lf[:,e]))/cnt
def sim(r,e,ent,tp,sl,tr,tb):
    k=len(r); px=np.full(k,np.nan); openm=np.ones(k,bool); peak=ent.copy()
    stamp=D['stamp'][r]
    for j in range(48):
        act=openm&(j>=e)
        if not act.any(): 
            if j>e.max(): break
            continue
        o=O[r,j];h=Hh[r,j];l=L[r,j]
        lvl=ent*(1-sl) if sl else np.full(k,-np.inf)
        if tr: lvl=np.where(peak>=ent*(1+tr[0]),np.maximum(lvl,peak*(1-tr[1])),lvl)
        hs=act&(l<=lvl); px[hs]=np.minimum(o,lvl)[hs]-TICK; openm&=~hs; act&=~hs
        if tp:
            tg=ent*(1+tp); ht=act&(h>=tg+TICK); px[ht]=np.maximum(o,tg)[ht]; openm&=~ht; act&=~ht
        if tb:
            tt=act&(j-e+1>=tb); px[tt]=C[r,j][tt]-TICK; openm&=~tt; act&=~tt
        peak=np.where(j>=e,np.maximum(peak,h),peak)
    px[openm]=C[r[openm],-1]-TICK
    return (px/ent-1)*1e4-(5+stamp+0.2)
out={}
TP=(0.005,0.01,0.015,0.02,0.03,None); SL=(0.005,0.01,0.02); TR=(None,(0.005,0.003),(0.01,0.005)); TB=(6,12,None)
for name,(sig,first) in RULES.items():
    s=sig.copy(); s[:,:first]=False; s[:,45:]=False
    has=s.any(1); i=np.argmax(s,1); r=np.flatnonzero(has); e=i[r]+1; ent=O[r,e]+TICK
    ok=(ent<D['up'][r]-0.005)&(V[r,e]>0); r,e,ent=r[ok],e[ok],ent[ok]
    d=inv[r]
    mf=(1+Hf[r,e])*O[r,e]/ent-1
    ma=(1+Lf[r,e])*O[r,e]/ent-1
    out[(name,'mfe')]=dict(n=len(r),mfe=np.nansum(mf),mae=np.nansum(ma),rmfe=refH[d,e].sum(),rmae=refL[d,e].sum())
    for tp,sl,tr,tb in itertools.product(TP,SL,TR,TB):
        bp=sim(r,e,ent,tp,sl,tr,tb); k=np.isfinite(bp); bp=bp[k]; dd=D['date'][r[k]]
        u,iv=np.unique(dd,return_inverse=True); w=bp>0
        out[(name,tp,sl,tr,tb)]=dict(n=len(bp),s=bp.sum(),nw=int(w.sum()),sw=bp[w].sum(),sl=bp[~w].sum(),dates=u,ds=np.bincount(iv,bp),dc=np.bincount(iv),ss=(bp**2).sum())
tag='_'.join(only) if only else 'all'
pickle.dump(out,open(f'{os.environ["HOME"]}/research/brk/ex_{tag}_{yr}.pkl','wb')); print(yr,tag,len(out))
