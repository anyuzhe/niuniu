"""Compute the repo's boolean theory factors (ICT, SMC, Brooks, Wyckoff, Chan rule/inclusion, zones, sequences...) on
5-minute bars per stock-year and store the bars where each fires. Research only. Usage: run_theory.py WORKER NWORKERS"""
import polars as pl, sys, os, time, traceback
sys.path.insert(0,'/home/claude/niuniu/src')
from quantlab.app import default_registry
from quantlab.domain import FactorType
W,N=int(sys.argv[1]),int(sys.argv[2])
df=pl.read_parquet(__import__('os').environ.get('THEORY_BARS','bars.parquet'))
sample={y:sorted(df.filter(pl.col('year')==y)['symbol'].unique().to_list())[::2] for y in range(2020,2027)}
tasks=[(y,s) for y in range(2020,2027) for s in sample[y]]
r=default_registry()
F=[(D.factor_id,D.version) for D in (d['definition'] for d in r.describe())
   if D.factor_type==FactorType.BOOLEAN and D.category!='quant' and not D.factor_id.startswith('CHAN.CLASSIC')]
os.makedirs('sig',exist_ok=True)
def prep(d):
    ts=(pl.col('date')+' '+pl.col('hm').str.slice(0,2)+':'+pl.col('hm').str.slice(2,2)).str.to_datetime('%Y-%m-%d %H:%M').dt.replace_time_zone('Asia/Shanghai')
    return d.with_columns(ts.alias('datetime')).with_columns(pl.col('datetime').alias('available_at'),pl.lit('5m').alias('timeframe')).select('symbol','datetime','available_at','timeframe','open','high','low','close','volume','turnover').sort('symbol','datetime')
for k,(y,s) in enumerate(tasks):
    if k%N!=W: continue
    out=f'sig/{y}_{s}.parquet'
    if os.path.exists(out): continue
    t=time.time(); b=prep(df.filter((pl.col('year')==y)&(pl.col('symbol')==s)))
    parts=[]
    for fid,ver in F:
        f=r.get(fid,ver)
        try:
            v=f.compute(b,f.parameters({})).filter(pl.col('value')==1).select('datetime').with_columns(pl.lit(fid).alias('factor'))
            parts.append(v)
        except Exception as e:
            print('ERR',y,s,fid,type(e).__name__,str(e)[:80],flush=True)
    pl.concat(parts).with_columns(pl.lit(s).alias('symbol'),pl.lit(y).alias('year')).write_parquet(out)
    print(W,k,len(tasks),y,s,b.height,round(time.time()-t,1),flush=True)
