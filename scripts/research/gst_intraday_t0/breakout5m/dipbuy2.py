"""分批抄底 with a market guard (research only): measure the equal-weight market (sample) from the window start;
once it has fallen by >= g, (A) stop adding, or (B) also sell everything at the next bar's open (-1 tick)."""
import sys, os, numpy as np, pickle, itertools
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); T=lib5.TICK; FEE=7.2
O,H,L,C,pc,up,V,code=D['O'],D['H'],D['L'],D['C'],D['pc'],D['up'],D['V'],D['code']; m=D['mret']
dn=np.round(pc*(1-np.where(up/pc>1.15,0.2,0.1))+1e-9,2)
nO=np.r_[O[1:,0],np.nan]; nO[np.r_[code[1:]!=code[:-1],True]]=np.nan
n=len(C); out={}
WIN={'10:00-11:30':(6,23),'10:30-11:30':(12,23),'13:30-14:30':(30,41)}
for (wn,(s,e)),step,N,tp,g,mode in itertools.product(WIN.items(),(0.01,0.015),(2,3),(0.005,0.01,None),(None,0.003,0.005,0.01),('A','B')):
    if g is None and mode=='B': continue
    ref=C[:,s-1]; m0=m[:,s-1]; ok=np.isfinite(pc)&(V[:,s]>0)
    units=np.zeros(n,int); cost=np.zeros(n); lastfill=np.full(n,-1); done=np.zeros(n,bool); pnl=np.zeros(n); guard=np.zeros(n,bool)
    for j in range(s,48):
        act=ok&~done
        if mode=='B' and g is not None:
            cut=act&(units>0)&guard&(lastfill<j)
            px=O[:,j]-T; pnl[cut]=((px[cut]*units[cut]-cost[cut])/(cost[cut]/units[cut]))*1e4-FEE*units[cut]; done|=cut; act&=~cut
        if j<=e:
            for k in range(1,N+1):
                lvl=ref*(1-k*step)
                f=act&~guard&(units==k-1)&(L[:,j]<=lvl-T)&(lvl>dn+0.005)
                units[f]=k; cost[f]+=lvl[f]; lastfill[f]=j
        if tp is not None:
            hold=act&(units>0)&(lastfill<j); tgt=cost/np.maximum(units,1)*(1+tp)
            x=hold&(H[:,j]>=tgt+T); px=np.maximum(O[:,j],tgt)
            pnl[x]=((px[x]*units[x]-cost[x])/(cost[x]/units[x]))*1e4-FEE*units[x]; done|=x
        if g is not None: guard|=((1+m[:,j])/(1+m0)-1)<=-g   # known at this bar's close, acts from the next bar
    last=ok&~done&(units>0); sellp=np.where(C[:,-1]<=dn+0.001,nO,C[:,-1])-T
    pnl[last]=((sellp[last]*units[last]-cost[last])/(cost[last]/units[last]))*1e4-FEE*units[last]
    tr=ok&(units>0)&np.isfinite(pnl)&(np.abs(pnl)<5000)
    d=D['date'][tr]; p=pnl[tr]; u,iv=np.unique(d,return_inverse=True); w=p>0
    out[(wn,step,N,tp,g,mode)]=dict(dates=u,ds=np.bincount(iv,p),dc=np.bincount(iv),n=len(p),s=p.sum(),nw=int(w.sum()),sw=p[w].sum(),sl=p[~w].sum(),
        units=units[tr].sum(),tp=0,q=np.percentile(p,[1,5]),full=0,fullpnl=0.,big=int((p<=-300).sum()))
pickle.dump(out,open(f'{os.environ["HOME"]}/research/brk/dip2_{yr}.pkl','wb')); print(yr,len(out))
