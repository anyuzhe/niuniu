"""Market intraday momentum on DATA's index 5-minute bars (tdx_index_kline_min5, 2024-09..2026-09) and, for comparison,
on the temporary whole-market 5-minute average (2020-2024). Morning move = previous close -> 10:00; rest of day = 10:00
-> close; also first half hour + 14:00-14:30 -> last half hour. Correlations by half-year."""
import duckdb, os, numpy as np
H=os.environ['HOME']; c=duckdb.connect()
def series(code):
    r=c.execute(f"""with m as (select date, substr(time,9,4) h, open, close from read_parquet('{H}/mnt/lake/bronze/provider=tdx/index_kline_min5/{code}.parquet'))
      select date::varchar, max(case when h='1000' then close end), max(case when h='1430' then close end), max(case when h='1400' then close end),
             max(case when h='1500' then close end), arg_min(open,h) from m group by date order by date""").fetchall()
    d=np.array([x[0] for x in r]); a=np.array([x[1:] for x in r],dtype=float)
    pc=np.r_[np.nan,a[:-1,3]]
    return d,a[:,0]/pc-1,a[:,3]/a[:,0]-1,a[:,0]/pc-1,a[:,1]/a[:,2]-1,a[:,3]/a[:,1]-1
def report(name,d,morn,rest,r1,r7,r8):
    for lo,hi in (('2024-09','2024-12-31'),('2025-01','2025-06-30'),('2025-07','2025-12-31'),('2026-01','2026-06-30'),('2026-07','2026-12-31')):
        m=(d>=lo)&(d<=hi)&np.isfinite(morn)&np.isfinite(rest)
        if m.sum()<20: continue
        c1=np.corrcoef(morn[m],rest[m])[0,1]; c2=np.corrcoef(r1[m]+r7[m],r8[m])[0,1]
        print(f'{name:10s} {lo}..{hi[:7]} days={m.sum():3d} corr(早盘→余下全天)={c1:+.2f}  corr(首半小时+14:00-14:30→尾盘半小时)={c2:+.2f}')
for code,name in (('sh_000300','沪深300'),('sh_000852','中证1000'),('sh_000001','上证指数')):
    d,morn,rest,r1,r7,r8=series(code); report(name,d,morn,rest,r1,r7,r8)
# temporary whole-market average 2020-2024 for comparison
r=c.execute(f"""select date::varchar, max(case when hhmm='1000' then ew_pc end), max(case when hhmm='1500' then ew_pc end)
   from read_parquet('{H}/research/mkt/mkt5_*.parquet') group by date order by date""").fetchall()
d=np.array([x[0] for x in r]); a=np.array([x[1:] for x in r],dtype=float)
morn=a[:,0]; rest=(1+a[:,1])/(1+a[:,0])-1
for y in ('2020','2021','2022','2023','2024'):
    m=np.char.startswith(d,y); print(f'全市场等权(临时) {y} corr(早盘→余下全天)={np.corrcoef(morn[m],rest[m])[0,1]:+.2f}')
# DATA breadth 2026
r=c.execute(f"""select date::varchar, max(case when time='10:00' then ew_ret_prev_close end), max(case when time='15:00' then ew_ret_prev_close end)
   from read_parquet('{H}/mnt/lake/silver/market_intraday_breadth/freq=1m/year=2026/*.parquet') group by date order by date""").fetchall()
a=np.array([x[1:] for x in r],dtype=float); morn=a[:,0]; rest=(1+a[:,1])/(1+a[:,0])-1
print(f'全市场等权(数据侧) 2026-05..09 days={len(a)} corr(早盘→余下全天)={np.corrcoef(morn,rest)[0,1]:+.2f}')
