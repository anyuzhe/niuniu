"""Reproduce saved cross-experiment comparisons without changing their plans."""
from datetime import date
from pathlib import Path
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.storage.codec import encode
from quantlab.storage.experiments import load_record_fields
from quantlab.storage.reproduction import _graph

KINDS=('residual_alpha','return_increment','stability','return_family','incremental_evidence','alpha_factory')


def reproduce_derived(artifact, output, *, _source_cache=None):
    from quantlab.storage.bundle import reproduce_artifact,_compare_reproduction
    from quantlab.experiments.runner import runtime_fingerprint
    from quantlab.experiments.residual import run_residual
    from quantlab.experiments.return_increment import compare_returns
    from quantlab.experiments.stability import run_stability
    path=Path(artifact);graph=_graph(path);record=graph[path.name];manifest=record['manifest'];kind=record['kind']
    if kind not in KINDS:raise ValueError('Unsupported derived experiment')
    if any(r['manifest'].get('runtime')!=runtime_fingerprint() for r in graph.values()):raise ValueError('Source/interpreter/dependency fingerprint differs; use matching source and environment')
    children=record['children'];ids=[c['run_id'] for c in children]
    if kind=='residual_alpha' and len(ids)<2 or kind=='return_increment' and len(ids)!=2:raise ValueError('Invalid comparison source count')
    if kind=='stability' and len(ids)!=2*len(manifest['plan']['comparisons']):raise ValueError('Invalid stability source count')
    if kind=='return_family':return reproduce_return_family(path,output,graph)
    if kind=='incremental_evidence':return reproduce_incremental_evidence(path,output,graph)
    if kind=='alpha_factory':return reproduce_alpha_factory(path,output,graph)
    if 'source_experiments' in manifest and [graph[i]['experiment_id'] for i in ids]!=manifest['source_experiments']:raise ValueError('Derived source identity mismatch')
    # Dependencies must contain their frozen inputs; never fall back to the old absolute paths.
    from quantlab.storage.frozen_inputs import load_frozen_inputs
    for run_id,r in graph.items():
        if 'frozen_inputs' in r['manifest']:load_frozen_inputs(path.parent/run_id,r['manifest'])
    mapped={};new_paths={}
    cache={} if _source_cache is None else _source_cache
    for run_id in dict.fromkeys(ids):
        if run_id not in cache:cache[run_id]=reproduce_artifact(path.parent/run_id,output)
        result=cache[run_id]
        if result['status']!='numerically_matched':raise ValueError('Source reproduction did not match')
        new_paths[run_id]=Path(result['artifact_path'])
        mapped.update(result.get('run_mapping',{run_id:result['run_id']}))
    paths=[new_paths[i] for i in ids]
    if kind=='residual_alpha':actual=run_residual(paths[0],paths[1:],date.fromisoformat(manifest['train_end']),output,manifest['horizon'])
    elif kind=='return_increment':actual=compare_returns(paths[0],paths[1],date.fromisoformat(manifest['evaluation_start']),output)
    else:
        # Preserve the original plan strings, which are part of the existing random seed.
        source_paths={}
        for i,item in enumerate(manifest['plan']['comparisons']):
            for offset,key in enumerate(('candidate','baseline')):
                original=str(Path(item[key]));target=paths[2*i+offset]
                if original in source_paths and source_paths[original]!=target:raise ValueError('Ambiguous stability path mapping')
                source_paths[original]=target
        actual=run_stability(manifest['plan'],output,source_paths=source_paths)
    target=Path(actual['artifact_path']);mapped[path.name]=actual['run_id']
    verification={'source_run_id':path.name,'run_id':actual['run_id'],'artifact_path':str(target),'status':'not_verified','run_mapping':mapped,
        'scope':'Recomputed source experiments, then derived statistics with the unchanged evaluation plan and random seeds; no original absolute source path access.'}
    try:
        new=load_record_fields(target/'experiment.json',{'manifest','summary','experiment_id'})
        for key in ('manifest','summary','experiment_id'):_compare_reproduction(record[key],new[key],kind+'/'+key)
        assert_frame_equal(pl.read_parquet(path/'observations.parquet'),pl.read_parquet(target/'observations.parquet'),check_exact=False,rel_tol=1e-9,abs_tol=1e-12)
        verification['status']='numerically_matched'
    except Exception as error:
        verification.update(status='mismatch',error=str(error))
        raise ValueError(f'复算不一致：{error}；核对记录：{target}/reproduction.json') from error
    finally:(target/'reproduction.json').write_text(encode(verification))
    return verification


