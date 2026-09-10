"""Job-scoped reuse of completed leaf studies with input and artifact checksums."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import hashlib
import json
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import load_record_fields
from quantlab.progress import checkpoint

_ACTIVE=ContextVar('quantlab_completed_children',default=None)


def _files(path):
    if path.is_symlink() or not path.is_dir(): raise ValueError('Invalid completed child directory')
    files={}
    for item in sorted(path.rglob('*')):
        if item.is_symlink(): raise ValueError('Child artifacts may not contain symlinks')
        if item.is_file(): files[str(item.relative_to(path))]=hashlib.sha256(item.read_bytes()).hexdigest()
    if 'experiment.json' not in files: raise ValueError('Missing completed child record')
    return files


def _write(path,value):
    temporary=path.with_name(path.name+'.'+str(uuid4())+'.tmp')
    try:
        temporary.write_text(encode(value));temporary.replace(path)
    finally: temporary.unlink(missing_ok=True)


class ChildScope:
    def __init__(self,output,root):
        self.output=output;self.root=root;self.counts={};self.events=[];self.runtime=None
    def acquire(self,identity):
        fingerprint=digest(identity);slot=self.counts.get(fingerprint,0)
        self.counts[fingerprint]=slot+1
        key=digest({'input':fingerprint,'occurrence':slot});path=self.root/(key+'.json')
        ticket=(self,key,path,fingerprint,slot)
        try:
            if path.is_symlink(): raise ValueError('Checkpoint symlink')
            entry=json.loads(path.read_text())
            if entry['key']!=key or str(UUID(entry['run_id']))!=entry['run_id']:
                raise ValueError('Checkpoint identity mismatch')
            artifact=self.output/entry['run_id']
            if _files(artifact)!=entry['files']: raise ValueError('Completed artifact checksum changed')
            record=load_record_fields(artifact/'experiment.json',{'run_id','experiment_id','status','metrics','checkpoint_input_hash','checkpoint_slot'})
            if record['status']!='completed' or record['run_id']!=entry['run_id']:
                raise ValueError('Child is not completed')
            if record.get('checkpoint_input_hash')!=fingerprint or record.get('checkpoint_slot')!=slot:
                raise ValueError('Completed child input/occurrence binding differs')
            from quantlab.experiments.runner import ExperimentResult
            result=ExperimentResult(record['experiment_id'],record['run_id'],artifact,record['metrics'])
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.events.append({'key':key,'status':'miss','reason':str(error)})
            return ticket,None
        checkpoint('复用已核对的子研究 · '+result.run_id)
        self.events.append({'key':key,'status':'reused','run_id':result.run_id})
        return ticket,result
    def publish(self,ticket,result):
        from quantlab.experiments.runner import runtime_fingerprint
        if runtime_fingerprint()!=self.runtime: raise ValueError('Source changed during the study; restart with one code revision')
        path=Path(result.artifact_path)
        if path.resolve().parent!=self.output or path.name!=result.run_id:
            raise ValueError('Completed child belongs to a different artifact root')
        entry={'key':ticket[1],'run_id':result.run_id,'files':_files(path)}
        _write(ticket[2],entry)
        self.events.append({'key':ticket[1],'status':'published','run_id':result.run_id})
    def summary(self):
        return {'completed_children_reused':sum(e['status']=='reused' for e in self.events),
            'completed_children_published':sum(e['status']=='published' for e in self.events),
            'cache_misses':sum(e['status']=='miss' for e in self.events),
            'scope':'Exact job/spec and leaf occurrence; source bars, universe masks, controls, context, code and every artifact file checked. Parent summaries are regenerated.'}


@contextmanager
def child_checkpoint_scope(output,job_id,spec):
    output=Path(output).resolve()
    root=output/'_jobs'/'_completed_children'/str(UUID(str(job_id)))/digest(spec)
    if not root.resolve().is_relative_to(output): raise ValueError('Checkpoint directory escapes artifact root')
    root.mkdir(parents=True,exist_ok=True)
    scope=ChildScope(output,root);token=_ACTIVE.set(scope)
    try: yield scope
    finally:
        _ACTIVE.reset(token)
        _write(root/('attempt-'+str(uuid4())+'.json'),{'created_at':datetime.now(timezone.utc).isoformat(),
            'summary':scope.summary(),'events':scope.events})


def checkpoint_active(): return _ACTIVE.get() is not None


def prepare_child(runner,config,manifest,captured,batch):
    scope=_ACTIVE.get()
    if scope is None: return None,None,None
    from quantlab.experiments.research import FactorResearchEngine
    from quantlab.processing.pipeline import PipelineConfig
    if type(runner.research) is not FactorResearchEngine: return None,None,None
    if scope.runtime is None: scope.runtime=manifest['runtime']
    if scope.runtime!=manifest['runtime']: raise ValueError('Source changed within the parent study')
    mask=runner.universe.mask(batch.bars).sort('symbol','datetime')
    controls={}
    if isinstance(config.processor,PipelineConfig):
        training=getattr(runner.universe,'source',runner.universe)
        controls['training_mask']=digest(training.mask(batch.bars).sort('symbol','datetime').write_json())
    if config.context is not None:
        captured.load(config.context.request(config.data))
        factor=runner.registry.get(config.context.factor_id,config.context.version)
        controls['context_factor']={'definition':asdict(factor.definition),'code':runner.registry.code_hash(factor)}
    inputs=[{'request':asdict(request),'snapshot':asdict(value.snapshot),'bars':digest(value.bars.write_json())}
        for request,value in captured.loads]
    identity={'manifest':manifest,'inputs':inputs,'mask':digest(mask.write_json()),'controls':controls}
    ticket,result=scope.acquire(identity)
    return ticket,result,mask


def publish_child(ticket,result):
    if ticket is not None: ticket[0].publish(ticket,result)
