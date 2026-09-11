"""Rebuild completed campaigns from frozen artifacts, never from the data lake."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import tempfile
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import load_record_fields, LocalExperimentStore
from quantlab.storage.artifact_integrity import snapshot_tree, verify_tree
from quantlab.storage.reproduction import _graph, _references
from quantlab.storage.frozen_inputs import load_frozen_inputs
from quantlab.progress import checkpoint


def compare_graph(left, right):
    from quantlab.storage.bundle import _compare_reproduction
    source = _graph(left); actual = _graph(right); mapping = {}
    def pair(old, new):
        if old in mapping:
            if mapping[old] != new: raise ValueError('Campaign lineage sharing differs')
            return
        if new in mapping.values(): raise ValueError('Campaign descendants collapsed')
        mapping[old] = new
        a = list(_references(source[old])); b = list(_references(actual[new]))
        if len(a) != len(b): raise ValueError('Campaign descendant count differs')
        for x, y in zip(a, b): pair(x, y)
    pair(left.name, right.name)
    if len(mapping) != len(source) or len(mapping) != len(actual):
        raise ValueError('Campaign graph differs')
    def normalized(value, old):
        if isinstance(value, dict):
            return {k: normalized(v, old) for k, v in value.items() if k != 'artifact_path'}
        if isinstance(value, list): return [normalized(v, old) for v in value]
        return mapping.get(value, value) if old and isinstance(value, str) else value
    files = 0
    for old, new in mapping.items():
        checkpoint('研究包复算后代核对 · ' + old)
        _compare_reproduction(normalized(source[old], True), normalized(actual[new], False), old)
        a = left.parent/old; b = right.parent/new
        names = {p.relative_to(a).as_posix() for p in a.rglob('*.parquet')}
        if names != {p.relative_to(b).as_posix() for p in b.rglob('*.parquet')}:
            raise ValueError('Campaign data file set differs')
        for name in sorted(names):
            assert_frame_equal(pl.read_parquet(a/name), pl.read_parquet(b/name),
                check_exact=False, rel_tol=1e-9, abs_tol=1e-12)
            files += 1
        extra = {'execution','fills','rejections','backend_comparison','targets_hash'}
        _compare_reproduction(load_record_fields(a/'experiment.json', extra),
            load_record_fields(b/'experiment.json', extra), 'execution/' + old)
    return mapping, files


def reproduce_campaign(artifact, output):
    from quantlab.storage.bundle import reproduce_artifact, _compare_reproduction
    from quantlab.experiments.runner import runtime_fingerprint
    from quantlab.agent.campaign_plan import prepare_campaign
    from quantlab.experiments.campaign import result_receipt, summarize
    from quantlab.experiments.trial_registry import _load_registry, bind_result, report_registry
    path = Path(artifact).absolute(); output = Path(output).resolve()
    source_tree = snapshot_tree(path.parent, path.name)
    record = load_record_fields(path/'experiment.json', {'run_id','experiment_id','status',
        'kind','manifest','summary','children','registry_plan','registry_snapshot','limitations'})
    if record.get('kind') != 'campaign' or record['status'] != 'completed':
        raise ValueError('Requires a completed campaign; resume unfinished jobs first')
    manifest = record['manifest']; runtime = runtime_fingerprint()
    if manifest['runtime'] != runtime:
        raise ValueError('Campaign runtime differs; use its frozen source/environment')
    preview = prepare_campaign(manifest['plan']); old_nodes = record['summary']['nodes']
    if [n['node_id'] for n in old_nodes] != preview['order']:
        raise ValueError('Campaign node layout differs')
    if any(n['status'] != 'completed' for n in old_nodes):
        raise ValueError('Cannot numerically replay failed/skipped nodes; their original evidence is retained')
    outcomes = [{'node_id':n['node_id'],'status':n['status'],
        'experiment_id':n.get('experiment_id')} for n in old_nodes]
    if manifest['node_outcomes'] != outcomes: raise ValueError('Campaign outcomes differ')
    registry = record.get('registry_snapshot')
    if not registry or registry.get('registry_id') != digest({k:v for k,v in registry.items() if k != 'registry_id'}):
        raise ValueError('Missing or changed registration snapshot')
    if registry['plan'] != record['registry_plan'] or registry['plan'] != preview['registry_plan']:
        raise ValueError('Campaign registration differs')
    if [(c['name'],c['run_id']) for c in record['children']] != [(n['node_id'],n['run_id']) for n in old_nodes]:
        raise ValueError('Campaign child references differ')
    for node in old_nodes:
        tree = node.get('artifact_tree')
        if not tree or tree.get('root_run_id') != node['run_id']:
            raise ValueError('Missing matching node tree receipt')
        verify_tree(path.parent, tree)
        for run_id, child in _graph(path.parent/node['run_id']).items():
            if output.is_relative_to((path.parent/run_id).resolve()):
                raise ValueError('Reproduction output cannot be inside an input archive')
            if child['manifest'].get('runtime') != runtime:
                raise ValueError('Child runtime differs')
            if 'frozen_inputs' in child['manifest']:
                load_frozen_inputs(path.parent/run_id, child['manifest'])
    if output.is_relative_to(path.resolve()): raise ValueError('Output overlaps campaign source')
    output.mkdir(parents=True, exist_ok=True)
    state = {'nodes':{},'job_id':str(uuid4())}; mapping = {}; checked_files = 0
    verification = {'status':'not_verified','source_run_id':path.name,
        'scope':'Frozen completed nodes and descendants; no external lake or new registration. '
        'Every Parquet column plus graph identities and fixed-family tests compared, rtol=1e-9/atol=1e-12.'}
    audit = output/('campaign-reproduction-' + str(uuid4()) + '.json')
    try:
        with tempfile.TemporaryDirectory(prefix='.campaign-reproduce-', dir=output) as tmp:
            family = Path(tmp)/'family'; family.mkdir(); (family/'results').mkdir()
            (family/'registry.json').write_text(encode(registry)); _load_registry(family)
            registered = {t['trial_id'] for t in registry['plan']['trials']}
            for node in old_nodes:
                checkpoint('复算固定研究包节点 · ' + node['node_id'])
                result = reproduce_artifact(path.parent/node['run_id'], output)
                if result['status'] != 'numerically_matched':
                    raise ValueError('Node reproduction was not verified')
                target = output/result['run_id']
                aliases, count = compare_graph(path.parent/node['run_id'], target)
                if set(mapping) & set(aliases) or set(mapping.values()) & set(aliases.values()):
                    raise ValueError('Shared nodes across campaign roots require explicit replay support')
                mapping.update(aliases); checked_files += count
                identity = load_record_fields(target/'experiment.json', {'experiment_id','run_id'})
                state['nodes'][node['node_id']] = result_receipt(output, SimpleNamespace(**identity))
                if node['node_id'] in registered: bind_result(family, node['node_id'], target)
            report = report_registry(family, Path(tmp)/'report')
            for key in ('registry_id','method','alpha','planned_tests','available_tests','tests'):
                _compare_reproduction(record['summary']['family'][key], report[key], 'family/' + key)
            summary = summarize(preview, state, report)
            for key in ('workflow_status','counts','planned_tests'):
                _compare_reproduction(record['summary'][key], summary[key], key)
            verify_tree(path.parent, source_tree)
            new_id = str(uuid4()); mapping[path.name] = new_id
            rebuilt = {'run_id':new_id,'experiment_id':record['experiment_id'],
                'created_at':datetime.now(timezone.utc).isoformat(),'kind':'campaign',
                'status':'completed','manifest':deepcopy(manifest),'summary':summary,
                'registry_plan':registry['plan'],'registry_snapshot':registry,
                'campaign_job_id':state['job_id'],'reproduction_of':path.name,
                'children':[{'name':n['node_id'],'run_id':mapping[n['run_id']],
                    'artifact_path':str(output/mapping[n['run_id']])} for n in old_nodes],
                'limitations':summary['limitations']}
            target = LocalExperimentStore(output).save(new_id, rebuilt, None)
            verification.update(status='numerically_matched',run_id=new_id,
                artifact_path=str(target),run_mapping=mapping,
                checked_runs=len(mapping),checked_parquet_files=checked_files,
                registry_id=registry['registry_id'],planned_tests=report['planned_tests'])
            (target/'reproduction.json').write_text(encode(verification))
    except Exception as error:
        verification.update(status='mismatch_or_interrupted',error=str(error)[:500],
            checked_runs=len(mapping),checked_parquet_files=checked_files)
        raise
    finally:
        with audit.open('x', encoding='utf-8') as stream: stream.write(encode(verification))
    return verification
