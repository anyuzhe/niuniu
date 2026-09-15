"""Register first, run real fixed-history experiments, then bind/report via CLI."""
import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from quantlab.app import build_runner
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.ablation import _LoadedData
from quantlab.statistics.permutation import PermutationConfig,holm
from quantlab.storage.codec import encode

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('/Volumes/Lexar/niuniu-data'));args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    symbols=('sh.600000','sh.600036','sh.600276','sh.600309','sh.600519','sh.600887','sh.601166','sh.601288','sh.601318','sh.601328',
        'sh.601398','sh.601857','sz.000001','sz.000002','sz.000333','sz.000651','sz.000858','sz.002415','sz.002594','sz.300750')
    request=DataRequest(symbols,Timeframe.MIN5,date(2026,8,3),date(2026,9,4))
    configs={name:ExperimentConfig('固定族验收 '+name,request,'BASE.MOMENTUM',parameters={'lookback':n},
        horizons=(1,5,20),permutation=PermutationConfig(99,3)) for name,n in
        [('momentum10',10),('momentum20',20),('invalid_parameter',0),('reserved_unrun',40)]}
    plan={'name':'二十证券固定研究族流程验收','alpha':.05,
          'trials':[{'trial_id':name,'config':asdict(cfg)} for name,cfg in configs.items()]}
    plan_path=args.output/'plan.json';plan_path.write_text(encode(plan));registry=args.output/'registry'
    commands=[]
    def cli(*parts):
        command=[sys.executable,'-m','quantlab.cli',*map(str,parts)]
        run=subprocess.run(command,capture_output=True,text=True,check=True)
        commands.append({'command':command,'exit_code':run.returncode})
        return json.loads(run.stdout)
    cli('trials-create','--plan',plan_path,'--output',registry)
    runner=build_runner(args.data_root,args.output/'runs',symbols);batch=runner.data.load(request)
    runner.data=_LoadedData(batch,request);batch.bars.write_parquet(args.output/'bars.parquet')
    (args.output/'data-snapshot.json').write_text(encode(batch.snapshot))
    artifacts={}
    for name,cfg in configs.items():
        if name=='reserved_unrun':continue
        if name=='invalid_parameter':
            existing=set((args.output/'runs').glob('*/experiment.json'))
            try:runner.run(cfg)
            except ValueError:
                new=set((args.output/'runs').glob('*/experiment.json'))-existing
                assert len(new)==1
                path=next(iter(new));assert json.loads(path.read_text())['status']=='failed'
            else:raise AssertionError('Invalid parameter unexpectedly succeeded')
        else:path=runner.run(cfg).artifact_path/'experiment.json'
        artifacts[name]=str(path)
        cli('trials-bind','--registry',registry,'--trial-id',name,'--artifact',path)
    assert cli('trials-bind','--registry',registry,'--trial-id','momentum10','--artifact',artifacts['momentum10'])['status']=='unchanged'
    result=cli('trials-report','--registry',registry,'--output',args.output/'family-report')
    assert result['planned_tests']==24 and result['available_tests']==12
    assert [t['status'] for t in result['trials']]==['completed','completed','failed','not_run']
    assert all(t['timing']=='after_local_registration' for t in result['trials'] if t['status']!='not_run')
    assert [t['p_holm'] for t in result['tests']]==holm([t['p_value'] for t in result['tests']])
    summary={'status':'completed','rows':batch.bars.height,'symbols':len(symbols),'registered_trials':4,
        'planned_tests':24,'available_tests':12,'rejected_tests':sum(t['reject_holm'] is True for t in result['tests']),
        'artifacts':artifacts,'commands':commands,'limitations':'invalid_parameter is an intentional failure-control; historical sample is not unseen data'}
    (args.output/'result.json').write_text(encode(summary));print(encode(summary))
