"""Read-only MQC evidence for aggregation, information alignment and added packs."""
from dataclasses import replace
from datetime import date
from pathlib import Path
import json,time
import polars as pl
from quantlab.app import default_registry
from quantlab.data.mqc import MQCParquetProvider
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.multitimeframe.engine import MultiTimeframeEngine
from quantlab.factors.engine import compute_factor
from quantlab.causal import assert_prefix_invariant
from quantlab.storage.codec import encode

root=Path('artifacts/core-completion');results={};provider=MQCParquetProvider(Path('/Volumes/Lexar/niuniu-data'),'qfq')
request=DataRequest(('sh.600000','sz.000001'),Timeframe.MIN5,date(2026,8,24),date(2026,9,4))
base=provider.load(request);registry=default_registry();periods=[]
for timeframe in (Timeframe.MIN15,Timeframe.MIN30,Timeframe.MIN60):
    high=replace(request,timeframe=timeframe);aggregate=provider.load(high)
    aligned=MultiTimeframeEngine(provider,registry).load(request,high,'BASE.MOMENTUM',parameters={'lookback':2},low_batch=base)
    assert aligned.frame.filter(pl.col('context_available_at')>pl.col('available_at')).height==0
    assert aggregate.bars['volume'].sum()==base.bars['volume'].sum()
    periods.append({'timeframe':timeframe.value,'bars':aggregate.bars.height,'source_bars':base.bars.height,
        'snapshot':aggregate.snapshot.snapshot_id,'context_id':aligned.context_id,'early_context_rows':0})
results['multitimeframe']=periods
try:provider.load(replace(request,timeframe=Timeframe.MIN1))
except FileNotFoundError:results['missing_1m']='Rejected missing source; never synthesized from 5m'
source=MQCParquetProvider(Path('artifacts/chan-500-full-ten-year-qfq/data'),'qfq')
spec=json.loads(Path('artifacts/chan-500-full-ten-year-qfq/client-spec.json').read_text())
daily=source.load(DataRequest(tuple(spec['symbols'][:5]),Timeframe.DAILY,date(2025,1,1),date(2026,9,4)))
checks=[]
for item in registry.describe():
    factor=registry.get(item['definition']['factor_id'],item['definition']['version']) if isinstance(item['definition'],dict) else registry.get(item['definition'].factor_id,item['definition'].version)
    identifier=factor.definition.factor_id
    if not identifier.startswith(('ALPHA101.','ALPHA158.','ICT.BREAKER','ICT.RANGE_POSITION','ICT.PREMIUM','ICT.DISCOUNT')):continue
    parameters=factor.parameters({});values=compute_factor(factor,daily.bars,parameters)
    dates=daily.bars['available_at'].unique().sort();cut=dates[len(dates)//2]
    prefix=compute_factor(factor,daily.bars.filter(pl.col('available_at')<=cut),parameters)
    expected=values.filter(pl.col('available_at')<=cut)
    difference=prefix.join(expected,on=['symbol','datetime','available_at'],suffix='_full').select((pl.col('value')-pl.col('value_full')).abs().max()).item()
    from polars.testing import assert_frame_equal
    try:assert_frame_equal(prefix,expected,check_exact=True)
    except AssertionError:
        print(identifier,'max_abs_difference',difference,'null_counts',prefix['value'].null_count(),expected['value'].null_count(),flush=True)
        try:assert_frame_equal(prefix,expected,check_exact=False,rel_tol=1e-9,abs_tol=1e-10)
        except AssertionError:
            prefix.write_parquet(root/(identifier+'-prefix.parquet'));expected.write_parquet(root/(identifier+'-expected.parquet'));raise

    checks.append({'factor_id':identifier,'rows':values.height,'non_null':values['value'].len()-values['value'].null_count(),'prefix_check':'passed_at_rtol_1e-9_atol_1e-10','max_abs_difference':difference})
results['factors']=checks;results['daily_snapshot']=daily.snapshot.snapshot_id
(root/'realdata-verification.json').write_text(encode(results));print('Verified',len(checks),'factors and',len(periods),'aggregations')
