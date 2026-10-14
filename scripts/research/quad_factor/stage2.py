import sys, pickle, time
from pathlib import Path
import polars as pl
REPO=Path(sys.argv[1]); OUT=sys.argv[2]
sys.path.insert(0,str(REPO/'src'))
import quantlab.progress as pg
t0=time.time()
def cp(label,*a):
    if a and a[0]%100==0: print(label,a,round(time.time()-t0),flush=True)
pg.checkpoint=cp
from quantlab.execution.backtest import OpenExecutionBacktester, ExecutionConfig
bars=pl.read_parquet(OUT+'.bars.parquet'); targets=pl.read_parquet(OUT+'.targets.parquet')
cfg=ExecutionConfig(initial_cash=float(__import__('os').environ.get('CASH','1e8')), top_n=20, lot_size=100, t_plus_one=True, commission_bps=1.0, minimum_commission=5.0, slippage_bps=1.0, statutory_fees=True, price_mode='research')
curve,fills,rej,summary=OpenExecutionBacktester(cfg).run(targets,bars)
pickle.dump({'curve':curve,'fills':fills,'rejections':rej,'summary':summary},open(OUT+'.engine'+__import__('os').environ.get('CASH','1e8')+'.pkl','wb'))
print('engine done',round(time.time()-t0),len(fills),len(rej),flush=True)
