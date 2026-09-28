"""Per-episode records for one 分批抄底 setting, with features known at entry and what happened afterwards,
to see when the big losses happen. Research only. Usage: dipdiag.py YEAR [s e step N tp]"""
import sys, os, numpy as np
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); s,e,step,N,tp=(int(sys.argv[2]),int(sys.argv[3]),float(sys.argv[4]),int(sys.argv[5]),float(sys.argv[6])) if len(sys.argv)>2 else (12,23,0.01,3,0.005)
D=lib5.load(yr); T=lib5.TICK; FEE=7.2
O,H,L,C,pc,up,V,code=D['O'],D['H'],D['L'],D['C'],D['pc'],D['up'],D['V'],D['code']; m=D['mret']
dn=np.round(pc*(1-np.where(up/pc>1.15,0.2,0.1))+1e-9,2)
nO=np.r_[O[1:,0],np.nan]; nO[np.r_[code[1:]!=code[:-1],True]]=np.nan
n=len(C); ref=C[:,s-1]; ok=np.isfinite(pc)&(V[:,s]>0)
units=np.zeros(n,int); cost=np.zeros(n); lastfill=np.full(n,-1); firstfill=np.full(n,-1); done=np.zeros(n,bool); pnl=np.zeros(n); xbar=np.full(n,47)
for j in range(s,48):
    act=ok&~done
    if j<=e:
        for k in range(1,N+1):
            lvl=ref*(1-k*step)
            f=act&(units==k-1)&(L[:,j]<=lvl-T)&(lvl>dn+0.005)
            units[f]=k; cost[f]+=lvl[f]; lastfill[f]=j; firstfill[f&(firstfill<0)]=j
    hold=act&(units>0)&(lastfill<j); tgt=cost/np.maximum(units,1)*(1+tp)
    x=hold&(H[:,j]>=tgt+T); px=np.maximum(O[:,j],tgt)
    pnl[x]=((px[x]*units[x]-cost[x])/(cost[x]/units[x]))*1e4-FEE*units[x]; done|=x; xbar[x]=j
last=ok&~done&(units>0)
sellp=np.where(C[:,-1]<=dn+0.001,nO,C[:,-1])-T
pnl[last]=((sellp[last]*units[last]-cost[last])/(cost[last]/units[last]))*1e4-FEE*units[last]
tr=ok&(units>0)&np.isfinite(pnl)&(np.abs(pnl)<5000); r=np.flatnonzero(tr)
lag=lambda x,k: np.where(np.r_[np.zeros(k,bool),code[k:]==code[:-k]],np.r_[np.full(k,np.nan),x[:-k]],np.nan)
pc2=lag(pc,1); pc6=lag(pc,5)
out=dict(date=D['date'][r],code=code[r],pnl=pnl[r],units=units[r],hit=done[r],first=firstfill[r],lastf=lastfill[r],x=xbar[r],
  gap=(O[:,0]/pc-1)[r], pre=(ref/pc-1)[r],
  m_pre=m[r,s-1], m_close=m[r,-1], m_after=((1+m[:,-1])/(1+m[:,s-1])-1)[r],
  after=(C[:,-1]/ref-1)[r], low_after=(L[:,s:].min(1)/ref-1)[r],
  r1=(pc/pc2-1)[r], r5=(pc/pc6-1)[r], vr=(V[:,:s].sum(1)/np.maximum(np.nansum(D['vs20'][:,:s],1),1))[r],
  limdn=(C[:,-1]<=dn+0.001)[r], hiddn=(L.min(1)<=dn+0.001)[r], price=ref[r], cy=(up/pc>1.15)[r],
  pre_rng=((H[:,:s].max(1)-L[:,:s].min(1))/pc)[r])
np.savez(f'{os.environ["HOME"]}/research/brk/dd{os.environ.get("DD_TAG","")}_{yr}.npz',**out); print(yr,len(r))
