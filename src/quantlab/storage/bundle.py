"""Portable, checksummed experiment evidence and source bundles.

Restoration preserves original records byte-for-byte. Absolute historical paths
remain provenance; the catalog resolves included run ids locally. A bundle is
not proof of reproducibility when the available source differs from run-time code.
"""
import hashlib
import importlib.metadata
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import UUID
from quantlab.storage.codec import encode


def _hash(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def export_bundle(artifact, destination, source_directory=None):
    artifact=Path(artifact).resolve();destination=Path(destination)
    if destination.exists():raise FileExistsError(destination)
    from quantlab.experiments.runner import runtime_fingerprint
    runtime=runtime_fingerprint();files={};records={};pending=[artifact.name]
    while pending:
        run_id=pending.pop()
        if run_id in records:continue
        if str(UUID(run_id))!=run_id:raise ValueError('Invalid run id')
        root=artifact.parent/run_id
        if root.is_symlink() or not root.is_dir():raise ValueError('Missing local child archive: '+run_id)
        record_path=root/'experiment.json'
        from quantlab.storage.experiments import load_identity
        record=load_identity(record_path);records[run_id]={'manifest':{'runtime':record['manifest'].get('runtime',{})}}
        if record['run_id']!=run_id:raise ValueError('Archive identity mismatch')
        def visit(node):
            if isinstance(node,dict):
                if 'artifact_path' in node and 'run_id' in node:pending.append(node['run_id'])
                for key in ('children','periods','folds','evaluations'):
                    for child in node.get(key,[]):visit(child)
        visit(record)
        for path in root.iterdir():
            if path.is_symlink():raise ValueError('Symlink in archive')
            if path.is_file():files['runs/'+run_id+'/'+path.name]=path
    package=Path(source_directory).resolve() if source_directory else Path(__file__).parents[1]
    def code_hash(directory):
        from quantlab.storage.codec import digest
        return digest({str(p.relative_to(directory)):_hash(p) for p in sorted(directory.rglob('*.py'))})
    if source_directory is None:
        frozen=artifact.parent.parent/'runtime-snapshot/src/quantlab'
        if frozen.is_dir() and code_hash(frozen)==records[artifact.name]['manifest']['runtime'].get('code_hash'):package=frozen
    if not package.is_dir() or not (package/'__init__.py').is_file():raise ValueError('Source directory must be a quantlab package')
    packaged_code_hash=code_hash(package)
    for path in package.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
            if path.is_symlink():raise ValueError('Symlink in source')
            files['source/quantlab/'+path.relative_to(package).as_posix()]=path
    import inspect
    helper=('import json,sys\nfrom pathlib import Path\n\n'+'\n\n'.join(inspect.getsource(fn) for fn in (reproduce_factor,_compare_reproduction,reproduce_execution,reproduce_artifact))+
        '\nif __name__ == "__main__":\n    print(json.dumps(reproduce_artifact(sys.argv[1],sys.argv[2]),ensure_ascii=False))\n').encode()
    extras={'tools/reproduce.py':helper}
    manifest={'version':1,'root_run_id':artifact.name,'runtime_at_export':runtime,
        'packaged_source_code_hash':packaged_code_hash,
        'run_code_matches_export_source':{key:value['manifest'].get('runtime',{}).get('code_hash')==packaged_code_hash for key,value in records.items()},
        'environment':{dist.metadata['Name']:dist.version for dist in importlib.metadata.distributions() if dist.metadata['Name']},
        'files':{**{name:{'bytes':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns,'sha256':_hash(path)} for name,path in files.items()},**{name:{'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()} for name,payload in extras.items()}},
        'scope':'Frozen run artifacts and descendants; matching adjacent frozen source when available, otherwise current/explicit source; installed package versions. Interpreter, wheels, external lake and absent historical metadata are not bundled. False code-match flags forbid claiming exact source reproduction. Run tools/reproduce.py with PYTHONPATH=source in the matching Python/dependency environment for supported factor and execution artifacts.'}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent,suffix='.zip',delete=False) as handle:temp=Path(handle.name)
    try:
        with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            archive.writestr('bundle.json',encode(manifest))
            for name,path in files.items():archive.write(path,name)
            for name,payload in extras.items():archive.writestr(name,payload)
        # Exclusive publication; never overwrite an existing user artifact.
        with destination.open('xb') as target,temp.open('rb') as source:shutil.copyfileobj(source,target)
    finally:temp.unlink(missing_ok=True)
    return {'path':str(destination),'runs':len(records),'files':len(manifest['files']),'bytes':destination.stat().st_size,'source_matches':manifest['run_code_matches_export_source']}


def restore_bundle(bundle, destination):
    destination=Path(destination)
    if destination.exists():raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.restore-',dir=destination.parent))
    try:
        with zipfile.ZipFile(bundle) as archive:
            names=archive.namelist()
            if len(set(names))!=len(names):raise ValueError('Duplicate bundle entry')
            if archive.getinfo('bundle.json').file_size>20_000_000:raise ValueError('Oversized bundle manifest')
            manifest=json.loads(archive.read('bundle.json'))
            if manifest.get('version')!=1 or set(names)!=set(manifest['files'])|{'bundle.json'}:raise ValueError('Bundle manifest/file set mismatch')
            for name,expected in manifest['files'].items():
                parts=PurePosixPath(name)
                if parts.is_absolute() or '..' in parts.parts or '\\' in name or not parts.parts or parts.parts[0] not in ('runs','source','tools'):raise ValueError('Unsafe bundle entry')
                if archive.getinfo(name).file_size!=expected['bytes']:raise ValueError('Bundle size mismatch')
                path=staging/parts;path.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(name) as source,path.open('xb') as target:shutil.copyfileobj(source,target)
                if _hash(path)!=expected['sha256']:raise ValueError('Bundle checksum mismatch: '+name)
            (staging/'bundle.json').write_text(encode(manifest))
        # Rebuild display summaries because extraction changes filesystem mtime.
        from quantlab.storage.experiments import listing_summary, detail_summary, identity_summary,load_record_fields
        for source in (staging/'runs').glob('*/experiment.json'):
            record=None
            original=manifest['files'][source.relative_to(staging).as_posix()]
            for name,make in [('summary.json',listing_summary),('detail.json',detail_summary),('identity.json',identity_summary)]:
                companion=source.parent/name
                if companion.is_file() and 'mtime_ns' in original:
                    saved=json.loads(companion.read_text())
                    if (saved.get('source_size'),saved.get('source_mtime_ns'))==(original['bytes'],original['mtime_ns']):
                        saved.update(source_size=source.stat().st_size,source_mtime_ns=source.stat().st_mtime_ns)
                        companion.write_text(encode(saved));continue
                if name=='identity.json':
                    identity=load_record_fields(source,{'run_id','experiment_id','created_at','status','kind','manifest','children','periods','folds','evaluations'})
                    companion.write_text(encode(identity_summary(identity,source)));continue
                if record is None:record=json.loads(source.read_text())
                (source.parent/name).write_text(encode(make(record,source)))
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging,ignore_errors=True);raise
    return {'path':str(destination),'artifact_root':str(destination/'runs'),'root_run_id':manifest['root_run_id'],'verified_files':len(manifest['files']),
        'source_matches':manifest['run_code_matches_export_source'],'verification':'All exported file checksums verified before regenerating display summaries; no code executed and no claim of numerical rerun.'}


def reproduce_factor(artifact, output):
    """Numerically rerun a self-contained factor artifact, without reading MQC.

    Caller runs the matching bundled source/environment. Unsupported external
    context or historical-universe dependencies are rejected, never substituted.
    """
    from dataclasses import replace
    import math
    import polars as pl
    from polars.testing import assert_frame_equal
    from quantlab.experiments.runner import runtime_fingerprint, ExperimentRunner
    from quantlab.storage.experiments import LocalExperimentStore, load_record
    from quantlab.data.base import DataBatch, DataSnapshot, ExplicitUniverse
    from quantlab.app import default_registry
    from quantlab.workbench.jobs import prepare
    from quantlab.storage.experiments import load_record_fields
    path=Path(artifact);record=load_record_fields(path/'experiment.json',{'manifest','kind','status','metrics','run_id'});manifest=record['manifest'];cfg=manifest['config']
    if 'frozen_inputs' in manifest:
        from quantlab.storage.reproduction import reproduce_research
        return reproduce_research(artifact,output)
    if record.get('kind','factor')!='factor' or record['status']!='completed':raise ValueError('Numerical reproduction requires a completed factor artifact')
    if manifest.get('runtime')!=runtime_fingerprint():raise ValueError('Source/interpreter/dependency fingerprint differs from the original run; use the matching saved environment')
    if manifest.get('universe',{}).get('id')!='explicit_symbols' or cfg.get('context'):raise ValueError('Historical universe or external timeframe inputs require their own frozen metadata/source; no substitution allowed')
    mapping={'research_question':'question','factor_id':'factor','factor_version':'version','random_seed':'seed'}
    spec={mapping.get(k,k):v for k,v in cfg.items() if k not in ('data','theory_origin') and v is not None}
    spec.update(cfg['data']);spec['adjustment']=manifest['data_snapshot']['adjustment'];spec['mode']='single'
    config=replace(prepare(spec).config,theory_origin=cfg.get('theory_origin'))
    bars=pl.read_parquet(path/'bars.parquet');snapshot=DataSnapshot(**{**manifest['data_snapshot'],'files':tuple(manifest['data_snapshot']['files'])})
    class FrozenSource:
        def load(self,request):
            if request!=config.data:raise ValueError('Reproduction requested an unbundled data range')
            return DataBatch(bars,snapshot)
    result=ExperimentRunner(FrozenSource(),default_registry(),ExplicitUniverse(config.data.symbols),LocalExperimentStore(output)).run(config)
    actual=load_record(result.artifact_path/'experiment.json')
    def compare(left,right,location='metrics'):
        if isinstance(left,dict):
            if not isinstance(right,dict) or set(left)!=set(right):raise ValueError('Reproduction keys differ: '+location)
            for k,v in left.items():compare(v,right[k],location+'/'+k)
        elif isinstance(left,list):
            if not isinstance(right,list) or len(left)!=len(right):raise ValueError('Reproduction length differs: '+location)
            for i,(a,b) in enumerate(zip(left,right)):compare(a,b,location+'/'+str(i))
        elif isinstance(left,float):
            if not isinstance(right,(int,float)) or not math.isclose(left,right,rel_tol=1e-9,abs_tol=1e-12):raise ValueError('Reproduction number differs: '+location)
        elif left!=right:raise ValueError('Reproduction value differs: '+location)
    compare(record['metrics'],actual['metrics'])
    assert_frame_equal(pl.read_parquet(path/'observations.parquet'),pl.read_parquet(result.artifact_path/'observations.parquet'),check_exact=False,rel_tol=1e-9,abs_tol=1e-12)
    return {'run_id':result.run_id,'artifact_path':str(result.artifact_path),'source_run_id':record['run_id'],'status':'numerically_matched','scope':'All research metrics and observation columns compared; frozen bars only, no original MQC access; rtol=1e-9, atol=1e-12'}


def _compare_reproduction(left, right, location):
    import math
    if isinstance(left, dict):
        if not isinstance(right, dict) or set(left)!=set(right):raise ValueError('Reproduction keys differ: '+location)
        for key,value in left.items():_compare_reproduction(value,right[key],location+'/'+key)
    elif isinstance(left, list):
        if not isinstance(right,list) or len(left)!=len(right):raise ValueError('Reproduction length differs: '+location)
        for i,(a,b) in enumerate(zip(left,right)):_compare_reproduction(a,b,location+'/'+str(i))
    elif isinstance(left,float):
        if not isinstance(right,(int,float)) or not math.isclose(left,right,rel_tol=1e-9,abs_tol=1e-12):raise ValueError('Reproduction number differs: '+location)
    elif left!=right:raise ValueError('Reproduction value differs: '+location)


def reproduce_execution(artifact, output):
    """Rebuild signals, targets and executions using only the two saved bar sets."""
    from dataclasses import replace
    from uuid import UUID
    import polars as pl
    from polars.testing import assert_frame_equal
    from quantlab.storage.codec import digest, encode
    from quantlab.storage.experiments import LocalExperimentStore, load_record_fields
    from quantlab.experiments.runner import runtime_fingerprint, ExperimentRunner
    from quantlab.experiments.execution import ExecutionStudy
    from quantlab.execution.backtest import ExecutionConfig
    from quantlab.execution.portfolio import PortfolioConfig
    from quantlab.execution.rules import MarketRules
    from quantlab.data.base import DataBatch, DataSnapshot, ExplicitUniverse
    from quantlab.app import default_registry
    from quantlab.workbench.jobs import prepare
    path=Path(artifact)
    fields={'run_id','experiment_id','status','kind','manifest','children','execution','fills','rejections','backend_comparison'}
    record=load_record_fields(path/'experiment.json',fields);manifest=record['manifest']
    if record.get('kind')!='execution' or record['status']!='completed':raise ValueError('Requires a completed execution artifact')
    if manifest.get('runtime')!=runtime_fingerprint():raise ValueError('Source/interpreter/dependency fingerprint differs from the original run; use the matching saved environment')
    if record['run_id']!=path.name or digest(manifest)!=record['experiment_id']:raise ValueError('Execution archive identity mismatch')
    children=record.get('children',[])
    if len(children)!=1:raise ValueError('Execution reproduction requires exactly one local signal child')
    child_id=children[0]['run_id']
    if str(UUID(child_id))!=child_id:raise ValueError('Invalid signal child id')
    child_path=path.parent/child_id
    if child_path.is_symlink():raise ValueError('Signal child must be a local archive')
    source=load_record_fields(child_path/'experiment.json',{'run_id','experiment_id','status','kind','manifest','metrics'})
    sm=source['manifest'];cfg=sm['config']
    if source['run_id']!=child_id or source['experiment_id']!=manifest['source_experiment_id'] or source['experiment_id']!=digest(sm):raise ValueError('Signal child identity mismatch')
    if source.get('kind','factor')!='factor' or source['status']!='completed':raise ValueError('Signal child must be a completed factor artifact')
    if sm['runtime']!=manifest['runtime']:raise ValueError('Signal and execution runtime fingerprints differ')
    expected_config={**manifest['config'],'replay':True}
    if cfg!=expected_config or sm['data_snapshot']!=manifest['signal_data_snapshot'] or sm['universe']!=manifest['universe']:raise ValueError('Signal and execution provenance differ')
    if 'frozen_inputs' not in sm and (sm.get('universe',{}).get('id')!='explicit_symbols' or cfg.get('context')):raise ValueError('Historical universe or external timeframe inputs require frozen metadata; no substitution allowed')
    price_mode=manifest['execution'].get('price_mode','account')
    if price_mode=='account' and manifest['data_snapshot']['adjustment']!='raw':raise ValueError('Account execution archive must contain raw prices')
    if price_mode=='research' and manifest['data_snapshot']!=manifest['signal_data_snapshot']:raise ValueError('Research execution must use the signal price snapshot')
    backend=manifest['backend']
    if backend!='open':
        import importlib.metadata
        if manifest.get('backend_version')!=importlib.metadata.version('vnpy'):raise ValueError('vn.py version differs from the original run')
    signal_bars=pl.read_parquet(child_path/'bars.parquet');raw_bars=pl.read_parquet(path/'bars.parquet')
    keys=['symbol','datetime','available_at']
    assert_frame_equal(signal_bars.select(keys).sort(keys),raw_bars.select(keys).sort(keys))
    if price_mode=='research' or sm['data_snapshot']['adjustment']=='raw':assert_frame_equal(signal_bars,raw_bars)
    archived_targets=pl.read_parquet(path/'targets.parquet')
    if digest(archived_targets.write_json())!=manifest['targets_hash']:raise ValueError('Archived targets hash mismatch')
    mapping={'research_question':'question','factor_id':'factor','factor_version':'version','random_seed':'seed'}
    spec={mapping.get(k,k):v for k,v in cfg.items() if k not in ('data','theory_origin') and v is not None}
    spec.update(cfg['data']);spec.update(adjustment=sm['data_snapshot']['adjustment'],mode='single')
    if 'frozen_inputs' in sm:
        from quantlab.storage.reproduction import config_from_record
        config=config_from_record(cfg)
    else:config=replace(prepare(spec).config,theory_origin=cfg.get('theory_origin'))
    class FrozenSource:
        def __init__(self,bars,snapshot):
            self.batch=DataBatch(bars,DataSnapshot(**{**snapshot,'files':tuple(snapshot['files'])}))
        def load(self,request):
            if request!=config.data:raise ValueError('Reproduction requested an unbundled data range')
            return self.batch
    signal_data=FrozenSource(signal_bars,sm['data_snapshot']);universe=ExplicitUniverse(config.data.symbols)
    if 'frozen_inputs' in sm:
        from quantlab.storage.frozen_inputs import load_frozen_inputs
        from quantlab.storage.reproduction import config_from_record
        config=config_from_record(cfg)
        signal_data,universe=load_frozen_inputs(child_path,sm)
        frozen_signal=signal_data.load(config.data)
        assert_frame_equal(signal_bars,frozen_signal.bars,check_exact=True)
    runner=ExperimentRunner(signal_data,default_registry(),universe,LocalExperimentStore(output))
    result=ExecutionStudy(runner,FrozenSource(raw_bars,manifest['data_snapshot'])).run(config,
        ExecutionConfig(**{**manifest['execution'],'price_mode':price_mode}),PortfolioConfig(**manifest['portfolio']),backend,
        MarketRules(manifest['market_rules']) if manifest.get('market_rules') is not None else None)
    verification={'run_id':result.run_id,'artifact_path':str(result.artifact_path),'source_run_id':record['run_id'],
        'status':'not_verified','scope':'Frozen signal/raw bars; recomputed research metrics, signals, targets, fills, rejections, execution summary and equity; rtol=1e-9, atol=1e-12. No external lake access.'}
    try:
        actual=load_record_fields(result.artifact_path/'experiment.json',fields)
        new_child=Path(output)/actual['children'][0]['run_id']
        new_source=load_record_fields(new_child/'experiment.json',{'metrics'})
        _compare_reproduction(source['metrics'],new_source['metrics'],'research/metrics')
        for key in ('execution','fills','rejections','backend_comparison'):
            _compare_reproduction(record.get(key),actual.get(key),key)
        for left,right in [(child_path/'observations.parquet',new_child/'observations.parquet'),
                           (path/'targets.parquet',result.artifact_path/'targets.parquet'),
                           (path/'observations.parquet',result.artifact_path/'observations.parquet')]:
            assert_frame_equal(pl.read_parquet(left),pl.read_parquet(right),check_exact=False,rel_tol=1e-9,abs_tol=1e-12)
        verification['status']='numerically_matched'
    except Exception as error:
        verification.update(status='mismatch',error=str(error))
        raise ValueError(f'复算不一致：{error}；核对记录：{result.artifact_path}/reproduction.json') from error
    finally:
        (result.artifact_path/'reproduction.json').write_text(encode(verification))
    return verification


def reproduce_artifact(artifact, output):
    from quantlab.storage.experiments import load_record_fields
    kind=load_record_fields(Path(artifact)/'experiment.json',{'kind'}).get('kind','factor')
    if kind=='factor':return reproduce_factor(artifact,output)
    if kind=='execution':return reproduce_execution(artifact,output)
    from quantlab.storage.reproduction import KINDS, reproduce_research
    if kind in KINDS:return reproduce_research(artifact,output)
    if kind=='trial_registry':
        from quantlab.storage.trial_reproduction import reproduce_registry
        return reproduce_registry(artifact,output)
    from quantlab.storage.derived_reproduction import KINDS as DERIVED_KINDS, reproduce_derived
    if kind in DERIVED_KINDS:return reproduce_derived(artifact,output)
    raise ValueError('Unsupported numerical reproduction artifact kind: '+kind)
