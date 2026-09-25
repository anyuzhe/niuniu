"""Build a stock-day x minute grid from gst_intraday (read-only). Research only, not product code."""
import duckdb, numpy as np, os, time
H=os.environ['HOME']
c=duckdb.connect(os.environ.get('GST_DB','/Volumes/Lexar/niuniu-data/lake/silver/gst_intraday/gst_intraday.duckdb'),read_only=True)
slots=[f'{h:02d}:{m:02d}' for h,a,b in ((9,31,59),(10,0,59),(11,0,30),(13,1,59),(14,0,59)) for m in range(a,b+1)]+['15:00']
idx={s:i for i,s in enumerate(slots)}; S=len(slots)
syms=[r[0] for r in c.execute('select symbol from stocks order by symbol').fetchall()]
keys=[];PC=[];AUC=[]
C=[];O=[];Hh=[];L=[];V=[];A=[];B=[];Sv=[]
t=time.time()
for sym in syms:
    d=c.execute("""select b.date, b.minute, b.open,b.high,b.low,b.close,b.volume::double v,b.amount,
        coalesce(b.buy_volume::double,'nan'::double) bv, coalesce(b.sell_volume::double,'nan'::double) sv, s.prev_close
        from bars_1m b join stock_days s using(symbol,date) where b.symbol=? and s.usable_ticks order by b.date,b.minute""",[sym]).fetchnumpy()
    dates=np.asarray(d['date']); mins=np.asarray(d['minute']).astype(str)
    bounds=np.flatnonzero(np.r_[True,dates[1:]!=dates[:-1],True])
    for a,b in zip(bounds[:-1],bounds[1:]):
        day=str(dates[a])[:10]
        g={k:np.full(S,np.nan) for k in 'COHLVABS'}
        auc=np.nan
        for j in range(a,b):
            m=mins[j]
            if m<'09:30':
                auc=d['open'][j]; continue
            i=idx.get(m)
            if i is None: continue
            g['C'][i]=d['close'][j];g['O'][i]=d['open'][j];g['H'][i]=d['high'][j];g['L'][i]=d['low'][j]
            g['V'][i]=d['v'][j];g['A'][i]=d['amount'][j];g['B'][i]=d['bv'][j];g['S'][i]=d['sv'][j]
        keys.append((sym,day));PC.append(float(d['prev_close'][a]));AUC.append(auc)
        for arr,k in ((C,'C'),(O,'O'),(Hh,'H'),(L,'L'),(V,'V'),(A,'A'),(B,'B'),(Sv,'S')): arr.append(g[k])
    print(sym,len(keys),round(time.time()-t,1),flush=True)
np.savez_compressed(os.environ.get('GST_GRID', f'{H}/research/grid.npz'),sym=np.array([k[0] for k in keys]),date=np.array([k[1] for k in keys]),
    prev_close=np.array(PC),auction=np.array(AUC),slots=np.array(slots),
    C=np.array(C),O=np.array(O),H=np.array(Hh),L=np.array(L),V=np.array(V),A=np.array(A),B=np.array(B),S=np.array(Sv))
print('done',time.time()-t)
