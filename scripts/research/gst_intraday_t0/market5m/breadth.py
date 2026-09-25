"""Whole-market 5-minute context from DATA's bars_min5_baostock_raw (READY, read-only), one year per run:
per (date, time): equal-weight return vs previous close and vs the day's open, share of stocks up vs previous close,
share of stocks at/near limit-up, number of stocks. Previous close = the stock's previous daily close from
bars_daily_baostock_raw (raw prices: ex-dividend days bias a few stocks slightly down). Suspended (zero volume) excluded."""
import duckdb, sys, os, time
H=os.environ['HOME']; yr=sys.argv[1]
M=f'{H}/mnt/lake/bronze/provider=baostock/stock_kline_min5/*.parquet'
Dd=f'{H}/mnt/lake/bronze/provider=baostock/stock_kline_daily/*.parquet'
t=time.time()
c=duckdb.connect(); c.execute("set threads=4"); c.execute("set temp_directory='/tmp/duck'"); c.execute("set preserve_insertion_order=false")
c.execute(f"""create temp table pc as
  select code, date, lag(close) over (partition by code order by date) as prev_close
  from read_parquet('{Dd}') where date between '{int(yr)-1}-12-01' and '{yr}-12-31' and volume>0""")
q=f"""
with m as (select date, substr(time,9,4) as hhmm, code, open, close, volume from read_parquet('{M}')
           where date between '{yr}-01-01' and '{yr}-12-31' and volume>0),
     o as (select code, date, arg_min(open, hhmm) as day_open from m group by code, date),
     j as (select m.date, m.hhmm, m.close, pc.prev_close, o.day_open
           from m join pc using (code, date) join o using (code, date) where pc.prev_close>0)
select date, hhmm, avg(close/prev_close-1) as ew_pc, avg(close/day_open-1) as ew_open,
       avg(case when close>prev_close then 1.0 else 0.0 end) as up_share,
       avg(case when close<prev_close then 1.0 else 0.0 end) as down_share,
       count(*) as n
from j group by date, hhmm order by date, hhmm"""
c.execute(f"copy ({q}) to '{H}/research/mkt/mkt5_{yr}.parquet' (format parquet)")
print(yr, round(time.time()-t,1),'s', c.execute(f"select count(*), min(n), max(n) from read_parquet('{H}/research/mkt/mkt5_{yr}.parquet')").fetchall())
