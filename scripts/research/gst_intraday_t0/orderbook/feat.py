import numpy as np, os, glob
H=os.environ['HOME']
TICK=0.01
HZ={'30s':10,'1m':20,'3m':60,'5m':100,'10m':200}
def load(sym):
    z=dict(np.load(f'{H}/research/ob/{sym}.npz',allow_pickle=True)); z['prev_close']=np.asarray(z['prev_close'],dtype=float)
    b1,a1=z['bid1_px'],z['ask1_px']
    ok=(b1>0)&(a1>0)&(a1>b1)
    z={k:v[ok] for k,v in z.items()}
    return z
def seg_ids(z):
    """contiguous segments: same date and no gap > 60 s (splits lunch)"""
    d=z['date']; t=z['t']
    new=np.r_[True,(d[1:]!=d[:-1])|(np.diff(t)>60)]
    return np.cumsum(new)-1
def shift(x,seg,k):
    """value k snapshots ahead (k>0) or behind (k<0) within the same segment, else nan"""
    n=len(x); out=np.full(n,np.nan)
    if k>0:
        out[:-k]=x[k:]; bad=np.r_[seg[k:]!=seg[:-k],np.ones(k,bool)]
    else:
        k=-k; out[k:]=x[:-k]; bad=np.r_[np.ones(k,bool),seg[k:]!=seg[:-k]]
    out[bad]=np.nan; return out
def features(z):
    seg=seg_ids(z)
    b1,a1=z['bid1_px'],z['ask1_px']; bv1,av1=z['bid1_vol'],z['ask1_vol']
    mid=(b1+a1)/2
    bv5=sum(z[f'bid{k}_vol'] for k in range(1,6)); av5=sum(z[f'ask{k}_vol'] for k in range(1,6))
    dv=np.r_[0,np.diff(z['cum_volume'])]; dv[np.r_[True,seg[1:]!=seg[:-1]]]=0; dv=np.maximum(dv,0)
    mid_prev=shift(mid,seg,-1)
    sgn=np.sign(z['last']-np.where(np.isnan(mid_prev),mid,mid_prev))   # trade above previous mid = buyer initiated
    flow=dv*sgn
    F={}
    F['imb1']=(bv1-av1)/(bv1+av1)
    F['imb5']=(bv5-av5)/(bv5+av5)
    F['spread_t']=(a1-b1)/TICK
    F['micro']=((b1*av1+a1*bv1)/(av1+bv1)-mid)/TICK
    for n in (10,20,100):
        cs=np.cumsum(flow); cv=np.cumsum(dv)
        f=cs-shift(cs,seg,-n); v=cv-shift(cv,seg,-n)
        F[f'flow{n}']=np.where(v>0,f/np.maximum(v,1),0)
        F[f'ret{n}']=(mid/shift(mid,seg,-n)-1)*1e4
    F['ret_pc']=(mid/z['prev_close']-1)*1e4
    T={h:(shift(mid,seg,k)/mid-1)*1e4 for h,k in HZ.items()}
    return F,T,mid,seg
