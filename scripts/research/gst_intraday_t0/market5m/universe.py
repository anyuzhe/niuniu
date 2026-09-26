"""Yearly universe: top 500 A-shares by average daily amount in the previous year, >= 200 trading days that year,
last close >= 8 yuan, not ST at the end of the previous year, Shanghai/Shenzhen only. Uses READY daily bars and status."""
import duckdb, os, json
H=os.environ['HOME']
Dd=f'{H}/mnt/lake/bronze/provider=baostock/stock_kline_daily/*.parquet'
St=f'{H}/mnt/lake/bronze/provider=baostock/daily_status_v2/*.parquet'
c=duckdb.connect(); c.execute("set temp_directory='/tmp/duck'")
out={}
for yr in range(2020,2027):
    p=yr-1
    rows=c.execute(f"""
      with d as (select code, date, close, amount from read_parquet('{Dd}') where date between '{p}-01-01' and '{p}-12-31' and volume>0),
           a as (select code, count(*) n, avg(amount) amt, arg_max(close,date) last_close, max(date) last_date from d group by code),
           s as (select code, arg_max(isST,date) st from read_parquet('{St}') where date between '{p}-12-01' and '{p}-12-31' group by code)
      select a.code from a left join s using(code)
      where n>=200 and last_close>=8 and coalesce(s.st,'0')<>'1' and (a.code like 'sh.6%' or a.code like 'sz.0%' or a.code like 'sz.3%')
      order by amt desc limit 500""").fetchall()
    out[str(yr)]=[r[0] for r in rows]
    print(yr,len(out[str(yr)]),out[str(yr)][:3])
json.dump(out,open(f'{H}/research/mkt/universe.json','w'))
