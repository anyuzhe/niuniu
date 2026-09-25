"""Per stock-day features at 10:00 and 10:30 from 5-minute bars for the yearly universe (read-only)."""
import duckdb, os, sys, json, time
H=os.environ['HOME']; yr=sys.argv[1]
U=json.load(open(f'{H}/research/mkt/universe.json'))[yr]
files=[f"{H}/mnt/lake/bronze/provider=baostock/stock_kline_min5/{c.replace('.','_')}.parquet" for c in U]
dfiles=[f"{H}/mnt/lake/bronze/provider=baostock/stock_kline_daily/{c.replace('.','_')}.parquet" for c in U]
sfiles=[f"{H}/mnt/lake/bronze/provider=baostock/daily_status_v2/{c.replace('.','_')}.parquet" for c in U]
t=time.time()
c=duckdb.connect(); c.execute("set temp_directory='/tmp/duck'"); c.execute("set threads=4")
c.execute("create temp table m as select code, date, substr(time,9,4) hhmm, open, high, low, close, volume, amount from read_parquet(?) where date between ? and ? and volume>0",[files,f'{yr}-01-01',f'{yr}-12-31'])
c.execute("create temp table pc as select code, date, lag(close) over (partition by code order by date) prev_close from read_parquet(?) where date between ? and ? and volume>0",[dfiles,f'{int(yr)-1}-11-01',f'{yr}-12-31'])
c.execute("create temp table st as select code, date, isST from read_parquet(?) where date between ? and ?",[sfiles,f'{yr}-01-01',f'{yr}-12-31'])
parts=[]
for T,prevT,nextT in (('1000',None,'1005'),('1030','1000','1035')):
    back = "d.day_open" if prevT is None else f"max(case when hhmm='{prevT}' then close end)"
    parts.append(f"""
    select code, date, '{T}' as t,
      max(case when hhmm='{T}' then close end) as p,
      {back} as back,
      sum(case when hhmm<='{T}' then amount end)/nullif(sum(case when hhmm<='{T}' then volume end),0) as vwap,
      max(case when hhmm<='{T}' then high end) as hi, min(case when hhmm<='{T}' then low end) as lo,
      max(case when hhmm='{nextT}' then open end) as entry_open,
      max(case when hhmm='1500' then close end) as day_close,
      max(d.day_open) as day_open
    from m join (select code, date, arg_min(open,hhmm) day_open from m group by code, date) d using(code,date)
    group by code, date, d.day_open""")
q=" union all ".join(parts)
c.execute(f"""copy (select f.*, pc.prev_close, st.isST from ({q}) f join pc using(code,date) left join st using(code,date))
             to '{H}/research/mkt/feat5_{yr}.parquet' (format parquet)""")
print(yr, round(time.time()-t,1),'s', c.execute(f"select count(*), count(distinct code) from read_parquet('{H}/research/mkt/feat5_{yr}.parquet')").fetchall())
