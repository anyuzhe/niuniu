"""Tick-level (≈3-second quote snapshots, gst quotes 2019-05..2020-06, 16 stocks) sprint scalping for 底仓做T.
Buy at the ask of the snapshot AFTER the signal (≈3 s latency); sell at the bid of the snapshot after the exit
condition (or a resting limit sell filled when a later trade prints above it / the bid reaches it).
Signals: V(k,m) volume over the last k snapshots >= m x the average of the previous 5 minutes and price up >= 1 tick;
P(N,w) last price breaks the high of the previous N seconds whose range <= w (platform); P+V both.
Exits: S(j) sell when no new high for j snapshots; TP(n) sell once bid >= entry + n ticks; LIM limit sell at entry+1 tick;
all with a 3-tick stop and a 5-minute cap. Costs: commission 2.5 bp x2, stamp 5 bp (current rule), transfer 0.2 bp.
Research only."""
import numpy as np, glob, os, sys, itertools, pickle
H=os.environ['HOME']; TK=0.01; COST=10.2
def load(f):
    z=np.load(f); return {k:z[k] for k in ('date','t','last','cum_volume','bid1_px','ask1_px','bid1_vol','ask1_vol')}
SIG=[('V',k,m,None) for k in (1,2,3) for m in (3,5,10)]+[('P',N,w,None) for N in (300,900) for w in (0.003,0.006)]+[('P',N,w,'V') for N in (300,900) for w in (0.003,0.006)]
EX=[('S',j) for j in (2,3,5,10)]+[('TP',n) for n in (1,2,3)]+[('LIM',1)]
def run_day(d):
    t=d['t'];p=d['last'];b=d['bid1_px'];a=d['ask1_px'];cv=d['cum_volume']; n=len(t)
    dv=np.r_[0,np.diff(cv)].clip(0)
    cs=np.r_[0,np.cumsum(dv)]
    # average per-snapshot volume over previous 100 snapshots (~5 min)
    idx=np.arange(n); lo=np.maximum(idx-100,0); avg=(cs[idx]-cs[lo])/np.maximum(idx-lo,1)
    runmax=np.maximum.accumulate(p)
    res={}
    for sg in SIG:
        if sg[0]=='V':
            k,m=sg[1],sg[2]
            vk=cs[idx+1]-cs[np.maximum(idx+1-k,0)]
            pk=p-np.r_[np.full(k,np.nan),p[:-k]]
            sig=(vk>=m*k*np.maximum(avg,1))&(pk>=TK-1e-9)&(idx>=100)
        else:
            N,w=sg[1],sg[2]
            hi=np.full(n,np.nan); lo_=np.full(n,np.nan)
            from numpy.lib.stride_tricks import sliding_window_view as sw
            W=int(N/3)
            if n>W+1:
                hi[W:]=sw(p[:-1],W).max(1)[:n-W]
                lo_[W:]=sw(p[:-1],W).min(1)[:n-W]
            sig=(p>hi+1e-9)&((hi-lo_)/p<=w)&(t-t[0]>=N)
            if sg[3]=='V': sig&=(dv>=3*np.maximum(avg,1))
        sig[-3:]=False
        cand=np.flatnonzero(sig)
        for ex in EX:
            out=[]; busy=-1
            for i in cand:
                if i<=busy: continue
                e=i+1; ent=a[e]
                if not(ent>0) or not(b[e]>0): continue
                peak=p[e]; since=0; stop=ent-3*TK; lim=ent+TK; px=None; k=e+1
                while k<n:
                    if t[k]-t[e]>300 or b[k]<=stop: px=b[min(k+1,n-1)]; break
                    if ex[0]=='LIM':
                        if p[k]>lim+1e-9 or b[k]>=lim-1e-9: px=lim; break
                    elif ex[0]=='TP':
                        if b[k]>=ent+ex[1]*TK-1e-9: px=b[min(k+1,n-1)]; break
                    else:
                        if p[k]>peak+1e-9: peak=p[k]; since=0
                        else:
                            since+=1
                            if since>=ex[1]: px=b[min(k+1,n-1)]; break
                    k+=1
                if px is None or not(px>0): px=b[n-1] if b[n-1]>0 else p[n-1]; k=n-1
                out.append((ent,px,(px/ent-1)*1e4-COST,t[k]-t[e])); busy=k
            res[(sg,ex)]=out
    return res
f=sys.argv[1]; D=load(f); sym=os.path.basename(f)[:9]
R={}
ud=np.unique(D['date'])
for dd in ud:
    m=D['date']==dd
    if m.sum()<500: continue
    r=run_day({k:v[m] for k,v in D.items()})
    for k,v in r.items(): R.setdefault(k,[]).extend([(dd,)+x for x in v])
pickle.dump(R,open(f'{H}/research/tick/sc_{sym}.pkl','wb')); print(sym,sum(len(v) for v in R.values()))
