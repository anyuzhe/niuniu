"""Sector lead-lag (申万一级, point-in-time from sw_industry_history): when a sector's equal-weight move over 15 minutes
is >= x and beats the market by >= 0.5%, buy members that lagged (own 15-min move < half the sector's) or the leaders,
sell the base at the close or with a trailing exit. First event per sector per day. Research only."""
import sys, os, pickle, itertools, numpy as np, duckdb
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); H=os.environ['HOME']
c=duckdb.connect()
ind=c.execute(f"""select code, start_date::varchar s, l1_code from read_parquet('{H}/mnt/lake/bronze/provider=swsresearch/industry_classification_history/2026-09-23.parquet') order by code, start_date""").fetchall()
hist={}
for cd,s,l1 in ind: hist.setdefault(cd,[]).append((s,l1))
code=D['code']; date=D['date']; n=len(code)
sec=np.empty(n,object)
for i in range(n):
    h=hist.get(code[i][3:],[]); v=None
    for s,l1 in h:
        if s<=date[i]: v=l1
    sec[i]=v
C,pc,m=D['C'],D['pc'],D['mret']
ret=C/pc[:,None]-1
key=np.array([f'{d}|{s}' for d,s in zip(date,sec)]); valid=sec!=None
uk,inv=np.unique(key,return_inverse=True); cnt=np.bincount(inv[valid],minlength=len(uk))
sr=np.zeros((len(uk),48))
for j in range(48): sr[:,j]=np.bincount(inv[valid],ret[valid,j],minlength=len(uk))/np.maximum(cnt,1)
S=sr[inv]; S[~valid]=np.nan; big=(cnt[inv]>=5)
dS=np.c_[np.full((n,3),np.nan),(1+S[:,3:])/(1+S[:,:-3])-1]
dM=np.c_[np.full((n,3),np.nan),(1+m[:,3:])/(1+m[:,:-3])-1]
dR=np.c_[np.full((n,3),np.nan),C[:,3:]/C[:,:-3]-1]
out={}
for x,who,ex in itertools.product((0.01,0.015,0.02),('lag','lead','all'),('close','trail')):
    ev=(dS>=x)&(dS-dM>=0.005)&big[:,None]
    first=np.cumsum(ev,1)==1; ev=ev&first
    if who=='lag': ev&=dR<0.5*dS
    elif who=='lead': ev&=dR>=dS
    r,e,bp=lib5.trades(D,ev,first=3,last=44,trail=0.01 if ex=='trail' else None)
    d=D['date'][r]; u,iv=np.unique(d,return_inverse=True); w=bp>0
    out[('S',x,who,ex)]=dict(n=len(bp),s=bp.sum(),nw=int(w.sum()),sw=bp[w].sum(),sl=bp[~w].sum(),dates=u,ds=np.bincount(iv,bp),dc=np.bincount(iv),ss=(bp**2).sum())
pickle.dump(out,open(f'{H}/research/brk/res_S_{yr}.pkl','wb')); print(yr,round(np.mean(valid),3),len(out))
