"""Resolve local experiment fields; callers cannot supply their own fact values."""
import hashlib
import re
from quantlab.agent.memory_store import MemoryError, identifier
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import load_record_fields
from quantlab.workbench.server import ArtifactCatalog

ROOTS = {'metrics','execution','summary','inference','status','error','limitations','manifest'}


def tokens(pointer):
    if not isinstance(pointer,str) or not pointer.startswith('/') or len(pointer)>400:
        raise MemoryError('INVALID_ARGUMENT', '证据字段须为不超过400字的 JSON Pointer。')
    if re.search(r'~(?![01])',pointer):
        raise MemoryError('INVALID_ARGUMENT', '证据字段转义无效。')
    parts = [p.replace('~1','/').replace('~0','~') for p in pointer[1:].split('/')]
    if parts[0] not in ROOTS or (parts[0]=='manifest' and (len(parts)<2 or parts[1] not in ('config','data_snapshot','universe'))):
        raise MemoryError('UNSUPPORTED_FIELD', '只允许研究指标、状态、限制和指定配置字段。')
    return parts


def signature(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


class EvidenceResolver:
    def __init__(self, output):
        self.catalog = ArtifactCatalog(output)

    def capture(self, run_id, pointer):
        identifier(run_id); parts = tokens(pointer)
        try:
            path = self.catalog.file(run_id, 'experiment.json')
            before = signature(path)
            if before[2] > 128*1024*1024:
                raise MemoryError('RESULT_TOO_LARGE', '归档超过当前证据读取预算，请使用较小研究归档。')
            record = load_record_fields(path, {parts[0],'manifest','run_id','experiment_id','status','kind'})
            with path.open('rb') as stream:
                checksum = hashlib.file_digest(stream,'sha256').hexdigest()
            if signature(path) != before:
                raise MemoryError('SOURCE_CHANGED', '证据读取期间归档发生变化。')
            if record.get('run_id') != run_id or digest(record['manifest']) != record.get('experiment_id'):
                raise MemoryError('INVALID_ARTIFACT', '实验身份与配置校验不一致。')
            value = record
            for part in parts:
                if isinstance(value, list):
                    if not re.fullmatch(r'0|[1-9][0-9]*',part): raise KeyError(part)
                    value = value[int(part)]
                elif isinstance(value, dict): value = value[part]
                else: raise KeyError(part)
            if len(encode(value).encode('utf-8')) > 8192:
                raise MemoryError('RESULT_TOO_LARGE', '请选择更具体的指标字段；不保存大型证据对象。')
        except (OSError, KeyError, IndexError, TypeError) as error:
            raise MemoryError('SOURCE_UNAVAILABLE', '归档或指定证据字段不可读取：'+type(error).__name__) from None
        cfg = record['manifest'].get('config',{})
        data = cfg.get('data',{})
        snapshot = record['manifest'].get('data_snapshot') or {}
        return {'run_id':run_id, 'pointer':pointer, 'value':value, 'value_hash':digest(value),
                'source_sha256':checksum, 'experiment_id':record['experiment_id'],
                'context':{'status':record.get('status'), 'kind':record.get('kind','factor'),
                    'factor_id':cfg.get('factor_id'), 'factor_version':cfg.get('factor_version'),
                    'parameters':cfg.get('parameters'), 'start':data.get('start'), 'end':data.get('end'),
                    'timeframe':data.get('timeframe'), 'symbols':data.get('symbols',[]),
                    'snapshot_id':snapshot.get('snapshot_id'), 'adjustment':snapshot.get('adjustment'),
                    'universe':record['manifest'].get('universe',{}).get('id')},
                'uri':'quantlab://run/'+run_id}

    def verify(self, evidence):
        try:
            current = self.capture(evidence['run_id'], evidence['pointer'])
            intact = (current['source_sha256']==evidence['source_sha256'] and
                      current['value_hash']==evidence['value_hash'] and
                      digest(evidence['value'])==evidence['value_hash'])
            return {'run_id':evidence['run_id'], 'pointer':evidence['pointer'],
                    'status':'verified' if intact else 'source_changed',
                    'claim_verified':False}
        except (MemoryError,ValueError,KeyError,TypeError) as error:
            return {'run_id':evidence.get('run_id'), 'pointer':evidence.get('pointer'),
                    'status':'unavailable', 'reason':getattr(error,'code','SOURCE_UNAVAILABLE'),
                    'claim_verified':False}
