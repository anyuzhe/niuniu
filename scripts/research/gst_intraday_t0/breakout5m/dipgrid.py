"""分批抄底 grid for the robustness check of the risk-filtered version (research only). Windows start at 10:30 or
later, so the 10:30 market model is known before any buy. Stores per-date sums so any day filter can be applied later.
Also stores the plain baseline: buy every stock at the 10:35 bar open (+1 tick) and sell at the close."""
import sys, os, numpy as np, pickle, itertools
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); T=lib5.TICK; FEE=7.2
O,H,L,C,pc,up,V,code=D['O'],D['H'],D['L'],D['C'],D['pc'],D['up'],D['V'],D['code']
dn=np.round(pc*(1-np.where(up/pc>1.15,0.2,0.1))+1e-9,2)
nO=np.r_[O[1:,0],np.nan]; nO[np.r_[code[1:]!=code[:-1],True]]=np.nan
n=len(C); out={}
date=D['date']; ud,dix=np.unique(date,return_inverse=True)
def pack(tr,p,u):
    d=dix[tr]; nd=len(ud)
    return dict(dates=ud,s=np.bincount(d,p,minlength=nd),c=np.bincount(d,minlength=nd),u=np.bincount(d,u,minlength=nd),
                big=np.bincount(d,(p<=-300).astype(float),minlength=nd),win=np.bincount(d,(p>0).astype(float),minlength=nd))
WIN={'10:30-11:30':(12,23),'10:30-13:30':(12,29),'10:30-14:30':(12,41),'13:00-14:30':(24,41)}
for (wn,(s,e)),step,N,tp in itertools.product(WIN.items(),(0.01,0.0125,0.015,0.02),(1,2,3,4),(0.01,0.02,None)):
    ref=C[:,s-1]; ok=np.isfinite(pc)&(V[:,s]>0)
    units=np.zeros(n,int); cost=np.zeros(n); lastfill=np.full(n,-1); done=np.zeros(n,bool); pnl=np.zeros(n)
    for j in range(s,48):
        act=ok&~done
        if j<=e:
            for k in range(1,N+1):
                lvl=ref*(1-k*step)
                f=act&(units==k-1)&(L[:,j]<=lvl-T)&(lvl>dn+0.005)
                units[f]=k; cost[f]+=lvl[f]; lastfill[f]=j
        if tp is not None:
            hold=act&(units>0)&(lastfill<j); tgt=cost/np.maximum(units,1)*(1+tp)
            x=hold&(H[:,j]>=tgt+T); px=np.maximum(O[:,j],tgt)
            pnl[x]=((px[x]*units[x]-cost[x])/(cost[x]/units[x]))*1e4-FEE*units[x]; done|=x
    last=ok&~done&(units>0); sellp=np.where(C[:,-1]<=dn+0.001,nO,C[:,-1])-T
    pnl[last]=((sellp[last]*units[last]-cost[last])/(cost[last]/units[last]))*1e4-FEE*units[last]
    tr=ok&(units>0)&np.isfinite(pnl)&(np.abs(pnl)<5000)
    out[(wn,step,N,tp)]=pack(tr,pnl[tr],units[tr])
# baseline: buy at 10:35 open, sell at the close
e=12; ent=O[:,e]+T; ok=np.isfinite(pc)&(V[:,e]>0)&(ent<D['up']-0.005)
sellp=np.where(C[:,-1]<=dn+0.001,nO,C[:,-1])-T; p=(sellp/ent-1)*1e4-FEE; tr=ok&np.isfinite(p)&(np.abs(p)<5000)
out[('BASE',)]=pack(tr,p[tr],np.ones(tr.sum(),int))
pickle.dump(out,open(f'{os.environ["HOME"]}/research/brk/grid_{yr}.pkl','wb')); print(yr,len(out))