def reproduce_return_family(path, output, graph):
    from datetime import datetime,timezone
    from uuid import uuid4
    from copy import deepcopy
    from quantlab.storage.codec import digest
    from quantlab.storage.experiments import LocalExperimentStore
    from quantlab.storage.bundle import reproduce_artifact,_compare_reproduction
    from quantlab.statistics.permutation import holm
    record=graph[path.name];manifest=record['manifest'];registry=manifest['registry'];original=record['summary']
    if digest({k:v for k,v in registry.items() if k!='registry_id'})!=registry['registry_id']:raise ValueError('Frozen family registry identity mismatch')
    if digest(original)!=manifest['report_hash']:raise ValueError('Frozen family report hash mismatch')
    plan=registry['plan'];tests=original['tests']
    if original['registry_id']!=registry['registry_id'] or original['planned_tests']!=len(plan['comparisons']) or [t['id'] for t in tests]!=[t['id'] for t in plan['comparisons']]:raise ValueError('Family plan/report slots differ')
    references={c['name']:c['run_id'] for c in record['children']}
    if references!={t['id']:t['run_id'] for t in tests if 'run_id' in t}:raise ValueError('Family comparison lineage differs')
    results=[];children=[];mapping={};report=deepcopy(original);source_cache={}
    for t in report['tests']:
        if 'run_id' not in t:
            if t['status']!='failed' or t.get('p_value') is not None:raise ValueError('Unbacked family result')
            results.append(None);continue
        old=t['run_id'];result=reproduce_derived(path.parent/old,output,_source_cache=source_cache)
        actual=load_record_fields(Path(result['artifact_path'])/'experiment.json',{'summary'})['summary']['permutation']
        _compare_reproduction(t['raw_test'],actual,'family/'+t['id'])
        if actual['status']!=t['status'] or actual.get('p_value')!=t['p_value']:raise ValueError('Family raw result differs')
        results.append(actual.get('p_value'));mapping.update(result.get('run_mapping',{}));mapping[old]=result['run_id']
        t.update(run_id=result['run_id'],artifact_path=result['artifact_path'])
        children.append({'run_id':result['run_id'],'artifact_path':result['artifact_path'],'name':t['id']})
    for old,t,p in zip(tests,report['tests'],holm(results)):
        reject=p<=plan['alpha'] if p is not None else None
        _compare_reproduction({'p_holm':old['p_holm'],'reject':old['reject']},{'p_holm':p,'reject':reject},'family/Holm/'+t['id'])
        t.update(p_holm=p,reject=reject)
    run_id=str(uuid4());new_manifest={**manifest,'report_hash':digest(report)}
    new={'run_id':run_id,'experiment_id':digest(new_manifest),'created_at':datetime.now(timezone.utc).isoformat(),'kind':'return_family','status':'completed','manifest':new_manifest,'summary':report,'children':children}
    target=LocalExperimentStore(output).save(run_id,new,None)
    failed=sum(t['status']=='failed' for t in tests)
    verification={'run_id':run_id,'source_run_id':path.name,'artifact_path':str(target),'run_mapping':{**mapping,path.name:run_id},
        'status':'available_results_matched' if failed else 'numerically_matched','planned_tests':len(tests),'recomputed_tests':len(children),'preserved_failed_slots':failed,
        'scope':'Recomputed available comparisons and Holm over every original planned slot; failed slots remain unknown. Original registration time and source hashes are provenance, not a new prospective registration.'}
    (target/'reproduction.json').write_text(encode(verification))
    return verification


