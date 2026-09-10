"""Archive a fixed registry snapshot and verify its available research results."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import LocalExperimentStore
from quantlab.experiments.trial_registry import report_registry, _validate_binding, _extract, _validate_plan


def _report(registry, bindings):
    # Use the existing registry validator/layout/Holm implementation without
    # contacting historical source paths or creating a new registration.
    _validate_plan(registry['plan'])
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);(root/'results').mkdir()
        (root/'registry.json').write_text(encode(registry))
        for trial in registry['plan']['trials']:
            key=trial['trial_id']
            if key in bindings:(root/'results'/f'{key}.json').write_text(encode(bindings[key]))
        if set(bindings)-{t['trial_id'] for t in registry['plan']['trials']}:raise ValueError('Unknown registry binding')
        return report_registry(root,root/'report')


def _check_report(expected, actual):
    from quantlab.storage.bundle import _compare_reproduction
    _compare_reproduction({k:v for k,v in expected.items() if k!='created_at'},
                          {k:v for k,v in actual.items() if k!='created_at'},'registry/report')


def _save(registry, bindings, report, children, output, status="completed"):
    from quantlab.experiments.runner import runtime_fingerprint
    run_id=str(uuid4());manifest={'config':{'research_question':registry['plan']['name']},
        'runtime':runtime_fingerprint(),'registry':registry,'bindings':bindings,'report_hash':digest(report)}
    record={'run_id':run_id,'experiment_id':digest(manifest),'created_at':datetime.now(timezone.utc).isoformat(),
        'kind':'trial_registry','status':status,'manifest':manifest,'summary':report,'children':children}
    target=LocalExperimentStore(output).save(run_id,record,None)
    return {'run_id':run_id,'artifact_path':str(target)}


def archive_registry(snapshot, output):
    """Archive an existing report without altering registration or binding times."""
    from quantlab.storage.reproduction import _graph
    root=Path(snapshot);output=Path(output).resolve()
    registry=json.loads((root/'registry.json').read_text());bindings=json.loads((root/'bindings.json').read_text())
    report=json.loads((root/'report.json').read_text());_check_report(report,_report(registry,bindings))
    children=[];sources={}
    for trial in registry['plan']['trials']:
        key=trial['trial_id'];binding=bindings.get(key)
        if binding is None or binding['record']['status']!='completed':continue
        source=Path(binding['source_path'])
        if hashlib.sha256(source.read_bytes()).hexdigest()!=binding['source_sha256']:raise ValueError('Bound source checksum differs: '+key)
        if json.loads(source.read_text())!=binding['record']:raise ValueError('Bound source record differs: '+key)
        graph=_graph(source.parent)
        for run_id in graph:
            folder=source.parent.parent/run_id
            if run_id in sources and sources[run_id]!=folder:raise ValueError('Ambiguous source run directory')
            sources[run_id]=folder
        children.append({'name':key,'run_id':source.parent.name,'artifact_path':str(output/source.parent.name)})
    # Validate destination collisions before copying any source. Never replace an archive.
    for run_id,folder in sources.items():
        target=output/run_id
        if target==folder:continue
        if any(p.is_symlink() or not p.is_file() for p in folder.iterdir()):raise ValueError('Unexpected archive entry')
        if target.exists():
            if {p.name for p in target.iterdir()}!={p.name for p in folder.iterdir()} or any(p.is_symlink() or not p.is_file() or p.read_bytes()!=(folder/p.name).read_bytes() for p in target.iterdir()):raise ValueError('Destination archive differs: '+run_id)
    output.mkdir(parents=True,exist_ok=True)
    for run_id,folder in sources.items():
        target=output/run_id
        if not target.exists():shutil.copytree(folder,target)
    return _save(registry,bindings,report,children,output)


def reproduce_registry(artifact, output):
    from quantlab.storage.reproduction import _graph
    from quantlab.storage.bundle import reproduce_artifact, _compare_reproduction
    from quantlab.experiments.runner import runtime_fingerprint
    path=Path(artifact);graph=_graph(path);record=graph[path.name];manifest=record['manifest']
    if record['kind']!='trial_registry':raise ValueError('Expected registry archive')
    if any(r['manifest'].get('runtime')!=runtime_fingerprint() for r in graph.values()):raise ValueError('Source/interpreter/dependency fingerprint differs; use matching source and environment')
    registry=manifest['registry'];bindings=manifest['bindings'];original=record['summary']
    if digest(original)!=manifest['report_hash']:raise ValueError('Registry report hash mismatch')
    _check_report(original,_report(registry,bindings))
    refs={c['name']:c for c in record['children']}
    expected={k for k,b in bindings.items() if b['record']['status']=='completed'}
    if len(refs)!=len(record['children']) or set(refs)!=expected:raise ValueError('Registry lineage differs from successful bindings')
    # Verify each local source is the bound experiment before creating new runs.
    for key,child in refs.items():
        source=graph[child['run_id']];bound=bindings[key]['record']
        if source['experiment_id']!=bound['experiment_id']:raise ValueError('Bound experiment identity differs: '+key)
    raw_results={};children=[];mapping={};preserved=sum(t['status']!='completed' for t in original['trials'])
    verification={'source_run_id':path.name,'status':'not_verified','preserved_trials':preserved,
        'scope':'Recomputed completed bound studies and checked their raw tests against the original registry; Holm includes all original slots. Failed/partial/unrun trials remain original evidence, not newly verified results. Registration/binding times are unchanged provenance.'}
    try:
        for trial in registry['plan']['trials']:
            key=trial['trial_id']
            if key not in refs:continue
            old=refs[key]['run_id'];new=reproduce_artifact(path.parent/old,output)
            if new['status']!='numerically_matched':raise ValueError('Bound study did not reproduce')
            actual=json.loads((Path(new['artifact_path'])/'experiment.json').read_text())
            raw_results[key]=_extract(actual,trial)
            _compare_reproduction(_validate_binding(bindings[key],trial),raw_results[key],'registry/raw/'+key)
            mapping.update(new.get('run_mapping',{old:new['run_id']}))
            children.append({'name':key,'run_id':new['run_id'],'artifact_path':new['artifact_path']})
        from quantlab.statistics.permutation import holm
        slots=[]
        for trial in registry['plan']['trials']:
            key=trial['trial_id']
            slots.extend(raw_results.get(key,[t for t in original['tests'] if t['trial_id']==key]))
        adjusted=holm([t['p_value'] for t in slots])
        _compare_reproduction([t['p_holm'] for t in original['tests']],adjusted,'registry/Holm')
        _compare_reproduction([t['reject_holm'] for t in original['tests']],
            [p<=registry['plan']['alpha'] if p is not None else None for p in adjusted],'registry/reject')
        verification.update(status='available_results_matched' if preserved else 'numerically_matched',
            recomputed_trials=len(children),planned_tests=original['planned_tests'],run_mapping=mapping)
    except Exception as error:
        failed=_save(registry,bindings,original,children,output,status='failed')
        target=Path(failed['artifact_path']);verification.update(failed,status='mismatch',error=str(error))
        (target/'reproduction.json').write_text(encode(verification))
        raise ValueError(f'复算不一致：{error}；核对记录：{target}/reproduction.json') from error
    completed=_save(registry,bindings,original,children,output)
    verification.update(completed);verification['run_mapping'][path.name]=completed['run_id']
    (Path(completed['artifact_path'])/'reproduction.json').write_text(encode(verification))
    return verification
