"""Market-timing 底仓做T with DATA's official market_intraday_breadth_5m (2020-01..2026-09, incl. delisted stocks).
At 10:00: model (whole-market return vs prev close, vs open, opening gap, up-share) fitted on all earlier years
predicts the universe's average move from the 10:05 open to the close. Trade days: prediction <= -thr bp.
Optional gate: trailing-120-day correlation (days before today) between the 10:00 whole-market move and the rest-of-day
whole-market move must exceed g. On trade days sell first in every universe stock, buy back at the close."""
import duckdb, os, numpy as np
H=os.environ['HOME']; c=duckdb.connect()
B=f'{H}/mnt/lake/silver/market_intraday_breadth/freq=5m/year=*/*.parquet'
br={r[0]:r[1:] for r in c.execute(f"""select date::varchar,
      max(case when time='10:00' then ew_ret_prev_close end), max(case when time='10:00' then ew_ret_open end),
      max(case when time='09:35' then ew_ret_prev_close end), max(case when time='09:35' then ew_ret_open end),
      max(case when time='10:00' then up_count*1.0/n_stocks end), max(case when time='15:00' then ew_ret_prev_close end)
      from read_parquet('{B}') group by date order by date""").fetchall()}
bd=np.array(sorted(br)); ba=np.array([br[d] for d in bd],dtype=float)
morn=ba[:,0]; rest=(1+ba[:,5])/(1+ba[:,0])-1
trail={}
for i,d in enumerate(bd):
    lo=max(0,i-120); m=np.isfinite(morn[lo:i])&np.isfinite(rest[lo:i])
    trail[d]=np.corrcoef(morn[lo:i][m],rest[lo:i][m])[0,1] if m.sum()>=60 else np.nan
d=c.execute(f"""select code, date::varchar, p, entry_open, day_close, prev_close, isST from read_parquet('{H}/research/mkt/feat5_*.parquet') where t='1000'""").fetchall()
code=np.array([x[0] for x in d]); dt=np.array([x[1] for x in d]); a=np.array([x[2:6] for x in d],dtype=float); st=np.array([str(x[6]) for x in d])
p,ent,cl,pc=a.T
rate=np.where(np.char.startswith(code,'sh.688')|((np.char.startswith(code,'sz.300')|np.char.startswith(code,'sz.301'))&(dt>='2020-08-24')),0.20,0.10)
ok=np.isfinite(ent)&np.isfinite(cl)&(st!='1')&(np.abs(p/pc-1)<rate-0.005)&(ent>pc*(1-rate)+0.011)
stamp=np.where(dt>='2023-08-28',5.0,10.0)
sell=((ent-0.01)/cl-1)*1e4-(5+stamp+0.2); y=(cl/ent-1)*1e4
days=np.unique(dt[ok])
day_sell=np.array([sell[ok&(dt==x)].mean() for x in days]); day_y=np.array([y[ok&(dt==x)].mean() for x in days])
F=np.array([[br[x][0],br[x][1],(1+br[x][2])/(1+br[x][3])-1,br[x][4]] if x in br else [np.nan]*4 for x in days],dtype=float)
yrs=np.array([x[:4] for x in days])
okd=np.isfinite(F).all(1)&np.isfinite(day_y)
def fit(m,cols,lam=0.01):
    X=F[:,cols]; mu=X[m].mean(0);sd=X[m].std(0);Z=(X[m]-mu)/sd
    w=np.linalg.solve(Z.T@Z+lam*len(Z)*np.eye(len(cols)),Z.T@(day_y[m]-day_y[m].mean())); return ((X-mu)/sd)@w+day_y[m].mean()
tr=np.array([trail.get(x,np.nan) for x in days])
for cols,lab in (([0,1,2],'3 features'),([0,1,2,3],'+up-share')):
    pred=np.full(len(days),np.nan)
    for Y in ('2021','2022','2023','2024','2025','2026'):
        pr=fit(okd&(yrs<Y),cols); pred[yrs==Y]=pr[yrs==Y]
    print(f'--- model {lab}: corr(pred, realised day move) by year:',' '.join(f"{Y}:{np.corrcoef(pred[okd&(yrs==Y)],day_y[okd&(yrs==Y)])[0,1]:+.2f}" for Y in ('2021','2022','2023','2024','2025','2026')))
    for thr in (10,15,20):
        for g in (None,0.0,0.1):
            sel=okd&(pred<=-thr)&((tr>g) if g is not None else True)
            parts=[]
            for Y in ('2021','2022','2023','2024','2025','2026'):
                v=day_sell[sel&(yrs==Y)]; parts.append(f"{Y[2:]}:{v.mean() if len(v) else float('nan'):+.0f}({len(v)})")
            v=day_sell[sel]; t=v.mean()/(v.std(ddof=1)/np.sqrt(len(v))) if len(v)>2 else float('nan')
            print(f'thr{thr:2d} gate={g}: days={len(v):3d} per trip={v.mean():+6.1f} bp day win={np.mean(v>0):.2f} t={t:+.2f} | {" ".join(parts)}')
print('trailing-120d corr at year starts:',' '.join(f"{x}:{trail[x]:+.2f}" for x in bd if x[5:10] in ('01-02','01-03','01-04','07-01','07-02','07-03')))
