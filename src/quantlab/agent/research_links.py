"""Bounded, read-only local links; no inferred registration or second authority store."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import UUID
from quantlab.agent.memory_store import MemoryStore, MemoryError
from quantlab.agent.research_memory import ResearchMemory
from quantlab.agent.model_config import strict_json
from quantlab.storage.codec import digest
from quantlab.experiments.trial_registry import _validate_plan, _validate_binding, _time, LIMITS
from quantlab.experiments.trial_layout import descendant_run_ids

MAX_FILE_BYTES=8*1024*1024
MAX_PAGE_BYTES=32*1024*1024
MAX_ENTRIES=20000
MAX_TRIALS=200
POLICY=('Only exact local run IDs, immutable binding fingerprints and explicit finding/hypothesis links. '
        'This checks local provenance, not numerical reproduction, trusted preregistration or Alpha. '
        'External CLI registries outside this workspace are not discovered. Follow next_offset; '
        'restart paging if inventory_digest changes. An incomplete/empty later page is UNKNOWN, not UNREGISTERED.')


def _id(value):
    if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError('INVALID_ARGUMENT：需要规范UUID')
    return value


def _safe(root,path):
    relative=path.relative_to(root)
    current=root
    for part in relative.parts:
        current=current/part
        if current.is_symlink():raise ValueError('INVALID_ARTIFACT：拒绝符号链接')
    return path


def _json(root,path,budget):
    _safe(root,path)
    before=path.stat()
    if before.st_size>MAX_FILE_BYTES or before.st_size>budget[0]:
        raise ValueError('RESULT_TOO_LARGE：来源超过有界读取预算')
    with path.open('rb') as stream:raw=stream.read(MAX_FILE_BYTES+1)
    budget[0]-=len(raw);after=path.stat()
    if len(raw)>MAX_FILE_BYTES or budget[0]<0 or (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('INVALID_ARTIFACT：来源在读取中变化或超限')
    value=strict_json(raw.decode('utf-8'))
    if not isinstance(value,dict):raise ValueError('INVALID_ARTIFACT：来源必须是JSON对象')
    return value,hashlib.sha256(raw).hexdigest()


def _run(root,rid,budget):
    _id(rid);folder=_safe(root,root/rid)
    if not folder.exists():return None,None
    value,sha=_json(root,folder/'experiment.json',budget)
    if value.get('run_id')!=rid or value.get('experiment_id')!=digest(value.get('manifest')):
        raise ValueError('INVALID_ARTIFACT：实验身份或manifest指纹不一致')
    return value,sha


def _registry(value):
    if (value.get('version') not in ('1.0.0','1.1.0') or
        value.get('registry_id')!=digest({k:v for k,v in value.items() if k!='registry_id'})):
        raise ValueError('INVALID_ARTIFACT：固定检验族登记指纹错误')
    plan=value.get('plan')
    if not isinstance(plan,dict) or len(plan.get('trials',[]))>MAX_TRIALS:
        raise ValueError('RESULT_TOO_LARGE：检验族超出单条关联读取预算')
    _validate_plan(plan);_time(value['created_at'])
    return value


def _family(root,rid,source_id,kind,budget):
    if kind=='archive':
        record,source_sha=_run(root,source_id,budget)
        if record is None or record.get('kind')!='trial_registry':return None
        manifest=record['manifest'];registry=_registry(manifest['registry'])
        if digest(record.get('summary'))!=manifest.get('report_hash'):
            raise ValueError('INVALID_ARTIFACT：检验族报告指纹变化')
        bindings=manifest['bindings']
        registry_run_id=source_id
    else:
        directory=_safe(root,root/'_trial_registries'/source_id)
        registry,source_sha=_json(root,directory/'registry.json',budget);registry=_registry(registry)
        registry_run_id=None;bindings={}
        for trial in registry['plan']['trials']:
            path=_safe(root,directory/'results'/(trial['trial_id']+'.json'))
            if path.exists():bindings[trial['trial_id']]=_json(root,path,budget)[0]
    trials={t['trial_id']:t for t in registry['plan']['trials']}
    if not isinstance(bindings,dict) or set(bindings)-set(trials):
        raise ValueError('INVALID_ARTIFACT：未知检验槽位')
    matches=[]
    for tid,binding in bindings.items():
        _validate_binding(binding,trials[tid]);_time(binding['bound_at'])
        bound=binding['record']
        if rid not in descendant_run_ids(bound):continue
        local,local_sha=_run(root,_id(bound['run_id']),budget)
        if local is None or local_sha!=binding.get('source_sha256') or local!=bound:
            raise ValueError('INVALID_ARTIFACT：绑定的实验原文已变化或不可读取')
        matches.append({'trial_id':tid,'binding_id':binding['binding_id'],
                        'source_run_id':bound['run_id'],'source_sha256':local_sha,
                        'relation':'direct' if rid==bound['run_id'] else 'explicit_descendant',
                        'registered_config_digest':digest(trials[tid]['config']),
                        'timing':'after_local_registration' if _time(bound['created_at'])>=_time(registry['created_at']) else 'retrospective'})
    if not matches:return None
    if len(matches)>20:raise ValueError('RESULT_TOO_LARGE：关联槽位过多，请在原检验族工作台查看')
    return {'registry_id':registry['registry_id'],'registry_run_id':registry_run_id,
            'source_kind':kind,'source_id':source_id,'source_sha256':source_sha,
            'name':registry['plan']['name'],'alpha':registry['plan']['alpha'],
            'matches':matches,'numeric_verification':False,'limitations':LIMITS}


def _inventory(root,store):
    entries=[];errors=[]
    def directory(path,kind):
        _safe(root,path)
        if not path.exists():return
        for index,child in enumerate(path.iterdir()):
            if index>=MAX_ENTRIES:raise ValueError('RESULT_TOO_LARGE：工作空间目录超过扫描预算')
            try:_id(child.name)
            except ValueError:continue
            entries.append((kind,child.name))
    directory(root,'archive')
    directory(root/'_trial_registries','live_registry')
    if store.path.is_symlink() or store.directory.is_symlink():
        raise ValueError('INVALID_ARTIFACT：研究记忆路径为符号链接')
    if store.path.exists():
        try:
            with store.connection() as db:
                ids=db.execute('SELECT id FROM memory_entries ORDER BY id LIMIT 10001').fetchall()
                if len(ids)>10000:raise ValueError('RESULT_TOO_LARGE：研究记忆超过预算')
                entries.extend(('memory',r['id']) for r in ids)
        except (sqlite3.Error,MemoryError) as exc:errors.append({'source':'memory','error':str(exc)[:200]})
    if len(entries)>MAX_ENTRIES:raise ValueError('RESULT_TOO_LARGE：关联目录超过预算')
    return sorted(entries),errors


def _memory(root,store,rid,mid):
    value=store.get(mid)
    refs=[e for e in value.get('evidence',[]) if e.get('run_id')==rid]
    if not refs:return None
    checked=ResearchMemory(root).get(mid)
    parent=None
    if value.get('hypothesis_id'):
        h=store.get(value['hypothesis_id'])
        if h['kind']!='hypothesis' or h['candidate_id']!=value['candidate_id']:
            raise ValueError('INVALID_ARTIFACT：研究假设父引用错误')
        parent={'memory_id':h['memory_id'],'title':h['title'],'kind':'hypothesis'}
    return {'memory_id':mid,'kind':value['kind'],'title':value['title'],'status':value['status'],
            'hypothesis_id':value.get('hypothesis_id'),'hypothesis':parent,
            'source_integrity':checked['source_integrity'],'claim_verified':False,
            'evidence':[{'run_id':rid,'pointer':e['pointer'],'relation':e['relation']} for e in refs]}


def get_run_research_links(output,run_id,*,offset=0,limit=20):
    supplied=Path(output)
    if supplied.is_symlink() or not supplied.is_dir():raise ValueError('INVALID_ARTIFACT：工作空间无效')
    root=supplied.resolve();rid=_id(run_id)
    if type(offset) is not int or not 0<=offset<=100000 or type(limit) is not int or not 1<=limit<=20:
        raise ValueError('INVALID_ARGUMENT：分页参数无效')
    budget=[MAX_PAGE_BYTES];record,sha=_run(root,rid,budget)
    if record is None:return {'run_id':rid,'status':'UNKNOWN','registered_families':[],
                             'memory_links':[],'errors':[],'next_offset':None,'incomplete':True,'policy':POLICY}
    store=MemoryStore(root);entries,errors=_inventory(root,store)
    window=entries[offset:offset+limit];families=[];memories=[]
    for kind,key in window:
        try:
            item=_memory(root,store,rid,key) if kind=='memory' else _family(root,rid,key,kind,budget)
            if item is not None:(memories if kind=='memory' else families).append(item)
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
            errors.append({'source_kind':kind,'source_id':key,'error':str(exc)[:240]})
    _,after=_run(root,rid,budget)
    if sha!=after:raise ValueError('INVALID_ARTIFACT：目标实验在查询中变化')
    next_offset=offset+len(window) if offset+len(window)<len(entries) else None
    complete=offset==0 and next_offset is None and not errors
    result={'run_id':rid,'run_status':record['status'],'run_kind':record.get('kind','factor'),
            'target_sha256':sha,'status':'REGISTERED' if families else ('UNREGISTERED' if complete else 'UNKNOWN'),
            'registered_families':families,'memory_links':memories,'errors':errors,
            'offset':offset,'scanned':len(window),'total_sources':len(entries),'next_offset':next_offset,
            'inventory_digest':digest(entries),'incomplete':not complete,
            'local_links_only':True,'policy':POLICY}
    if len(json.dumps(result,ensure_ascii=False).encode())>24000:
        raise ValueError('RESULT_TOO_LARGE：完整关联响应超限，请缩小limit')
    return result

