"""Research only: per (code,date) snapshot prices from bars_min5_baostock_raw (READY, raw prices).
For each snapshot s (bar END time): sig_s = close of bar ending s ; exe_s = open of the next bar ; plus day open, day low/high so far not needed."""
import duckdb, sys, os, time
H=os.environ['HOME']; yr=sys.argv[1]
M=f'{H}/mnt/lake/bronze/provider=baostock/stock_kline_min5/*.parquet'
S=['0945','1000','1030','1100','1330','1400','1430','1450']
NX={'0945':'0950','1000':'1005','1030':'1035','1100':'1105','1330':'1335','1400':'1405','1430':'1435','1450':'1455'}
cols=[]
for s in S:
    cols.append(f"max(case when hhmm='{s}' then close end) as c{s}")
    cols.append(f"max(case when hhmm='{NX[s]}' then open end) as x{s}")
q=f"""with m as (select code,date,substr(time,9,4) as hhmm,open,close,volume from read_parquet('{M}')
 where date between '{yr}-01-01' and '{yr}-12-31' and volume>0)
select code,date,arg_min(open,hhmm) as dopen,{','.join(cols)} from m group by code,date"""
t=time.time()
c=duckdb.connect(); c.execute("set threads=3"); c.execute("set memory_limit='1800MB'"); c.execute("set temp_directory='/tmp/duck'"); c.execute("set preserve_insertion_order=false")
c.execute(f"copy ({q}) to '{H}/research/intra/snap_{yr}.parquet' (format parquet)")
print(yr,round(time.time()-t,1),'s',c.execute(f"select count(*) from read_parquet('{H}/research/intra/snap_{yr}.parquet')").fetchall(),flush=True)
