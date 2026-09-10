"""Rerun frozen research studies and compare the complete descendant graph."""
import json
from datetime import date
from pathlib import Path
from uuid import UUID
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import load_record_fields, LocalExperimentStore
from quantlab.storage.frozen_inputs import load_frozen_inputs

KINDS=('factor','holdout','walkforward','sweep','ablation','theory_study','correlation','correlation_holdout','correlation_walkforward')
# Project only numerical evidence and lineage; avoid loading huge rendering audits.
FIELDS={'run_id','experiment_id','status','kind','manifest','children','periods','folds','metrics',
        'baseline_metrics','regime_summary','context_baseline_metrics','context_summary','inference',
        'comparisons','contrasts','stability','pairs','groups','coverage','selection_summary','processor_audit','summary'}


def config_from_record(cfg, correlation=False):
    from quantlab.data.base import DataRequest
    from quantlab.domain import Timeframe
    from quantlab.experiments.config import ExperimentConfig
    from quantlab.experiments.correlation import CorrelationConfig
    from quantlab.regime.config import RegimeConfig, RegimeFilter
    from quantlab.statistics.bootstrap import BootstrapConfig
    from quantlab.statistics.permutation import PermutationConfig
    from quantlab.multitimeframe.config import DailyContextConfig
    from quantlab.processing.pipeline import PipelineConfig
    from quantlab.processing.cross_section import CrossSectionConfig
    values=dict(cfg);r=cfg['data']
    values['data']=DataRequest(tuple(r['symbols']),Timeframe(r['timeframe']),date.fromisoformat(r['start']),date.fromisoformat(r['end']))
    for name,cls in [('regime',RegimeConfig),('regime_filter',RegimeFilter),('bootstrap',BootstrapConfig),('permutation',PermutationConfig)]:
        if values.get(name) is not None:values[name]=cls(**values[name])
    if values.get('processor') is not None:
        p=values['processor'];values['processor']=PipelineConfig(**p) if 'steps' in p else CrossSectionConfig(**p)
    if values.get('context') is not None:
        c=values['context'];values['context']=DailyContextConfig(**{**c,'start':date.fromisoformat(c['start'])})
    if 'horizons' in values:values['horizons']=tuple(values['horizons'])
    return (CorrelationConfig if correlation else ExperimentConfig)(**values)


def _references(record):
    for key in ('children','periods','folds'):
        for item in record.get(key,[]):
            if 'run_id' in item:yield item['run_id']


def _graph(path):
    result={};active=set();root=path.parent
    def visit(run_id):
        if str(UUID(run_id))!=run_id:raise ValueError('Invalid archive run id')
        if run_id in active:raise ValueError('Cyclic archive lineage')
        if run_id in result:return
        folder=root/run_id
        if folder.is_symlink():raise ValueError('Child must be a local archive')
        record=load_record_fields(folder/'experiment.json',FIELDS)
        if record['run_id']!=run_id or record['experiment_id']!=digest(record['manifest']):raise ValueError('Archive identity mismatch: '+run_id)
        if record['status']!='completed':raise ValueError('复算要求完整成功的研究及子实验；失败记录保留为证据')
        active.add(run_id);result[run_id]=record
        for child in _references(record):visit(child)
        active.remove(run_id)
    visit(path.name)
    return result


