"""Persist executable client plans beside the fixed research registry."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from uuid import UUID,uuid4
from quantlab.storage.codec import digest,encode
from quantlab.workbench.jobs import prepare
from quantlab.experiments.trial_layout import planned_layout
from quantlab.experiments.trial_registry import _load_registry


def planned_trial(spec,trial_id):
    prepared=prepare(spec)
    if prepared.mode not in ('single','ablation','holdout','walkforward','sweep','theory_study'):raise ValueError('固定族支持单因子、消融、样本外、滚动、扫描或理论研究')
    config=prepared.config
    if config.permutation is None:raise ValueError('固定族必须启用显著性检验')
    if prepared.mode=='holdout' and config.processor is not None and hasattr(config.processor,'fit_start'):
        config=replace(config,processor=replace(config.processor,fit_start=config.data.start,fit_end=prepared.split.train_end))
    trial={'trial_id':trial_id,'config':json.loads(encode(asdict(config)))}
    if prepared.mode!='single':
        design={}
        if prepared.mode=='holdout':design={'split':asdict(prepared.split)}
        elif prepared.mode=='walkforward':design={'schedule':asdict(prepared.schedule)}
        elif prepared.mode=='sweep':design={k:asdict(v) if v is not None else None for k,v in [('grid',prepared.grid),('split',prepared.split),('schedule',prepared.schedule)]}
        elif prepared.mode=='theory_study':design={'plan':asdict(prepared.theory_study)}
        trial['study']={'kind':prepared.mode,'design':json.loads(encode(design))};trial['layout']=planned_layout(trial)
    return trial


def save_submissions(root,specs):
    root=Path(root);registry=_load_registry(root);trials=registry['plan']['trials']
    if len(specs)!=len(trials):raise ValueError('研究配置数量与冻结计划不一致')
    entries=[]
    for spec,trial in zip(specs,trials):
        if planned_trial(spec,trial['trial_id'])!=trial:raise ValueError('研究配置与冻结计划不一致')
        entries.append({'trial_id':trial['trial_id'],'job_id':str(uuid4()),'spec':spec})
    payload={'registry_id':registry['registry_id'],'entries':entries};payload['checksum']=digest(payload)
    with (root/'submissions.json').open('x',encoding='utf-8') as stream:stream.write(encode(payload))
    return payload


def load_submissions(root):
    root=Path(root);registry=_load_registry(root);payload=json.loads((root/'submissions.json').read_text())
    if payload.get('checksum')!=digest({k:v for k,v in payload.items() if k!='checksum'}) or payload.get('registry_id')!=registry['registry_id']:raise ValueError('可执行计划校验不一致')
    entries=payload['entries'];trials=registry['plan']['trials']
    if len(entries)!=len(trials):raise ValueError('研究计划项缺失')
    ids=set()
    for entry,trial in zip(entries,trials):
        if entry['job_id'] in ids or str(UUID(entry['job_id']))!=entry['job_id']:raise ValueError('任务编号重复或无效')
        ids.add(entry['job_id'])
        if entry['trial_id']!=trial['trial_id'] or planned_trial(entry['spec'],entry['trial_id'])!=trial:raise ValueError('可执行配置偏离冻结研究计划')
    return [(e['job_id'],e['spec']) for e in entries]
