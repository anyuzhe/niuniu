"""Fixed, explicitly selected universe; retain all results, no winner selection.
Run once per output experiment; raw execution results omit corporate actions.
"""
from pathlib import Path
from datetime import date
from dataclasses import replace
import json
from quantlab.app import build_runner
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.theory_study import TheoryStudyPlan,TheoryStudyRunner
from quantlab.experiments.holdout import ChronologicalSplit
from quantlab.experiments.walkforward import WalkForwardConfig
from quantlab.theory.templates import resolve_template
from quantlab.experiments.execution import ExecutionStudy
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.portfolio import PortfolioConfig
from quantlab.experiments.return_increment import compare_returns
from quantlab.storage.codec import encode

root=Path(__file__).resolve().parents[1]
symbols=('sh.600519','sz.000001','sz.000858','sh.601318','sz.300750','sh.600000','sh.600036','sh.600276','sh.600309','sh.600887',
 'sh.601166','sh.601398','sh.601288','sh.601328','sh.601857','sz.000002','sz.000333','sz.000651','sz.002415','sz.002594')
request=DataRequest(symbols,Timeframe.DAILY,date(2025,1,1),date(2026,9,4))
plan={'symbols':symbols,'start':request.start,'end':request.end,'train_end':'2025-08-31','valid_end':'2025-12-31',
 'theories':['RESEARCH.BROOKS_SECOND_ENTRY','RESEARCH.ICT_MSS_FVG','RESEARCH.WYCKOFF_SOS_MOMENTUM'],
 'execution_pair':'fixed momentum lookback 5 versus 20; identical inverse-volatility portfolio and costs',
 'limitations':'Explicit present-day selected stocks; selection/survivorship bias. No certified historical rules or corporate-action accounting. OOS repeatedly observed is exploratory.'}
out=root/'artifacts/data-acceptance';out.mkdir(parents=True,exist_ok=True)
with (out/'expanded-plan.json').open('x') as handle:handle.write(encode(plan))
runner=build_runner(Path('/Volumes/Lexar/MQC-DATA'),root/'artifacts',symbols);results=[]
for template,alias,grid in [('RESEARCH.BROOKS_SECOND_ENTRY','entry',{'trend_lookback':[10,20]}),
 ('RESEARCH.ICT_MSS_FVG','mss',{'atr_multiple':[1.5,2.]}),('RESEARCH.WYCKOFF_SOS_MOMENTUM','sos',{'lookback':[10,20]})]:
 try:
  params,origin=resolve_template(template,runner.registry)
  cfg=ExperimentConfig('扩样本验证 '+template,request,'COMB.CONDITION','1.0.0',parameters=params,theory_origin=origin,horizons=(1,5,20))
  study=TheoryStudyRunner(runner).run(cfg,TheoryStudyPlan(ChronologicalSplit(date(2025,8,31),date(2025,12,31)),WalkForwardConfig(240,60,90),alias,grid))
  results.append({'name':template,'status':'completed','run_id':study.run_id,'path':str(study.artifact_path)})
 except Exception as error:results.append({'name':template,'status':'failed','error':str(error)})
 (out/'expanded-results.json').write_text(encode(results));print(results[-1],flush=True)
execution=ExecutionConfig(initial_cash=1000000,top_n=5,max_actual_position=.25,max_actual_exposure=.8)
portfolio=PortfolioConfig(weighting='inverse_volatility',max_position=.25,max_exposure=.8)
base=ExperimentConfig('固定动量窗口收益增量验收',request,'BASE.MOMENTUM','1.0.0',parameters={'lookback':5},horizons=(1,5))
a=ExecutionStudy(runner).run(base,execution,portfolio)
b=ExecutionStudy(runner).run(replace(base,parameters={'lookback':20}),execution,portfolio)
r=compare_returns(a.artifact_path,b.artifact_path,date(2026,1,1),root/'artifacts')
results.append({'name':'return_increment','status':'completed','candidate':str(a.artifact_path),'baseline':str(b.artifact_path),**r})
(out/'expanded-results.json').write_text(encode(results));print(results[-1],flush=True)