def reproduce_research(artifact, output):
    from quantlab.app import default_registry
    from quantlab.experiments.runner import ExperimentRunner, runtime_fingerprint
    from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
    from quantlab.experiments.walkforward import WalkForwardConfig, WalkForwardRunner
    from quantlab.experiments.sweep import ParameterGrid, SweepRunner
    from quantlab.experiments.ablation import AblationRunner
    from quantlab.experiments.theory_study import TheoryStudyPlan, TheoryStudyRunner
    from quantlab.experiments.correlation import CorrelationRunner
    from quantlab.storage.bundle import _compare_reproduction
    path=Path(artifact);graph=_graph(path);record=graph[path.name];manifest=record['manifest'];kind=record.get('kind','factor')
    if kind not in KINDS:raise ValueError('Unsupported research kind: '+kind)
    runtime=runtime_fingerprint()
    if any(r['manifest'].get('runtime')!=runtime for r in graph.values()):raise ValueError('Source/interpreter/dependency fingerprint differs; use matching source and environment')
    # Validate every archived input before launching any new experiment.
    for run_id,r in graph.items():
        if 'frozen_inputs' in r['manifest']:load_frozen_inputs(path.parent/run_id,r['manifest'])
    data,universe=load_frozen_inputs(path,manifest)
    config=config_from_record(manifest['config'],kind.startswith('correlation'))
    runner=ExperimentRunner(data,default_registry(),universe,LocalExperimentStore(output))
    split=lambda value:ChronologicalSplit(**{k:date.fromisoformat(v) for k,v in value.items()})
    if kind=='factor':result=runner.run(config)
    elif kind=='holdout':result=HoldoutRunner(runner).run(config,split(manifest['split']))
    elif kind=='walkforward':result=WalkForwardRunner(runner).run(config,WalkForwardConfig(**manifest['schedule']))
    elif kind=='sweep':result=SweepRunner(runner).run(config,ParameterGrid(**manifest['grid']),split=split(manifest['split']) if manifest.get('split') else None,schedule=WalkForwardConfig(**manifest['schedule']) if manifest.get('schedule') else None)
    elif kind=='ablation':result=AblationRunner(runner).run(config)
    elif kind=='theory_study':result=TheoryStudyRunner(runner).run(config,TheoryStudyPlan.parse(manifest['plan']))
    elif kind=='correlation_holdout':
        from quantlab.experiments.correlation_holdout import CorrelationHoldoutRunner
        result=CorrelationHoldoutRunner(runner).run(config,split(manifest['split']))
    elif kind=='correlation_walkforward':
        from quantlab.experiments.correlation_walkforward import CorrelationWalkForwardRunner
        result=CorrelationWalkForwardRunner(runner).run(config,WalkForwardConfig(**manifest['schedule']))
    else:result=CorrelationRunner(runner).run(config)
    verification={'source_run_id':path.name,'run_id':result.run_id,'artifact_path':str(result.artifact_path),'status':'not_verified','checked_runs':0,
        'scope':'Rebuilt parent study and descendants from frozen bars and eligibility metadata; compare identities, metrics, inference, context/regime summaries and all observation columns. rtol=1e-9, atol=1e-12.'}
    try:
        actual=_graph(result.artifact_path);mapping={}
        def pair(old,new):
            if old in mapping:
                if mapping[old]!=new:raise ValueError('Reproduction lineage sharing differs')
                return
            mapping[old]=new;a=list(_references(graph[old]));b=list(_references(actual[new]))
            if len(a)!=len(b):raise ValueError('Reproduction child count differs')
            for x,y in zip(a,b):pair(x,y)
        pair(path.name,result.run_id)
        if len(mapping)!=len(graph) or len(set(mapping.values()))!=len(actual):raise ValueError('Reproduction graph differs')
        def normalized(value,old):
            if isinstance(value,dict):return {k:normalized(v,old) for k,v in value.items() if k!='artifact_path'}
            if isinstance(value,list):return [normalized(v,old) for v in value]
            if old and isinstance(value,str):return mapping.get(value,value)
            return value
        for old,new in mapping.items():
            _compare_reproduction(normalized(graph[old],True),normalized(actual[new],False),'run/'+old)
            left=path.parent/old/'observations.parquet';right=Path(output)/new/'observations.parquet'
            if left.exists()!=right.exists():raise ValueError('Observation artifact availability differs')
            if left.exists():assert_frame_equal(pl.read_parquet(left),pl.read_parquet(right),check_exact=False,rel_tol=1e-9,abs_tol=1e-12)
            verification['checked_runs']+=1
        verification.update(status='numerically_matched',run_mapping=mapping)
    except Exception as error:
        verification.update(status='mismatch',error=str(error))
        raise ValueError(f'复算不一致：{error}；核对记录：{result.artifact_path}/reproduction.json') from error
    finally:(result.artifact_path/'reproduction.json').write_text(encode(verification))
    return verification
