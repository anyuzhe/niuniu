"""分批抄底 with market filters on each buy (research only). A buy at bar j is allowed only if, at the close of bar j-1:
 F1 market (sample equal-weight) vs previous close >= 0; F2 market's last-30-minute change >= 0; F3 both;
 F4 market vs today's open >= 0; ORACLE: skip days whose market falls >= 1% from the window start to the close
 (hindsight, upper bound only)."""
import sys, os, numpy as np, pickle, itertools
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); T=lib5.TICK; FEE=7.2
O,H,L,C,pc,up,V,code=D['O'],D['H'],D['L'],D['C'],D['pc'],D['up'],D['V'],D['code']; m=D['mret']
dn=np.round(pc*(1-np.where(up/pc>1.15,0.2,0.1))+1e-9,2)
nO=np.r_[O[1:,0],np.nan]; nO[np.r_[code[1:]!=code[:-1],True]]=np.nan
n=len(C); out={}
m30=np.c_[np.zeros((n,6)),(1+m[:,6:])/(1+m[:,:-6])-1]
mopen=(1+m)/(1+m[:,[0]])-1
WIN={'10:00-11:30':(6,23),'10:30-11:30':(12,23),'13:30-14:30':(30,41),'全天09:40-14:30':(1,41)}
for (wn,(s,e)),step,N,tp,flt in itertools.product(WIN.items(),(0.01,0.015),(1,2,3),(0.005,0.01,None),('无','F1','F2','F3','F4','ORACLE')):
    ref=C[:,s-1]; ok=np.isfinite(pc)&(V[:,s]>0)
    if flt=='ORACLE': ok&=((1+m[:,-1])/(1+m[:,s-1])-1)>-0.01
    units=np.zeros(n,int); cost=np.zeros(n); lastfill=np.full(n,-1); done=np.zeros(n,bool); pnl=np.zeros(n)
    for j in range(s,48):
        act=ok&~done
        if j<=e:
            allow=np.ones(n,bool)
            if flt in ('F1','F3'): allow&=m[:,j-1]>=0
            if flt in ('F2','F3'): allow&=m30[:,j-1]>=0
            if flt=='F4': allow&=mopen[:,j-1]>=0
            for k in range(1,N+1):
                lvl=ref*(1-k*step)
                f=act&allow&(units==k-1)&(L[:,j]<=lvl-T)&(lvl>dn+0.005)
                units[f]=k; cost[f]+=lvl[f]; lastfill[f]=j
        if tp is not None:
            hold=act&(units>0)&(lastfill<j); tgt=cost/np.maximum(units,1)*(1+tp)
            x=hold&(H[:,j]>=tgt+T); px=np.maximum(O[:,j],tgt)
            pnl[x]=((px[x]*units[x]-cost[x])/(cost[x]/units[x]))*1e4-FEE*units[x]; done|=x
    last=ok&~done&(units>0); sellp=np.where(C[:,-1]<=dn+0.001,nO,C[:,-1])-T
    pnl[last]=((sellp[last]*units[last]-cost[last])/(cost[last]/units[last]))*1e4-FEE*units[last]
    tr=ok&(units>0)&np.isfinite(pnl)&(np.abs(pnl)<5000)
    d=D['date'][tr]; p=pnl[tr]; u,iv=np.unique(d,return_inverse=True); w=p>0
    out[(wn,step,N,tp,flt)]=dict(dates=u,ds=np.bincount(iv,p),dc=np.bincount(iv),n=len(p),s=p.sum(),nw=int(w.sum()),sw=p[w].sum(),sl=p[~w].sum(),
        units=units[tr].sum(),q=np.percentile(p,[1,5]) if len(p) else np.array([np.nan]*2),big=int((p<=-300).sum()),days=len(u))
pickle.dump(out,open(f'{os.environ["HOME"]}/research/brk/dip3_{yr}.pkl','wb')); print(yr,len(out))
