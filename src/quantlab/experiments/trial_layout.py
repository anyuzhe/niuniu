"""Data-free planned test trees for existing parent study runners."""
import json
from datetime import date
from quantlab.storage.codec import encode

COLLECTIONS = ('children','periods','folds','evaluations','contrasts')
KINDS = {'ablation':set(), 'holdout':{'split'}, 'walkforward':{'schedule'}, 'sweep':{'grid','split','schedule'}, 'theory_study':{'plan'}}


def planned_layout(trial):
    from quantlab.app import default_registry
    from quantlab.data.base import DataRequest
    from quantlab.domain import Timeframe
    from quantlab.experiments.ablation import variants
    from quantlab.experiments.holdout import ChronologicalSplit
    from quantlab.experiments.walkforward import WalkForwardConfig
    from quantlab.experiments.sweep import ParameterGrid
    from quantlab.factors.combinations import CombinationFactor
    cfg=trial['config'];study=trial['study']
    if not isinstance(study,dict) or set(study)!={'kind','design'} or study['kind'] not in KINDS:
        raise ValueError('Supported parent kinds: ablation, holdout, walkforward, sweep, theory_study')
    kind=study['kind'];design=study['design']
    if not isinstance(design,dict) or set(design)!=KINDS[kind]:
        raise ValueError('Parent design must include exactly the required split/schedule/grid fields')
    if cfg.get('incremental_test') and kind!='ablation':
        raise ValueError('Paired IC registry requires an ablation study')
    registry=default_registry();factor=registry.get(cfg['factor_id'],cfg.get('factor_version','1.0.0'))
    def request():
        d=cfg['data']
        return DataRequest(tuple(d['symbols']),Timeframe(d['timeframe']),date.fromisoformat(d['start']),date.fromisoformat(d['end']))
    def periods(split,req):
        split=ChronologicalSplit(**{k:date.fromisoformat(v) for k,v in split.items()})
        return [{'name':name,'start':start,'end':end,'_metrics':'standard'} for name,start,end in split.periods(req)]
    def folds(schedule,req):
        return [{**w,'periods':periods({'train_end':w['train_end'].isoformat(),'valid_end':w['valid_end'].isoformat()},
            DataRequest(req.symbols,req.timeframe,w['start'],w['end']))} for w in WalkForwardConfig(**schedule).windows(req)]
    if kind=='theory_study':
        from dataclasses import asdict
        from types import SimpleNamespace
        from quantlab.experiments.theory_study import TheoryStudyPlan, component_specs
        plan=TheoryStudyPlan.parse(design['plan'])
        grid=plan.variants(SimpleNamespace(**{**cfg,'data':request(),'factor_version':cfg.get('factor_version','1.0.0')}),registry)
        params=factor.parameters(cfg['parameters'])
        children=[{'name':'组件 '+component.definition.factor_id,'_metrics':'standard'} for component,_ in component_specs(params,registry)]
        children.append({'name':'完整组合','_metrics':'standard'})
        def child(name,child_kind,child_design,extra=None):
            child_config={**cfg,**(extra or {})}
            if child_kind=='holdout' and isinstance(child_config.get('processor'),dict) and 'steps' in child_config['processor']:
                child_config['processor']={**child_config['processor'],'fit_start':cfg['data']['start'],'fit_end':design['plan']['split']['train_end']}
            layout=planned_layout({'config':child_config,'study':{'kind':child_kind,'design':child_design}})
            children.append({'name':name,**layout})
        child('逐输入消融','ablation',{}, {'incremental_test':True})
        child('固定样本外','holdout',{'split':design['plan']['split']})
        child('滚动验证','walkforward',{'schedule':design['plan']['schedule']})
        child('预设参数敏感性（各阶段）','sweep',{'grid':asdict(grid),'split':design['plan']['split'],'schedule':None})
        tree={'children':children}
    elif kind=='ablation':
        if not isinstance(factor,CombinationFactor):raise ValueError('Ablation plan needs a combination')
        aliases=list(variants(factor,cfg['parameters']))
        tree={'children':[{'removed':alias,'_metrics':'standard'} for alias in [None,*aliases]]}
        if cfg.get('incremental_test'):
            tree['contrasts']=[{'name':alias,'_metrics':'paired'} for alias in aliases]
    elif kind=='holdout':
        # Holdout rewrites PipelineConfig fit boundaries; require the effective stored config.
        processor=cfg.get('processor')
        if processor and 'steps' in processor and (processor.get('fit_start')!=cfg['data']['start'] or processor.get('fit_end')!=design['split']['train_end']):
            raise ValueError('Register holdout pipeline with its effective fit_start/fit_end')
        tree={'periods':periods(design['split'],request())}
    elif kind=='walkforward':
        tree={'folds':folds(design['schedule'],request())}
    else:
        if design['split'] is not None and design['schedule'] is not None:
            raise ValueError('Choose split or schedule for sweep')
        parameters=ParameterGrid(**design['grid']).variants(factor,cfg['parameters'])
        if design['split'] is not None:
            phases=[p['name'] for p in periods(design['split'],request())]
        elif design['schedule'] is not None:
            phases=[f"fold_{f['fold']}:{p['name']}" for f in folds(design['schedule'],request()) for p in f['periods']]
        else:phases=['all']
        tree={'children':[{'parameters':p,'evaluations':[{'phase':phase,'_metrics':'standard'} for phase in phases]} for p in parameters]}
    return json.loads(encode(tree))


