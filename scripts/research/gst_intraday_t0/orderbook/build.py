"""Order-book arrays per stock from gst quotes (usable quote days only, read-only)."""
import duckdb, numpy as np, os, sys, time
H=os.environ['HOME']
c=duckdb.connect(os.environ.get('GST_DB',f'{H}/mnt/lake/silver/gst_intraday/gst_intraday.duckdb'),read_only=True)
syms=[r[0] for r in c.execute('select symbol from stocks order by symbol').fetchall()]
cols=['last','cum_volume']+[f'{s}{k}_{f}' for s in ('bid','ask') for k in range(1,6) for f in ('px','vol')]
t0=time.time()
for sym in syms:
    q=c.execute(f"""select date::varchar as d, time, {','.join(cols)} from quotes
        where symbol=? and ((time>='09:30:00' and time<='11:30:00') or (time>='13:00:00' and time<='14:57:00'))
        order by date, seq""",[sym]).fetchnumpy()
    tm=np.array([int(x[:2])*3600+int(x[3:5])*60+int(x[6:8]) for x in q['time']],dtype=np.int32)
    out={'date':np.asarray(q['d']).astype('U10'),'t':tm}
    for k in cols: out[k]=np.asarray(q[k],dtype=np.float64)
    pc=dict(c.execute('select date::varchar, prev_close from stock_days where symbol=?',[sym]).fetchall())
    out['prev_close']=np.array([pc.get(d,np.nan) for d in out['date']])
    np.savez(f'{H}/research/ob/{sym}.npz',**out)
    print(sym,len(tm),round(time.time()-t0,1),flush=True)