def reproduce_incremental_evidence(path,output,graph):
    from datetime import datetime,timezone
    from uuid import uuid4
    from copy import deepcopy
    from quantlab.storage.codec import digest
    from quantlab.storage.experiments import LocalExperimentStore,load_record_fields
    from quantlab.storage.bundle import _compare_reproduction
    from quantlab.statistics.permutation import holm
    record=graph[path.name];original=record['summary'];tests=original['tests']
    children={c['name']:c['run_id'] for c in record['children']};new_children=[];mapping={};pvalues=[]
    report=deepcopy(original)
    for old,new in zip(tests,report['tests']):
        if old['status']=='failed':
            if old.get('run_id') or old.get('p_value') is not None:raise ValueError('失败槽位不能带研究结果')
            pvalues.append(None);continue
        run_id=children.get(old['id'])
        if run_id!=old.get('run_id'):raise ValueError('增量证据子研究映射不一致')
        result=reproduce_derived(path.parent/run_id,output)
        child=load_record_fields(Path(result['artifact_path'])/'experiment.json',{'kind','summary'})
        raw=child['summary']['test'] if child['kind']=='residual_alpha' else child['summary']['permutation']
        if raw.get('p_value')!=old.get('p_value') or raw.get('status')!=old.get('test_status'):
            raise ValueError('增量证据原始检验结果不一致')
        new.update(run_id=result['run_id'],artifact_path=result['artifact_path'],reused=False)
        pvalues.append(raw.get('p_value'));mapping.update(result.get('run_mapping',{}))
        new_children.append({'run_id':result['run_id'],'artifact_path':result['artifact_path'],'name':old['id']})
    adjusted=holm(pvalues);alpha=record['manifest']['plan']['alpha']
    for old,new,p in zip(tests,report['tests'],adjusted):
        reject=p<=alpha if p is not None else None
        _compare_reproduction({'p_holm':old.get('p_holm'),'reject':old.get('reject')},
            {'p_holm':p,'reject':reject},'incremental/Holm/'+old['id'])
        new.update(p_holm=p,reject=reject)
    def semantic(value):
        value=deepcopy(value)
        for row in value['tests']:
            for key in ('run_id','artifact_path','reused'):row.pop(key,None)
        return value
    _compare_reproduction(semantic(original),semantic(report),'incremental/summary')
    run_id=str(uuid4());manifest=record['manifest']
    new_record={'run_id':run_id,'experiment_id':digest(manifest),'created_at':datetime.now(timezone.utc).isoformat(),
        'status':'completed','kind':'incremental_evidence','manifest':manifest,'summary':report,'children':new_children}
    target=LocalExperimentStore(output).save(run_id,new_record,None);mapping[path.name]=run_id
    failed=sum(t['status']=='failed' for t in tests)
    verification={'source_run_id':path.name,'run_id':run_id,'artifact_path':str(target),
        'run_mapping':mapping,'planned_tests':len(tests),'recomputed_tests':len(new_children),
        'preserved_failed_slots':failed,'status':'available_results_matched' if failed else 'numerically_matched',
        'scope':'Recomputed every available fixed incremental-evidence slot and Holm over the original full family; failed slots remain unknown.'}
    (target/'reproduction.json').write_text(encode(verification));return verification


