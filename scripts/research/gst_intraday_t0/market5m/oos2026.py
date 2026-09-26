"""Fresh out-of-sample check (2026-05-21..2026-09-24) of models fixed on 2020-2024:
 (1) market timing at 10:00 (whole-market model), (2) stock-level morning score (9 features, 5-minute-bar model).
Market context: DATA's market_intraday_breadth (1 minute, READY). Stocks: DATA's tdx_kline_min1 (READY),
universe = top 500 by 2025 average daily amount, last 2025 close >= 8, not ST at 2025 year end.
Sell first at the 10:01 bar's open - 1 tick, buy back at the 15:00 close. Stamp 5 bp (after 2023-08-28)."""
import os, json, numpy as np, duckdb
exec(open(os.environ['HOME']+'/research/mkt/wf500b.py').read().split("for Y in ('2021','2022','2023','2024'):\n    fm=ok&(yr<Y)&(yr>='2020'); ps=")[0])
H=os.environ['HOME']
# models fixed on 2020-2024
fm=ok&(yr>='2020')&(yr<='2024')
mkt_model=fitg(Xm,ymean,fm)
def fitX(m,lam=0.01):
    mu=X[m].mean(0);sd=X[m].std(0);sd=np.where(sd>0,sd,1);Z=(X[m]-mu)/sd
    w=np.linalg.solve(Z.T@Z+lam*len(Z)*np.eye(Z.shape[1]),Z.T@(y[m]-y[m].mean())); return lambda B:((B-mu)/sd)@w+y[m].mean()
stock_model=fitX(fm)
# 2026 universe
Dd=f'{H}/mnt/lake/bronze/provider=baostock/stock_kline_daily/*.parquet'
St=f'{H}/mnt/lake/bronze/provider=baostock/daily_status_v2/*.parquet'
c=duckdb.connect(); c.execute("set temp_directory='/tmp/duck'")
U=[r[0] for r in c.execute(f"""
  with d as (select code, date, close, amount from read_parquet('{Dd}') where date between '2025-01-01' and '2025-12-31' and volume>0),
       a as (select code, count(*) n, avg(amount) amt, arg_max(close,date) last_close from d group by code),
       s as (select code, arg_max(isST,date) st from read_parquet('{St}') where date between '2025-12-01' and '2025-12-31' group by code)
  select a.code from a left join s using(code) where n>=200 and last_close>=8 and coalesce(s.st,'0')<>'1'
    and (a.code like 'sh.6%' or a.code like 'sz.0%' or a.code like 'sz.3%') order by amt desc limit 500""").fetchall()]
files=[f"{H}/mnt/lake/bronze/provider=tdx/kline_min1/{u.replace('.','_')}.parquet" for u in U]
files=[f for f in files if os.path.exists(f)]
dfiles=[f"{H}/mnt/lake/bronze/provider=baostock/stock_kline_daily/{u.replace('.','_')}.parquet" for u in U]
B=f'{H}/mnt/lake/silver/market_intraday_breadth/freq=1m/year=2026/*.parquet'
rows=c.execute(f"""
  with m as (select code, date, substr(time,9,4) hhmm, open, high, low, close, volume, amount from read_parquet(?) where date between '2026-05-21' and '2026-09-24' and volume>0),
       pc as (select code, date, lag(close) over (partition by code order by date) prev_close from read_parquet(?) where date>='2026-04-01' and volume>0),
       f as (select code, date,
               max(case when hhmm='1000' then close end) p,
               arg_min(open,hhmm) day_open,
               sum(case when hhmm<='1000' then amount end)/nullif(sum(case when hhmm<='1000' then volume end),0) vwap,
               max(case when hhmm<='1000' then high end) hi, min(case when hhmm<='1000' then low end) lo,
               max(case when hhmm='1001' then open end) entry, max(case when hhmm='1500' then close end) cl
             from m group by code, date),
       b as (select date, max(case when time='10:00' then ew_ret_prev_close end) ew_pc, max(case when time='10:00' then ew_ret_open end) ew_open,
                    max(case when time='09:31' then ew_ret_prev_close end) fb_pc, max(case when time='09:31' then ew_ret_open end) fb_open
             from read_parquet('{B}') group by date)
  select f.code, f.date::varchar, f.p, f.day_open, f.vwap, f.hi, f.lo, f.entry, f.cl, pc.prev_close, b.ew_pc, b.ew_open, b.fb_pc, b.fb_open
  from f join pc using(code,date) join b on b.date=f.date order by f.date, f.code""",[files,dfiles]).fetchall()
a=np.array([r[2:] for r in rows],dtype=float); cd=np.array([r[0] for r in rows]); dd=np.array([r[1] for r in rows])
p,op,vw,hi,lo,ent,cl,pc,ewp,ewo,fbp,fbo=a.T
Xn=np.column_stack([p/pc-1,p/op-1,p/op-1,p/vw-1,np.where(hi>lo,(p-lo)/np.where(hi>lo,hi-lo,1),.5),ewp,ewo,op/pc-1,(1+fbp)/(1+fbo)-1])
rate=np.where(np.char.startswith(cd,'sh.688')|np.char.startswith(cd,'sz.300')|np.char.startswith(cd,'sz.301'),0.20,0.10)
okn=np.isfinite(Xn).all(1)&np.isfinite(ent)&np.isfinite(cl)&(np.abs(p/pc-1)<rate-0.005)&(ent>pc*(1-rate)+0.011)
sell_n=((ent-0.01)/cl-1)*1e4-(5+5+0.2)
print('universe',len(U),'files',len(files),'stock-days',len(rows),'usable',okn.sum(),'days',len(np.unique(dd)))
pm=mkt_model(Xn[:,[5,6,8]]); ps=stock_model(Xn)
days=np.unique(dd)
dm=np.array([np.nanmean(sell_n[okn&(dd==d)]) for d in days]); dp=np.array([pm[okn&(dd==d)][0] for d in days])
print('baseline: sell-first every stock every day at 10:01, buy at close: per trip',round(np.nanmean(sell_n[okn]),1),'bp')
print('corr(market prediction, realised day-average rest-of-day return)',round(np.corrcoef(dp,-(dm+10.2))[0,1],3))
for thr in (5,10,15,20):
    sel=dp<=-thr
    if sel.sum()==0: print(f'market timing thr{thr}: no days'); continue
    v=dm[sel]; print(f'market timing thr{thr}: days={sel.sum()} per trip={v.mean():+.1f} bp  days won={np.mean(v>0):.2f}  dates={list(days[sel])[:12]}')
for thr in (20,30,40):
    s=okn&(ps<=-thr)
    b=sell_n[s]; w=b[b>0]; l=b[b<=0]
    nd=len(np.unique(dd[s]))
    print(f'stock morning score thr{thr}: trips={s.sum()} on {nd} days per trip={b.mean():+.1f} win={len(w)/max(len(b),1):.2f} payoff={(w.mean()/-l.mean()) if len(w) and len(l) else float("nan"):.2f}')
print('corr(stock score, realised) all stock-days:',round(np.corrcoef(ps[okn],-(sell_n[okn]+10.2))[0,1],3))