def hypotheses(trial):
    layout=trial.get('layout',{'_metrics':'standard'})
    result=[]
    def visit(node,path):
        if '_metrics' in node:
            suffix='_difference' if node['_metrics']=='paired' else ''
            for h in trial['config']['horizons']:
                for metric in ('daily_mean_ic','daily_mean_rank_ic'):
                    result.append({'path':path,'horizon':h,'metric':metric+suffix})
        for key in COLLECTIONS:
            for i,child in enumerate(node.get(key,[])):visit(child,f'{path}/{key}/{i}')
    visit(layout,'study')
    return result


def extract_parent(record,trial,validate_raw):
    if record.get('kind')!=trial['study']['kind']:
        raise ValueError('Parent kind differs from registered design')
    if any(record['manifest'].get(k)!=v for k,v in trial['study']['design'].items()):
        raise ValueError('Parent split/schedule/grid differs from registered design')
    partial=record['status']=='failed';rows=[]
    def visit(actual,planned,path):
        if actual is not None:
            for key,value in planned.items():
                if key not in COLLECTIONS and key!='_metrics' and actual.get(key)!=value:
                    raise ValueError(f'Parent node identity differs at {path}/{key}')
            for key in COLLECTIONS:
                if actual.get(key) and key not in planned:
                    raise ValueError(f'Unplanned descendant at {path}/{key}')
            if actual.get('metrics') and '_metrics' not in planned:
                raise ValueError(f'Unplanned metrics at {path}')
        if '_metrics' in planned:
            metrics=(actual or {}).get('metrics')
            if metrics is None and not partial:raise ValueError(f'Missing planned metrics at {path}')
            suffix='_difference' if planned['_metrics']=='paired' else ''
            expected={'daily_mean_ic'+suffix,'daily_mean_rank_ic'+suffix}
            if metrics is not None and set(metrics)!={str(h) for h in trial['config']['horizons']}:
                raise ValueError('Parent horizon set differs from plan')
            for h in trial['config']['horizons']:
                source=metrics[str(h)].get('permutation',{}) if metrics is not None else None
                if source is not None and set(source)!=expected:raise ValueError('Parent must contain every planned raw test')
                for metric in ('daily_mean_ic'+suffix,'daily_mean_rank_ic'+suffix):
                    raw=source[metric] if source is not None else {}
                    if source is not None:validate_raw(raw,trial)
                    rows.append({'trial_id':trial['trial_id'],'path':path,'horizon':h,'metric':metric,
                        'p_value':raw.get('p_value'),'status':raw.get('status','failed'),
                        'reason':raw.get('reason',record.get('error')),'raw_test':raw})
        for key in COLLECTIONS:
            expected=planned.get(key,[]);children=(actual or {}).get(key,[])
            if not isinstance(children,list) or len(children)>len(expected) or (not partial and len(children)!=len(expected)):
                raise ValueError(f'Parent descendant count differs at {path}/{key}')
            matched={}
            for actual_child in children:
                matches=[i for i,child in enumerate(expected) if all(actual_child.get(k)==v
                    for k,v in child.items() if k not in COLLECTIONS and k!='_metrics')]
                if len(matches)!=1 or matches[0] in matched:
                    raise ValueError(f'Duplicate or unplanned parent child identity at {path}/{key}')
                matched[matches[0]]=actual_child
            for i,child in enumerate(expected):visit(matched.get(i),child,f'{path}/{key}/{i}')
    visit(record,trial['layout'],'study')
    return rows


def descendant_run_ids(record):
    ids=set()
    def visit(node):
        if node.get('run_id'):ids.add(node['run_id'])
        for key in COLLECTIONS:
            for child in node.get(key,[]):visit(child)
    visit(record)
    return ids
