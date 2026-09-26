import os, sys, types, json, typing, typing_extensions
typing.Self = typing_extensions.Self
sys.path.insert(0, 'src')
for p in ('trading','adapters','data'):
    if f'quantlab.{p}' not in sys.modules:
        m=types.ModuleType(f'quantlab.{p}'); m.__path__=[f'src/quantlab/{p}']; sys.modules[f'quantlab.{p}']=m
from quantlab.intraday.gst import GstIntraday
from quantlab.intraday import backtest
from quantlab.intraday.t0 import T0Config, Costs
H=os.environ['HOME']
r = GstIntraday(path=f'{H}/mnt/lake/silver/gst_intraday/gst_intraday.duckdb', status_dir=f'{H}/mnt/lake/bronze/provider=baostock/daily_status_v2')
low=Costs(commission=0.0001,commission_min=0,stamp_before=0.0005,stamp_after=0.0005,slippage_ticks=1.0)
for key in sys.argv[1:]:
    cfg=backtest.STRATEGY_CONFIG.get(key) if hasattr(backtest,'STRATEGY_CONFIG') else None
    res=backtest.run_backtest(r,key,config=T0Config(costs=low))
    out={'summary':res['summary'],'per_year':res['per_year']}
    json.dump(out,open(f'{H}/fees_{key}.json','w'),ensure_ascii=False,default=str)
    s1,s2=res['summary']['train'],res['summary']['test']
    print(f"{key:16s} train trips={s1.get('trips')} trip={s1.get('avg_trip_bps')} raw={s1.get('avg_raw_bps')} win={s1.get('win_rate')} t={s1.get('t_stat')} | test trips={s2.get('trips')} trip={s2.get('avg_trip_bps')} raw={s2.get('avg_raw_bps')} win={s2.get('win_rate')} t={s2.get('t_stat')} ann={s2.get('annual_pct')}% | years {[(y['year'],y['trips'],y.get('avg_trip_bps')) for y in res['per_year']]}",flush=True)
