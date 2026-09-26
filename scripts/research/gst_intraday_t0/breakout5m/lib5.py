"""Shared loading and trade evaluation for the breakout study (research only)."""
import numpy as np, os, duckdb, warnings
warnings.filterwarnings('ignore')
H=os.environ['HOME']
TICK=0.01
_mk={}
def market():
    if not _mk:
        c=duckdb.connect()
        r=c.execute(f"""select date::varchar d, replace(time,':','') t, ew_ret_prev_close x, up_count*1.0/n_stocks u
            from read_parquet('{H}/mnt/lake/silver/market_intraday_breadth/freq=5m/year=*/*.parquet')""").fetchnumpy()
        _mk.update(r)
    return _mk
def load(yr):
    z=np.load(f'{H}/research/brk/g{yr}.npz')
    code=z['code'];date=z['date'];slots=[str(s) for s in z['slots']]
    O,Hh,L,C,V,A=(z[k].astype(np.float64) for k in 'O H L C V A'.split())
    # fill within day
    for i in range(48):
        m=np.isnan(C[:,i])
        if i==0: C[m,0]=O[m,0]
        else: C[m,i]=C[m,i-1]
    ok=~np.isnan(C[:,0])
    O=np.where(np.isnan(O),C,O);Hh=np.where(np.isnan(Hh),C,Hh);L=np.where(np.isnan(L),C,L);V=np.nan_to_num(V);A=np.nan_to_num(A)
    n=len(code)
    def lag(x,s):
        out=np.full(x.shape,np.nan); 
        if s<n:
            out[s:]=x[:-s]; bad=np.r_[np.ones(s,bool),code[s:]!=code[:-s]]; out[bad]=np.nan
        return out
    dh=Hh.max(1);dl=L.min(1);dc=C[:,-1];dv=V.sum(1)
    pc=lag(dc,1)
    def lead(x):
        out=np.full(x.shape,np.nan); out[:-1]=x[1:]; out[:-1][code[1:]!=code[:-1]]=np.nan; return out
    nO=lead(O[:,0]); nC=lead(dc)
    pc2=lag(dc,2); pc6=lag(dc,6); pdv=lag(dv,1); pH1_=lag(dh,1); pL1_=lag(dl,1)
    lim0=np.where(np.char.startswith(code.astype(str),'sz.30')&(date>='2020-08-24')|np.char.startswith(code.astype(str),'sh.688'),0.2,0.1)
    prevLU=pc>=np.round(pc2*(1+lim0)+1e-9,2)-0.001
    # 20-day beta of 5-minute returns to the whole market (prior days only)
    prevH={N:np.nanmax(np.stack([lag(dh,s) for s in range(1,N+1)]),0) for N in (1,5,10,20)}
    prevL={N:np.nanmin(np.stack([lag(dl,s) for s in range(1,N+1)]),0) for N in (5,10,20)}
    full={N:np.all(np.stack([~np.isnan(lag(dh,s)) for s in range(1,N+1)]),0) for N in (5,10,20)}
    for N in (5,10,20): prevH[N][~full[N]]=np.nan; prevL[N][~full[N]]=np.nan
    cs=np.cumsum(V,0); vs20=np.full(V.shape,np.nan)
    # prior 20 days excluding today: sum rows r-20..r-1
    cs0=np.r_[np.zeros((1,48)),cs]  # cs0[k]=sum rows<k
    vs20=np.full(V.shape,np.nan); r=np.arange(20,n)
    vs20[r]=(cs0[r]-cs0[r-20])/20; bad=np.r_[np.ones(20,bool),code[20:]!=code[:-20]]; vs20[bad]=np.nan
    dv20=np.nansum(vs20,1); dv20[bad]=np.nan
    iny=z['iny']&ok&~np.isnan(pc)
    M=market()
    mret=np.full((n,48),np.nan); mup=np.full((n,48),np.nan)
    dates=np.unique(date); mk=list(M)
    tbl={}
    for d,t,x,u in zip(M['d'],M['t'],M['x'],M['u']): tbl[(d,t)]=(x,u)
    dm={}
    for d in dates:
        dm[d]=np.array([tbl.get((d,s),(np.nan,np.nan)) for s in slots])
    for d in dates:
        ix=np.flatnonzero(date==d); mret[ix]=dm[d][:,0]; mup[ix]=dm[d][:,1]
    rm=np.c_[np.zeros(n),(1+mret[:,1:])/(1+mret[:,:-1])-1]; rs=np.c_[np.zeros(n),C[:,1:]/C[:,:-1]-1]
    cov=np.nansum(rs*rm,1); var=np.nansum(rm*rm,1)
    cc=np.r_[0,np.cumsum(cov)]; vv=np.r_[0,np.cumsum(var)]; r20=np.arange(n); beta=np.full(n,np.nan)
    k=r20[20:]; beta[k]=(cc[k]-cc[k-20])/(vv[k]-vv[k-20]); beta[np.r_[np.ones(20,bool),code[20:]!=code[:-20]]]=np.nan
    sel=iny
    lim=np.where(np.char.startswith(code.astype(str),'sz.30')&(date>='2020-08-24')|np.char.startswith(code.astype(str),'sh.688'),0.2,0.1)
    up=np.round(pc*(1+lim)+1e-9,2)
    stamp=np.where(date>='2023-08-28',5.0,10.0)
    D=dict(code=code,date=date,O=O,H=Hh,L=L,C=C,V=V,A=A,pc=pc,up=up,stamp=stamp,vs20=vs20,dv20=dv20,
           mret=mret,mup=mup,beta=beta,pc2=pc2,pc6=pc6,pdv=pdv,pL1=pL1_,prevLU=prevLU,nO=nO,nC=nC,slots=slots,**{f'pH{N}':prevH[N] for N in prevH},**{f'pL{N}':prevL[N] for N in prevL})
    return {k:(v[sel] if isinstance(v,np.ndarray) and v.shape[0]==n else v) for k,v in D.items()}

