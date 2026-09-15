"""Real MQC bars + imported retrospective cash records. No official-rule claim."""
from dataclasses import replace
from datetime import date
from pathlib import Path
import json
import polars as pl
from quantlab.app import build_runner
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.execution import ExecutionStudy
from quantlab.execution.backtest import ExecutionConfig
from quantlab.storage.codec import encode

if __name__=='__main__':
    output=Path('artifacts/phase4-acceptance')
    imported=json.loads((output/'dividends.json').read_text())
    start,end=date(2025,1,1),date(2026,9,4)
    symbol='sh.600000'
    unresolved=[r for r in imported['unresolved'] if r['symbol']==symbol and r.get('source_record',{}).get('dividOperateDate','')>=start.isoformat()]
    if unresolved:raise ValueError('Unresolved company actions in requested window')
    actions=[r for r in imported['corporate_actions'] if r['symbol']==symbol and start.isoformat()<=r['record_at'][:10]<=end.isoformat()]
    cfg=ExecutionConfig(initial_cash=100000,top_n=1,exposure=.5,threshold=-1,corporate_actions=actions,corporate_action_mode='retrospective')
    (output/'cash-execution.json').write_text(encode(cfg))
    runner=build_runner(Path('/Volumes/Lexar/niuniu-data'),Path('artifacts'),(symbol,),'raw')
    research=ExperimentConfig('真实 raw K 线现金分红账务核对；税率 0 假设，非严格 PIT，无官方交易规则',
        DataRequest((symbol,),Timeframe.DAILY,start,end),'BASE.MOMENTUM',parameters={'lookback':5},horizons=(1,5),replay=True)
    result=ExecutionStudy(runner).run(research,cfg,backend='vnpy_rules')
    (output/'cash-execution-result.json').write_text(encode(result))
    print(encode(result))
