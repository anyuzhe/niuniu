"""分批抄底、反弹卖出 (底仓做T, yearly top-500, 5-minute bars). In a buy window [s,e], reference = close of the bar before
the window. Limit buys of 1 unit at ref*(1-k*step), k=1..N (filled only when the bar's low trades through the level by
1 tick). Once holding, sell everything with a limit at avg_cost*(1+tp) (filled when the high trades through by 1 tick,
from the bar after the last fill; at the open if it gaps above); otherwise sell at the close (-1 tick; limit-down close ->
next open). Optional market filter: skip days when the equal-weight market is down >= 1% at the window start.
Fees 7.2 bp per unit round trip (万1 免五 + stamp 5 bp). One episode per stock-day. Research only."""
import sys, os, numpy as np, pickle, itertools
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); T=lib5.TICK; FEE=7.2
O,H,L,C,pc,up,V,code=D['O'],D['H'],D['L'],D['C'],D['pc'],D['up'],D['V'],D['code']; m=D['mret']
dn=np.round(pc*(1-np.where(up/pc>1.15,0.2,0.1))+1e-9,2)
nO=np.r_[O[1:,0],np.nan]; nO[np.r_[code[1:]!=code[:-1],True]]=np.nan
n=len(C)
WIN={'09:35-10:00':(0,5),'10:00-11:30':(6,23),'10:30-11:30':(12,23),'13:00-14:30':(24,41),'13:30-14:30':(30,41),'全天09:35-14:30':(0,41)}
out={}
for (wn,(s,e)),step,N,tp,mf in itertools.product(WIN.items(),(0.005,0.01,0.015),(1,2,3,4),(0.003,0.005,0.01,None),(0,1)):
    ref=O[:,0] if s==0 else C[:,s-1]
    ok=np.isfinite(pc)&(V[:,s]>0)
    if mf: ok&=~(np.nan_to_num(m[:,max(s-1,0)])<=-0.01)
    units=np.zeros(n,int); cost=np.zeros(n); lastfill=np.full(n,-1); done=np.zeros(n,bool); pnl=np.zeros(n)
    for j in range(s,48):
        act=ok&~done
        if j<=e:
            for k in range(1,N+1):
                lvl=ref*(1-k*step)
                f=act&(units==k-1)&(L[:,j]<=lvl-T)&(lvl>dn+0.005)
                units[f]=k; cost[f]+=lvl[f]; lastfill[f]=j
        if tp is not None:
            hold=act&(units>0)&(lastfill<j)
            tgt=cost/np.maximum(units,1)*(1+tp)
            x=hold&(H[:,j]>=tgt+T)
            px=np.maximum(O[:,j],tgt)
            pnl[x]=((px[x]*units[x]-cost[x])/(cost[x]/units[x]))*1e4-FEE*units[x]; done|=x
    last=ok&~done&(units>0)
    sellp=np.where(C[:,-1]<=dn+0.001,nO,C[:,-1])-T
    pnl[last]=((sellp[last]*units[last]-cost[last])/(cost[last]/units[last]))*1e4-FEE*units[last]
    tr=ok&(units>0)&np.isfinite(pnl)&(np.abs(pnl)<5000)
    d=D['date'][tr]; p=pnl[tr]; u,iv=np.unique(d,return_inverse=True); w=p>0
    out[(wn,step,N,tp,mf)]=dict(dates=u,ds=np.bincount(iv,p),dc=np.bincount(iv),n=len(p),s=p.sum(),nw=int(w.sum()),sw=p[w].sum(),sl=p[~w].sum(),
        units=units[tr].sum(),tp=int((done&tr).sum()),q=np.percentile(p,[1,5]) if len(p) else np.array([np.nan,np.nan]),
        full=int((units[tr]==N).sum()),fullpnl=p[units[tr]==N].sum())
pickle.dump(out,open(f'{os.environ["HOME"]}/research/brk/dip_{yr}.pkl','wb')); print(yr,len(out))