def trades(D,sig,first=6,last=46,exit='close',stop=None,trail=None):
    """sig: bool (n,48) signal at bar close. Enter first signal in [first,last] at next bar open + 1 tick.
    exit 'close' = last bar close - 1 tick; stop: price level array (n,) -> fill min(open,stop)-tick at first bar
    whose low <= stop; trail: fraction from running high since entry. Returns rows, entry col, net bp."""
    s=sig.copy(); s[:,:first]=False; s[:,last+1:]=False
    has=s.any(1); i=np.argmax(s,1); r=np.flatnonzero(has); e=i[r]+1
    O,Hh,L,C=D['O'],D['H'],D['L'],D['C']
    ent=O[r,e]+TICK
    okb=(ent<D['up'][r]-0.005)&(D['V'][r,e]>0)
    r,e,ent=r[okb],e[okb],ent[okb]
    px=C[r,-1]-TICK
    if exit=='nextopen': px=D['nO'][r]-TICK
    if exit=='nextclose': px=D['nC'][r]-TICK
    if stop is not None or trail is not None:
        cols=np.arange(48)
        after=cols[None,:]>=e[:,None]
        lvl=np.full((len(r),48),-np.inf)
        if stop is not None:
            st=stop[r,e-1] if stop.ndim==2 else stop[r]
            lvl=np.maximum(lvl,st[:,None])
        if trail is not None:
            runh=np.maximum.accumulate(np.where(after,Hh[r],-np.inf),1)
            # stop level for bar j uses running high up to bar j-1
            rh=np.r_['1',np.full((len(r),1),-np.inf),runh[:,:-1]]
            rh=np.where(rh==-np.inf,ent[:,None],np.maximum(rh,ent[:,None]))
            lvl=np.maximum(lvl,rh*(1-trail))
        hit=after&(L[r]<=lvl)&(cols[None,:]<47)
        hh=hit.any(1); j=np.argmax(hit,1)
        k=np.flatnonzero(hh)
        px[k]=np.minimum(O[r[k],j[k]],lvl[k,j[k]])-TICK
    cost=2*2.5+D['stamp'][r]+0.2
    bp=(px/ent-1)*1e4-cost
    k=np.isfinite(bp); r,e,bp=r[k],e[k],bp[k]
    trades.gross=bp+cost[k]
    return r,e,bp

def stats(D,r,bp,years=None):
    if len(r)<20: return None
    d=D['date'][r]
    u,inv=np.unique(d,return_inverse=True); s=np.bincount(inv,bp)
    # date-clustered t: treat day sums
    n=len(bp); m=bp.mean()
    res=np.bincount(inv,bp-m); se=np.sqrt((res**2).sum())/n
    w=bp>0; payoff=bp[w].mean()/-bp[~w].mean() if w.any() and (~w).any() else np.nan
    return dict(n=n,days=len(u),bp=m,win=w.mean(),payoff=payoff,t=m/se if se>0 else np.nan)
