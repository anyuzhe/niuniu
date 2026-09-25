import duckdb, os, sys, json, time
from chanlib import run
H=os.environ['HOME']
sym,yr=sys.argv[1],sys.argv[2]
half=sys.argv[3] if len(sys.argv)>3 else ''
lo,hi={'':(f'{yr}-01-01',f'{yr}-12-31'),'H1':(f'{yr}-01-01',f'{yr}-06-30'),'H2':(f'{yr}-07-01',f'{yr}-12-31')}[half]
out_path=f'{H}/research/chan/out/{sym}_{yr}{half}.json'
if os.path.exists(out_path): sys.exit(0)
c=duckdb.connect(f'{H}/mnt/lake/silver/gst_intraday/gst_intraday.duckdb',read_only=True)
days=[r[0] for r in c.execute("select date::varchar from stock_days where symbol=? and usable_ticks and date<? order by date desc limit 10",[sym,lo]).fetchall()]
start=min(days) if days else lo
rows=c.execute("""select b.date::varchar, b.minute, b.open,b.high,b.low,b.close,b.volume::double,b.amount from bars_1m b join stock_days s using(symbol,date)
  where b.symbol=? and s.usable_ticks and b.minute>='09:30' and b.date>=? and b.date<=? order by b.date,b.minute""",[sym,start,hi]).fetchall()
c.close()
bars=[(int(d[:4]),int(d[5:7]),int(d[8:]),int(m[:2]),int(m[3:]),o,h,l,cl,v,a) for d,m,o,h,l,cl,v,a in rows]
t=time.time(); pts=run(bars)
out=[{'confirm_date':rows[i][0],'confirm_minute':rows[i][1],'point_date':rows[j][0],'point_minute':rows[j][1],
      'type':ty,'buy':b,'price':px,'level':lv} for i,j,ty,b,px,lv in pts if rows[i][0]>=lo]
json.dump(out,open(out_path,'w'))
print(sym,yr,len(bars),len(out),round(time.time()-t),'s',flush=True)
