import numpy as np, os
H=os.environ['HOME']
z=np.load(os.environ.get('GST_GRID', f'{H}/research/grid.npz'))
sym=z['sym'];date=z['date'];pc=z['prev_close'];auc=z['auction'];slots=list(z['slots'])
def ffill(a):
    a=a.copy()
    for i in range(1,a.shape[1]):
        m=np.isnan(a[:,i]); a[m,i]=a[m,i-1]
    return a
C=ffill(z['C']); O=z['O']
first_open=np.where(np.isnan(auc),O[:,0],auc)
C[:,0]=np.where(np.isnan(C[:,0]),first_open,C[:,0]); C=ffill(C)
V=np.nan_to_num(z['V']);A=np.nan_to_num(z['A']);B=np.nan_to_num(z['B']);S=np.nan_to_num(z['S'])
Hh=np.where(np.isnan(z['H']),C,z['H']);L=np.where(np.isnan(z['L']),C,z['L'])
cumV=np.cumsum(V,1);cumA=np.cumsum(A,1);cumB=np.cumsum(B,1);cumS=np.cumsum(S,1)
VW=np.where(cumV>0,cumA/np.maximum(cumV,1),C)
HI=np.maximum.accumulate(Hh,1);LO=np.minimum.accumulate(L,1)
T=lambda s: slots.index(s)
train=date<='2022-12-31'; test=~train
close=C[:,-1]
# previous-day features within each symbol (rows are sorted by sym,date)
same=np.r_[False,sym[1:]==sym[:-1]]
prev_ret=np.where(same,np.r_[np.nan,(close/pc)[:-1]]-1,np.nan)  # note: pc is adjusted prev close of the next day
day_ret=close/pc-1
rng=(HI[:,-1]-LO[:,-1])/pc
def roll_mean_prev(x,n=20):
    out=np.full(len(x),np.nan)
    for s in np.unique(sym):
        ix=np.flatnonzero(sym==s); v=x[ix]
        cs=np.r_[0,np.cumsum(np.nan_to_num(v))]
        for k in range(len(ix)):
            if k>=n: out[ix[k]]=(cs[k]-cs[k-n])/n
    return out
vol20=roll_mean_prev(rng)          # average daily range of the previous 20 days
volu20=roll_mean_prev(cumV[:,-1])  # average daily volume previous 20 days
tick=0.01
stamp=np.where(date>='2023-08-28',5.0,10.0)
def cost_bp(ticks_per_side=1.0,commission_bp=2.5,price=None):
    price=C[:,0] if price is None else price
    return 2*ticks_per_side*tick/price*1e4+2*commission_bp+stamp+0.2
def fwd(t,e):
    """return (bp) from slot t close to slot e close"""
    return (C[:,e]/C[:,t]-1)*1e4
def clustered(x,mask):
    """mean and t-stat with date clustering"""
    m=mask&np.isfinite(x)
    if m.sum()<30: return np.nan,np.nan,int(m.sum())
    d=date[m];v=x[m]
    u,inv=np.unique(d,return_inverse=True)
    s=np.bincount(inv,v);n=np.bincount(inv)
    per=s/n  # per-date mean
    # weight by count for mean, cluster-robust se
    mean=v.mean()
    resid=np.bincount(inv,v-mean)
    se=np.sqrt((resid**2).sum())/len(v)
    return mean, mean/se if se>0 else np.nan, int(m.sum())
rate=np.full(len(sym),0.10)
rate[(np.char.startswith(sym.astype(str),'sz.300'))&(date>='2020-08-24')]=0.20
rate[(sym=='sh.601777')&(date>='2020-08-25')&(date<='2021-04-23')]=0.05
lim_up=np.round(pc*(1+rate),2); lim_dn=np.round(pc*(1-rate),2)
tick_bp=tick/C[:,0]*1e4
year=np.array([d[:4] for d in date])
