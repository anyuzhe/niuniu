"""大盘随动: when the whole market moves sharply within 15 minutes, trade high-beta stocks that have not followed yet.
Buy side (正T): market 15-min change >= +x -> buy laggard high-beta stocks, sell base at close.
Sell side (反T): market 15-min change <= -x -> sell base in laggard high-beta stocks at next open, buy back at close.
Research only."""
import sys, os, pickle, itertools, numpy as np
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr)
C,O,L,Hh,m,beta=D['C'],D['O'],D['L'],D['H'],D['mret'],D['beta']; n=len(C)
dm=np.c_[np.full((n,3),np.nan),(1+m[:,3:])/(1+m[:,:-3])-1]
ds=np.c_[np.full((n,3),np.nan),C[:,3:]/C[:,:-3]-1]
# beta rank within day
bq=np.full(n,np.nan)
for d in np.unique(D['date']):
    ix=np.flatnonzero(D['date']==d); b=beta[ix]; o=np.argsort(np.argsort(np.nan_to_num(b,nan=-9)))
    bq[ix]=o/max(len(ix)-1,1)
out={}
for side,x,bmin,lagf in itertools.product((1,-1),(0.003,0.005,0.008),(0.0,0.7),(None,0.5,0.0)):
    ev=(side*dm>=x)
    # first market event of the day only (same for all stocks on a date)
    first=np.argmax(ev,1); has=ev.any(1)
    sig=np.zeros((n,48),bool); r=np.flatnonzero(has); sig[r,first[r]]=True
    cond=(bq>=bmin)[:,None]
    if lagf is not None: cond=cond&(side*ds<=lagf*np.maximum(beta,0)[:,None]*side*dm)
    s=sig&cond
    if side==1:
        rr,e,bp=lib5.trades(D,s,first=3,last=44)
    else:
        s2=s.copy(); s2[:,:3]=False; s2[:,45:]=False
        hh=s2.any(1); i=np.argmax(s2,1); rr=np.flatnonzero(hh); e=i[rr]+1
        sell=O[rr,e]-lib5.TICK; buy=C[rr,-1]+lib5.TICK
        dn=np.round(D['pc'][rr]*(1-np.where(D['up'][rr]/D['pc'][rr]>1.15,0.2,0.1))+1e-9,2)
        ok=(sell>dn+0.005)&(D['V'][rr,e]>0); rr,sell,buy=rr[ok],sell[ok],buy[ok]
        bp=(sell/buy-1)*1e4-(5+D['stamp'][rr]+0.2)
    d=D['date'][rr]; u,inv=np.unique(d,return_inverse=True); w=bp>0
    out[('D',side,x,bmin,lagf)]=dict(n=len(bp),s=bp.sum(),nw=int(w.sum()),sw=bp[w].sum(),sl=bp[~w].sum(),dates=u,ds=np.bincount(inv,bp),dc=np.bincount(inv),ss=(bp**2).sum())
pickle.dump(out,open(f'{os.environ["HOME"]}/research/brk/res_D_{yr}.pkl','wb')); print(yr,len(out))