def reproduce_alpha_factory(path,output,graph):
    from copy import deepcopy
    from datetime import date,datetime,timezone
    from uuid import uuid4
    from quantlab.agent.alpha_factory import factory_decisions
    from quantlab.agent.candidate_review import compare_candidate
    from quantlab.experiments.residual import run_residual
    from quantlab.experiments.return_increment import compare_returns
    from quantlab.statistics.permutation import holm
    from quantlab.storage.bundle import reproduce_artifact,_compare_reproduction
    from quantlab.storage.codec import digest
    from quantlab.storage.experiments import LocalExperimentStore,load_record_fields

    record=graph[path.name];manifest=record['manifest'];original=record['summary'];plan=manifest['plan']
    if original['planned_tests']!=len(original['tests']) or original['planned_candidates']!=len(plan['candidate_ids']):
        raise ValueError('Factory父归档计划数量不一致')
    primary=[plan['baseline_run_id'],*plan['control_run_ids']]
    if plan['require_net_return']:primary.append(plan['baseline_execution_run_id'])
    for entry in original.get('runs',{}).values():
        primary.extend(v for k,v in entry.items() if k.endswith('_run_id') and v)
    mapping={};new_paths={};source_cache={}
    for run_id in dict.fromkeys(primary):
        result=reproduce_artifact(path.parent/run_id,output)
        if result['status'] not in ('numerically_matched','available_results_matched'):
            raise ValueError('Factory来源复算未匹配：'+run_id)
        new_paths[run_id]=Path(result['artifact_path']);mapping.update(result.get('run_mapping',{}));mapping[run_id]=result['run_id']
    tests=[];reviews={};new_runs={};new_children=[]
    for cid in plan['candidate_ids']:
        old_runs=original['runs'].get(cid,{})
        factor_old=old_runs.get('factor_run_id');execution_old=old_runs.get('execution_run_id')
        new_runs[cid]={'factor_job_id':old_runs.get('factor_job_id'),'factor_run_id':mapping.get(factor_old)}
        if execution_old:new_runs[cid].update(execution_job_id=old_runs.get('execution_job_id'),execution_run_id=mapping.get(execution_old))
        old_candidate_tests=[t for t in original['tests'] if t['candidate_id']==cid]
        if not factor_old:
            tests.extend(deepcopy(old_candidate_tests));reviews[cid]=deepcopy(original.get('candidate_reviews',{}).get(cid,{}));continue
        candidate_new=mapping[factor_old];baseline_new=mapping[plan['baseline_run_id']]
        reviews[cid]=compare_candidate(output,candidate_new,baseline_new,plan['horizon'])
        old_residual=next(t for t in old_candidate_tests if t['id']=='residual_ic')
        if old_residual['status']=='failed':tests.append(deepcopy(old_residual))
        else:
            result=run_residual(new_paths[factor_old],[new_paths[v] for v in plan['control_run_ids']],
                date.fromisoformat(plan['train_end']),output,plan['horizon'])
            raw=result['summary']['test'];tests.append({'candidate_id':cid,'id':'residual_ic','kind':'residual_alpha',
                'status':'completed','run_id':result['run_id'],'artifact_path':result['artifact_path'],
                'p_value':raw.get('p_value'),'estimate':raw.get('estimate'),'test_status':raw.get('status'),'reused':False})
            new_children.append({'run_id':result['run_id'],'artifact_path':result['artifact_path'],'name':'residual_ic '+cid[:8]})
            mapping[old_residual['run_id']]=result['run_id']
        if plan['require_net_return']:
            old_net=next(t for t in old_candidate_tests if t['id']=='net_return_increment')
            if old_net['status']=='failed':tests.append(deepcopy(old_net))
            else:
                result=compare_returns(new_paths[execution_old],new_paths[plan['baseline_execution_run_id']],
                    date.fromisoformat(plan['evaluation_start']),output)
                raw=result['summary']['permutation'];tests.append({'candidate_id':cid,'id':'net_return_increment','kind':'return_increment',
                    'status':'completed','run_id':result['run_id'],'artifact_path':result['artifact_path'],
                    'p_value':raw.get('p_value'),'estimate':result['summary'].get('mean_daily_difference'),
                    'test_status':raw.get('status'),'reused':False})
                new_children.append({'run_id':result['run_id'],'artifact_path':result['artifact_path'],'name':'net_return_increment '+cid[:8]})
                mapping[old_net['run_id']]=result['run_id']
    adjusted=holm([t.get('p_value') for t in tests])
    for row,p in zip(tests,adjusted):
        row['p_holm']=p;row['reject']=p<=plan['alpha'] if p is not None else None
    names={d['candidate_id']:d['name'] for d in original['decisions']}
    prepared={'plan':plan,'candidates':[{'candidate_id':cid,'name':names[cid]} for cid in plan['candidate_ids']]}
    decisions=factory_decisions(prepared,tests,reviews)
    report=deepcopy(original);report.update(tests=tests,candidate_reviews=reviews,runs=new_runs,
        decisions=decisions,available_tests=sum(t.get('p_value') is not None for t in tests),
        recommended_candidate_ids=[d['candidate_id'] for d in decisions if d['recommended_for_watchlist']])
    def semantic(value):
        value=deepcopy(value)
        for row in value['tests']:
            for key in ('run_id','artifact_path','reused'):row.pop(key,None)
        for row in value.get('runs',{}).values():
            row.pop('factor_run_id',None);row.pop('execution_run_id',None)
        for review in value.get('candidate_reviews',{}).values():
            review.pop('source_fingerprints',None)
            for key in ('candidate','baseline'):
                if isinstance(review.get(key),dict):review[key].pop('run_id',None)
        return value
    _compare_reproduction(semantic(original),semantic(report),'alpha_factory/summary')
    children=[];seen=set()
    for old in dict.fromkeys(primary):
        new=mapping[old]
        if new in seen:continue
        children.append({'run_id':new,'artifact_path':str(new_paths[old]),'name':'复算来源'});seen.add(new)
    children.extend(new_children)
    run_id=str(uuid4());new_record={'run_id':run_id,'experiment_id':digest(manifest),
        'created_at':datetime.now(timezone.utc).isoformat(),'kind':'alpha_factory','status':'completed',
        'manifest':manifest,'summary':report,'children':children}
    target=LocalExperimentStore(output).save(run_id,new_record,None);mapping[path.name]=run_id
    failed=sum(t['status']=='failed' for t in tests)
    verification={'source_run_id':path.name,'run_id':run_id,'artifact_path':str(target),'run_mapping':mapping,
        'planned_candidates':len(plan['candidate_ids']),'planned_tests':len(tests),
        'recomputed_tests':len(tests)-failed,'preserved_failed_slots':failed,
        'status':'available_results_matched' if failed else 'numerically_matched',
        'scope':'Recomputed frozen source studies, candidate reviews, all available Factory tests, Factory-wide Holm and the unchanged watchlist recommendation rule.'}
    (target/'reproduction.json').write_text(encode(verification));return verification
