"""Per-year 5-minute grid for the yearly top-500 universe (read-only on READY baostock 5m bars).
Rows = stock-days (sorted by code, date), columns = 48 bars 09:35..15:00. Includes the last ~30 trading days
of the previous year so rolling features have history; `iny` marks rows inside the year."""
import duckdb, os, sys, json, time, numpy as np
H=os.environ['HOME']; yr=int(sys.argv[1])
U=json.load(open(f'{H}/research/mkt/universe.json'))[str(yr)]
files=[f"{H}/mnt/lake/bronze/provider=baostock/stock_kline_min5/{c.replace('.','_')}.parquet" for c in U]
files=[f for f in files if os.path.exists(f)]
t=time.time(); c=duckdb.connect(); c.execute("set temp_directory='/tmp/duck'"); c.execute("set threads=4")
df=c.execute("""select code, date::varchar d, substr(time,9,4) hm, open, high, low, close, volume::double v, amount
   from read_parquet(?) where date between ? and ? order by code, date, time""",[files,f'{yr-1}-11-10',f'{yr}-12-31']).fetchnumpy()
hm=df['hm']; slots=sorted(set(hm.tolist()))
assert len(slots)==48, slots
si={s:i for i,s in enumerate(slots)}
key=np.char.add(df['code'].astype(str),df['d'].astype(str))
chg=np.r_[True,key[1:]!=key[:-1]]; row=np.cumsum(chg)-1; n=row[-1]+1
col=np.array([si[x] for x in hm])
G={}
for k,src in (('O','open'),('H','high'),('L','low'),('C','close'),('V','v'),('A','amount')):
    a=np.full((n,48),np.nan,np.float32); a[row,col]=df[src]; G[k]=a
code=df['code'][chg].astype(str); date=df['d'][chg].astype(str)
np.savez(f'{H}/research/brk/g{yr}.npz',code=code,date=date,iny=(date>=f'{yr}-01-01'),slots=np.array(slots),**G)
print(yr,n,len(set(code)),round(time.time()-t,1),'s')
