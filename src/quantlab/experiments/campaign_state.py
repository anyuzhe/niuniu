"""Checksummed campaign receipts and source signatures; no separate worker."""
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4
import fcntl
import json
import os
from quantlab.storage.codec import digest, encode
from quantlab.agent.planning import ProposalError
from quantlab.progress import checkpoint, ResearchCancelled


def canonical_id(value):
    if not isinstance(value,str) or str(UUID(value)) != value: raise ValueError('Invalid campaign UUID')
    return value


def read_checked(path):
    if path.is_symlink(): raise ValueError('Campaign receipt cannot be a symlink')
    value = json.loads(path.read_text())
    if value.get('checksum') != digest({k:v for k,v in value.items() if k!='checksum'}):
        raise ValueError('Campaign receipt checksum mismatch')
    return {k:v for k,v in value.items() if k!='checksum'}


def write_checked(path,value):
    if path.is_symlink(): raise ValueError('Campaign receipt cannot be a symlink')
    temporary = path.with_name('.'+str(uuid4())+'.pending')
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            stream.write(encode({**value,'checksum':digest(value)})); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
    finally: temporary.unlink(missing_ok=True)


@contextmanager
def campaign_directory(output,job_id):
    output = Path(output).resolve(); parent = output/'_campaigns'
    folder = parent/canonical_id(job_id)
    if parent.is_symlink() or folder.is_symlink(): raise ValueError('Campaign directory symlink')
    folder.mkdir(parents=True,exist_ok=True); lock = folder/'campaign.lock'
    if lock.is_symlink(): raise ValueError('Campaign lock symlink')
    with lock.open('a+b') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try: yield folder
        finally: fcntl.flock(stream,fcntl.LOCK_UN)


def input_signature(spec,data_root):
    from quantlab.workbench.jobs import prepare
    from quantlab.data.provider import local_data_provider
    from quantlab.data.universe import build_universe
    submission = prepare(spec); cfg = submission.config
    try:
        provider = local_data_provider(data_root,submission.adjustment)
        batch = provider.load(cfg.data)
        universe = build_universe(data_root,cfg.data.symbols,submission.universe)
        inputs = [{'snapshot':asdict(batch.snapshot),'bars_hash':digest(batch.bars.write_json())}]
        if cfg.context:
            context = provider.load(cfg.context.request(cfg.data))
            inputs.append({'snapshot':asdict(context.snapshot),'bars_hash':digest(context.bars.write_json())})
        if submission.execution and submission.execution.price_mode=='account' and submission.adjustment!='raw':
            raw = local_data_provider(data_root,'raw').load(cfg.data)
            inputs.append({'snapshot':asdict(raw.snapshot),'bars_hash':digest(raw.bars.write_json())})
        return {'status':'available','inputs':inputs,'universe_version':universe.version,
            'mask_hash':digest(universe.mask(batch.bars).sort('symbol','datetime').write_json())}
    except (ResearchCancelled,TimeoutError): raise
    except (OSError,ValueError,KeyError) as error:
        return {'status':'unavailable','error_type':type(error).__name__,'reason':str(error)[:500]}
