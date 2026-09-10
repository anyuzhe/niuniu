"""Reproduce saved cross-experiment comparisons without changing their plans."""
from datetime import date
from pathlib import Path
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.storage.codec import encode
from quantlab.storage.experiments import load_record_fields
from quantlab.storage.reproduction import _graph

KINDS=('residual_alpha','return_increment','stability','return_family')


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
