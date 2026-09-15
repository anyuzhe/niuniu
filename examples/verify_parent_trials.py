"""Register four native parent designs before reading/running fixed historical data."""
import argparse
import json
import subprocess
import sys
from dataclasses import asdict,replace
from datetime import date
from pathlib import Path
from quantlab.app import build_runner,default_registry
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.ablation import AblationRunner,_LoadedData
from quantlab.experiments.holdout import ChronologicalSplit,HoldoutRunner
from quantlab.experiments.walkforward import WalkForwardConfig,WalkForwardRunner
from quantlab.experiments.sweep import ParameterGrid,SweepRunner
from quantlab.statistics.permutation import PermutationConfig,holm
from quantlab.theory.templates import resolve_template
from quantlab.storage.codec import encode

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('/Volumes/Lexar/niuniu-data'));args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    symbols=('sh.600000','sh.600036','sh.600276','sh.600309','sh.600519','sh.600887','sh.601166','sh.601288','sh.601318','sh.601328',
        'sh.601398','sh.601857','sz.000001','sz.000002','sz.000333','sz.000651','sz.000858','sz.002415','sz.002594','sz.300750')
    request=DataRequest(symbols,Timeframe.MIN5,date(2026,8,3),date(2026,9,4))
    base=ExperimentConfig('父研究登记验证',request,'BASE.MOMENTUM',parameters={'lookback':10},horizons=(1,5),permutation=PermutationConfig(99,1))
    params,origin=resolve_template('RESEARCH.TREND_BREAKOUT',default_registry())
    configs={kind:replace(base,research_question='父研究 '+kind) for kind in ('ablation','holdout','walkforward','sweep')}
    configs['ablation']=replace(configs['ablation'],factor_id='COMB.CONDITION',parameters=params,theory_origin=origin,incremental_test=True)
    split=ChronologicalSplit(date(2026,8,14),date(2026,8,21));schedule=WalkForwardConfig(12,7,14);grid=ParameterGrid({'lookback':[10,20]})
    designs={'ablation':{},'holdout':{'split':asdict(split)},'walkforward':{'schedule':asdict(schedule)},
        'sweep':{'grid':asdict(grid),'split':asdict(split),'schedule':None}}
    trials=[{'trial_id':kind,'config':asdict(cfg),'study':{'kind':kind,'design':designs[kind]}} for kind,cfg in configs.items()]
    trials.append({'trial_id':'reserved_ablation','config':asdict(replace(configs['ablation'],research_question='未运行保留')),
        'study':{'kind':'ablation','design':{}}})
    plan=args.output/'plan.json';plan.write_text(encode({'name':'父研究与配对差异固定族','alpha':.05,'trials':trials}))
    registry=args.output/'registry';commands=[]
    def cli(*parts):
        command=[sys.executable,'-m','quantlab.cli',*map(str,parts)]
        result=subprocess.run(command,capture_output=True,text=True,check=True)
        commands.append({'command':command,'exit_code':result.returncode});return json.loads(result.stdout)
    cli('trials-create','--plan',plan,'--output',registry)
    runner=build_runner(args.data_root,args.output/'runs',symbols);batch=runner.data.load(request);runner.data=_LoadedData(batch,request)
    batch.bars.write_parquet(args.output/'bars.parquet');(args.output/'snapshot.json').write_text(encode(batch.snapshot))
    paths={}
    for kind,cfg in configs.items():
        if kind=='ablation':result=AblationRunner(runner).run(cfg)
        elif kind=='holdout':result=HoldoutRunner(runner).run(cfg,split)
        elif kind=='walkforward':result=WalkForwardRunner(runner).run(cfg,schedule)
        else:result=SweepRunner(runner).run(cfg,grid,split=split)
        paths[kind]=str(result.artifact_path)
        cli('trials-bind','--registry',registry,'--trial-id',kind,'--artifact',result.artifact_path)
    report=cli('trials-report','--registry',registry,'--output',args.output/'family-report')
    assert report['planned_tests']==88
    assert sum(t['status']=='not_run' for t in report['tests'])==20
    assert sum(t['metric'].endswith('_difference') and t['trial_id']=='ablation' for t in report['tests'])==8
    assert [t['p_holm'] for t in report['tests']]==holm([t['p_value'] for t in report['tests']])
    assert all(t['timing']=='after_local_registration' for t in report['trials'] if t['status']!='not_run')
    summary={'status':'completed','rows':batch.bars.height,'symbols':len(symbols),'planned_tests':report['planned_tests'],
        'available_tests':report['available_tests'],'unavailable_tests':sum(t['status']=='unavailable' for t in report['tests']),
        'not_run_tests':20,'rejected_tests':sum(t['reject_holm'] is True for t in report['tests']),
        'artifacts':paths,'commands':commands}
    (args.output/'result.json').write_text(encode(summary));print(encode(summary))
