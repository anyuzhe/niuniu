"""1-minute check (2026-05-21..09-24, tdx_kline_min1, 2026 top-500 universe): breakout entries with tight swing exits.
Signal at a 1-minute bar close, buy next bar open + 1 tick; exits as in exits.py but on 1-minute bars. Research only."""
import duckdb, os, json, itertools, pickle, numpy as np, time
H=os.environ['HOME']; TICK=0.01
U=json.load(open(f'{H}/research/mkt/universe.json'))['2026']
files=[f"{H}/mnt/lake/bronze/provider=tdx/kline_min1/{c.replace('.','_')}.parquet" for c in U]
files=[f for f in files if os.path.exists(f)]
c=duckdb.connect(); c.execute("set temp_directory='/tmp/duck'")
t=time.time()
slots=None; parts=[]
for f in files:
    x=c.execute("""select code, date::varchar d, substr(time,9,4) hm, open, high, low, close, volume::double v
      from read_parquet(?) where date>='2026-04-20' and substr(time,9,4)<>'0930' order by date, time""",[f]).fetchnumpy()
    if len(x['d'])==0: continue
    parts.append(x)
slots=sorted(set(parts[0]['hm'].tolist())|set(parts[1]['hm'].tolist())); assert len(slots)==240,len(slots); si={s:i for i,s in enumerate(slots)}
nrows=[len(np.unique(p['d'])) for p in parts]; n=sum(nrows)
G={k:np.full((n,240),np.nan,np.float32) for k in 'OHLCV'}
code=np.empty(n,object); date=np.empty(n,object); base=0
for p,nr in zip(parts,nrows):
    ud,inv=np.unique(p['d'],return_inverse=True); cl=np.array([si[h] for h in p['hm']])
    for k,src in (('O','open'),('H','high'),('L','low'),('C','close'),('V','v')): G[k][base+inv,cl]=p[src]
    code[base:base+nr]=p['code'][0]; date[base:base+nr]=ud; base+=nr
del parts
code=code.astype(str); date=date.astype(str)
O,Hh,L,C,V=G['O'],G['H'],G['L'],G['C'],np.nan_to_num(G['V']); del G
for i in range(240):
    m=np.isnan(C[:,i]); C[m,i]=O[m,i] if i==0 else C[m,i-1]
O=np.where(np.isnan(O),C,O);Hh=np.where(np.isnan(Hh),C,Hh);L=np.where(np.isnan(L),C,L)
def lag(x,s):
    out=np.full(x.shape,np.nan); out[s:]=x[:-s]; out[np.r_[np.ones(s,bool),code[s:]!=code[:-s]]]=np.nan; return out
dc=C[:,-1]; pc=lag(dc,1); pH1=lag(Hh.max(1),1)
V5=np.c_[np.zeros((n,4)),np.lib.stride_tricks.sliding_window_view(V,5,axis=1).sum(-1)]
cs0=np.r_[np.zeros((1,240)),np.cumsum(V5,0)]; r=np.arange(n); v20=np.full((n,240),np.nan); k=r[20:]
v20[k]=(cs0[k]-cs0[k-20])/20; v20[np.r_[np.ones(20,bool),code[20:]!=code[:-20]]]=np.nan
volr=(V5/np.where(v20>0,v20,np.nan)).astype(np.float32); del cs0,v20,V5
sel=(date>='2026-05-21')&~np.isnan(pc)&~np.isnan(C[:,0])
mk=c.execute(f"""select date::varchar d, replace(time,':','') t, ew_ret_prev_close x from read_parquet('{H}/mnt/lake/silver/market_intraday_breadth/freq=1m/year=*/*.parquet')""").fetchnumpy()
tbl={(a,b):x for a,b,x in zip(mk['d'],mk['t'],mk['x'])}
mret=np.full((n,240),np.nan,np.float32)
for d in np.unique(date[sel]):
    ix=np.flatnonzero(date==d); mret[ix]=np.array([tbl.get((d,s),np.nan) for s in slots])
print('load',round(time.time()-t,1),'rows',sel.sum(),'mkt nan',np.isnan(mret[sel]).mean().round(3))
up=np.round(pc*(1+np.where(np.char.startswith(code,'sz.30')|np.char.startswith(code,'sh.688'),0.2,0.1))+1e-9,2)
prevmaxC=np.c_[np.full((n,1),-np.inf),np.maximum.accumulate(C,1)[:,:-1]]
prevmaxH=np.c_[np.full((n,1),np.inf),np.maximum.accumulate(Hh,1)[:,:-1]]
ph=np.full((n,240),np.nan,np.float32); pl=np.full((n,240),np.nan,np.float32)
from numpy.lib.stride_tricks import sliding_window_view as sw
ph[:,30:]=sw(Hh,30,axis=1)[:,:-1].max(-1); pl[:,30:]=sw(L,30,axis=1)[:,:-1].min(-1)
fixed=np.zeros((n,240),bool); fixed[:,35]=True
RULES={'A1 30分钟平台≤2%+放量1.5+大盘红':(((ph-pl)/pc[:,None]<=0.02)&(C>ph)&(volr>=1.5)&(mret>0),30),
       'C1 放量2倍破昨高+大盘红':((C>pH1[:,None])&(prevmaxC<=pH1[:,None])&(volr>=2)&(mret>0),30),
       'C2 放量3倍创日内新高':((C>prevmaxH)&(volr>=3),30),
       'Z1 10:05随机买':(fixed,30)}
def sim(r,e,ent,tp,sl,tr,tb):
    k=len(r); px=np.full(k,np.nan); openm=np.ones(k,bool); peak=ent.copy()
    for j in range(e.min(),240):
        act=openm&(j>=e)
        if not act.any(): continue
        o=O[r,j];h=Hh[r,j];l=L[r,j]
        lvl=ent*(1-sl)
        if tr: lvl=np.where(peak>=ent*(1+tr[0]),np.maximum(lvl,peak*(1-tr[1])),lvl)
        hs=act&(l<=lvl); px[hs]=np.minimum(o,lvl)[hs]-TICK; openm&=~hs; act&=~hs
        if tp:
            tg=ent*(1+tp); ht=act&(h>=tg+TICK); px[ht]=np.maximum(o,tg)[ht]; openm&=~ht; act&=~ht
        if tb:
            tt=act&(j-e+1>=tb); px[tt]=C[r,j][tt]-TICK; openm&=~tt
        peak=np.where(j>=e,np.maximum(peak,h),peak)
    px[openm]=C[r[openm],-1]-TICK
    return (px/ent-1)*1e4
out={}
for name,(sig,first) in RULES.items():
    s=sig.copy(); s[:,:first]=False; s[:,225:]=False; s&=sel[:,None]
    has=s.any(1); i=np.argmax(s,1); rr=np.flatnonzero(has); e=i[rr]+1; ent=O[rr,e]+TICK
    ok=(ent<up[rr]-0.005)&(V[rr,e]>0); rr,e,ent=rr[ok],e[ok],ent[ok]
    cost=5+5+0.2
    for tp,sl,tr,tb in itertools.product((0.003,0.005,0.01,0.015,0.02,None),(0.003,0.005,0.01,0.02),(None,(0.003,0.002),(0.005,0.003),(0.01,0.005)),(5,15,30,None)):
        g=sim(rr,e,ent,tp,sl,tr,tb); out[(name,tp,sl,tr,tb)]=(g,date[rr])
    print(name,len(rr),round(time.time()-t,1))
pickle.dump(out,open(f'{H}/research/brk/m1_2026.pkl','wb'))
