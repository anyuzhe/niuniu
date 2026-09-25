"""Morning score on a yearly top-500 universe from 5-minute bars, walk-forward (fit on earlier years from 2020 only).
Sell first at the next 5-minute bar's open - 1 tick after the 10:00 / 10:30 bar, buy back at the close.
Costs: commission 2.5 bp x2, transfer, stamp on the sell (10 bp before 2023-08-28, 5 bp after)."""
import duckdb, os, numpy as np, collections, sys
H=os.environ['HOME']
d=duckdb.connect().execute(f"""
  select f.code, f.date::varchar d, f.t, f.p, f.back, f.vwap, f.hi, f.lo, f.entry_open, f.day_close, f.day_open, f.prev_close, f.isST,
         m.ew_pc, m.ew_open, fb.ew_pc as fb_pc, fb.ew_open as fb_open
  from read_parquet('{H}/research/mkt/feat5_*.parquet') f
  join read_parquet('{H}/research/mkt/mkt5_*.parquet') m on m.date=f.date and m.hhmm=f.t
  join (select date, ew_pc, ew_open from read_parquet('{H}/research/mkt/mkt5_*.parquet') where hhmm='0935') fb on fb.date=f.date
  order by f.date, f.code, f.t""").fetchnumpy()
code=np.asarray(d['code']).astype(str); dt=np.asarray(d['d']).astype(str); tt=np.asarray(d['t']).astype(str)
g=lambda k: np.asarray(d[k],dtype=float)
p,back,vwap,hi,lo,ent,cl,op,pc=[g(k) for k in ('p','back','vwap','hi','lo','entry_open','day_close','day_open','prev_close')]
st=np.asarray(d['isST']).astype(str)
yr=np.array([x[:4] for x in dt])
rate=np.where(np.char.startswith(code,'sh.688')|((np.char.startswith(code,'sz.300')|np.char.startswith(code,'sz.301'))&(dt>='2020-08-24')),0.20,0.10)
X=np.column_stack([p/pc-1,p/op-1,p/back-1,p/vwap-1,np.where(hi>lo,(p-lo)/np.where(hi>lo,hi-lo,1),.5),g('ew_pc'),g('ew_open'),op/pc-1,(1+g('fb_pc'))/(1+g('fb_open'))-1])
names=['ret_pc','ret_open','ret_30','vwap_dev','range_pos','mkt','mkt_open','gap','mgap']
y=(cl/ent-1)*1e4
stamp=np.where(dt>='2023-08-28',5.0,10.0); fees=5+stamp+0.2
tick=0.01
ok=np.isfinite(X).all(1)&np.isfinite(y)&(st!='1')&(np.abs(p/pc-1)<rate-0.005)&(ent>pc*(1-rate)+0.011)&(ent<pc*(1+rate)-0.011)
sell=((ent-tick)/cl-1)*1e4-fees; buy=(cl/(ent+tick)-1)*1e4-fees
def fit(m,lam=0.01):
    mu=X[m].mean(0);sd=X[m].std(0);sd=np.where(sd>0,sd,1);Z=(X[m]-mu)/sd
    w=np.linalg.solve(Z.T@Z+lam*len(Z)*np.eye(Z.shape[1]),Z.T@(y[m]-y[m].mean())); return mu,sd,w,y[m].mean()
def pred(mo): mu,sd,w,b=mo; return ((X-mu)/sd)@w+b
def clustered(v,m):
    v=v[m]; ds=dt[m]; mean=v.mean(); u,inv=np.unique(ds,return_inverse=True)
    se=np.sqrt((np.bincount(inv,v-mean)**2).sum())/len(v); return mean,mean/se,len(v)
key=np.char.add(code,dt)
for thr in (20,30,40):
    for side in ('sell','buy'):
        taken=np.zeros(len(y),bool); net=np.full(len(y),np.nan); stock_day_taken=set()
        for Y in ('2021','2022','2023','2024'):
            mo=fit(ok&(yr<Y)&(yr>='2020')); pr=pred(mo)
            for T in ('1000','1030'):
                s=ok&(yr==Y)&(tt==T)&((pr<=-thr) if side=='sell' else (pr>=thr))
                idx=[i for i in np.flatnonzero(s) if key[i] not in stock_day_taken]
                stock_day_taken.update(key[idx]); taken[idx]=True
                net[idx]=(sell if side=='sell' else buy)[idx]
        mean,t_,n=clustered(net,taken)
        ys=' '.join(f"{Y[2:]}:{np.nanmean(net[taken&(yr==Y)]):+.0f}({(taken&(yr==Y)).sum()})" for Y in ('2021','2022','2023','2024'))
        b=net[taken]; w=b[b>0]; l=b[b<=0]
        print(f'thr{thr} {side}: n={n} trip={mean:+.1f} t={t_:+.2f} win={len(w)/len(b):.2f} payoff={w.mean()/-l.mean():.2f}  {ys}',flush=True)
mo=fit(ok&(yr>='2020')&(yr<='2023'))
print('weights (fit 2020-2023):',' '.join(f'{n}:{w:+.1f}' for n,w in zip(names,mo[2])))
print('corr(pred,y) by year:',' '.join(f"{Y}:{np.corrcoef(pred(fit(ok&(yr<Y)&(yr>='2020')))[ok&(yr==Y)],y[ok&(yr==Y)])[0,1]:+.3f}" for Y in ('2021','2022','2023','2024')))
