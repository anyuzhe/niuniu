from pathlib import Path
from datetime import date,timedelta
from dataclasses import replace
import json
import polars as pl
from quantlab.app import build_runner
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.execution import ExecutionStudy
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.rules import MarketRules
from quantlab.experiments.residual import run_residual
from quantlab.regime.config import RegimeConfig
from quantlab.storage.codec import encode
root=Path(__file__).resolve().parents[1]
symbols=('sh.600519','sz.000001','sz.000858','sh.601318','sz.300750')
runner=build_runner(Path('/Volumes/Lexar/niuniu-data'),root/'artifacts',symbols)
data=DataRequest(symbols,Timeframe.MIN5,date(2026,8,3),date(2026,9,4))
cfg=ExperimentConfig('真实行情因子残差验收',data,'BASE.MOMENTUM','1.0.0',parameters={'lookback':5},horizons=(1,5),regime=RegimeConfig(),replay=True)
a=runner.run(cfg);b=runner.run(replace(cfg,parameters={'lookback':20}))
residual=run_residual(a.artifact_path,[b.artifact_path],date(2026,8,14),root/'artifacts',5)
market=pl.read_parquet(a.artifact_path/'bars.parquet');records=[]
for symbol in symbols:
    for day in sorted(market['datetime'].dt.date().unique().to_list()):
        at=market['datetime'][0].replace(year=day.year,month=day.month,day=day.day,hour=0,minute=0,second=0)
        # Explicit simulation fixture: no claims about actual ST/suspension/official limits.
        records.append({'symbol':symbol,'effective_at':at,'available_at':at,'expires_at':at+timedelta(days=1),
            'suspended':False,'st':False,'limit_up':None,'limit_down':None,'commission_bps':3.,
            'minimum_commission':5.,'sell_tax_bps':5.,'transfer_bps':.1,'source':'SYNTHETIC_ACCEPTANCE_ONLY: assumed tradable/unbounded; not historical exchange rules'})
rules_path=root/'artifacts/acceptance-inputs/synthetic-market-rules.json';rules_path.write_text(encode(records))
execution=ExecutionStudy(runner).run(replace(cfg,research_question='真实 MQC 行情 + 明示模拟规则的 vn.py 记账验收'),
    ExecutionConfig(**json.loads((root/'examples/rule_aware_execution.json').read_text())),backend='vnpy_rules',market_rules=MarketRules(records))
result={'candidate':str(a.artifact_path),'control':str(b.artifact_path),'residual':residual,'execution':execution,'rules':str(rules_path)}
(root/'artifacts/acceptance-inputs/results.json').write_text(encode(result))
print(encode(result))
