"""Fixed local experiment families with write-once result bindings."""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from quantlab.statistics.permutation import PermutationConfig, holm
from quantlab.storage.codec import digest, encode
from quantlab.experiments.trial_layout import planned_layout, hypotheses, extract_parent, descendant_run_ids

METRICS = ('daily_mean_ic', 'daily_mean_rank_ic')
LIMITS = ('Local configuration registration, not trusted timestamping or proof of unseen data. '
          'Holm covers only this fixed family, conditional on valid raw p-values; repeated report '
          'inspection/stopping and studies outside this registry are not controlled. '
          'Supports single, ablation, holdout, walkforward, sweep and theory-study parents; execution-return families use their own explicit plan.')


def _time(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return dt


def _validate_plan(plan):
    if set(plan) != {'name','alpha','trials'} or not isinstance(plan['name'],str) or not plan['name'].strip():
        raise ValueError('Plan requires name, alpha, trials')
    PermutationConfig(alpha=plan['alpha'])
    if not isinstance(plan['trials'],list) or not plan['trials']:
        raise ValueError('Plan requires nonempty trials')
    ids, configs = set(), set()
    for trial in plan['trials']:
        if set(trial) not in ({'trial_id','config'}, {'trial_id','config','study','layout'}) or not isinstance(trial['trial_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',trial['trial_id']):
            raise ValueError('Trial requires safe trial_id and complete config')
        config=trial['config']
        if not isinstance(config,dict) or not config.get('factor_id') or not config.get('research_question'):
            raise ValueError('Complete ExperimentConfig JSON required')
        horizons=config.get('horizons')
        if not isinstance(horizons,list) or not horizons or any(type(h) is not int or h<1 for h in horizons) or len(set(horizons))!=len(horizons):
            raise ValueError('Unique positive horizons required')
        if not isinstance(config.get('permutation'),dict):
            raise ValueError('Each registered experiment must enable permutation')
        PermutationConfig(**config['permutation'])
        if 'study' in trial:
            if planned_layout(trial)!=trial['layout']:raise ValueError('Frozen parent test layout differs from current planner')
        elif config.get('incremental_test'):
            raise ValueError('Paired IC requires registered ablation study')
        fingerprint=digest({'config':config,'study':trial.get('study')})
        if trial['trial_id'] in ids or fingerprint in configs:
            raise ValueError('Duplicate trial id or exact configuration')
        ids.add(trial['trial_id']);configs.add(fingerprint)


def create_registry(plan, destination):
    plan=json.loads(encode(plan))
    for trial in plan.get('trials',[]):
        if 'study' in trial:
            if 'layout' in trial:raise ValueError('Layout is generated from design, not supplied manually')
            trial['layout']=planned_layout(trial)
    _validate_plan(plan)
    record={'version':'1.1.0','created_at':datetime.now(timezone.utc).isoformat(),'plan':plan}
    record['registry_id']=digest(record)
    path=Path(destination)
    path.mkdir(parents=True,exist_ok=False)
    (path/'results').mkdir()
    (path/'registry.json').write_text(encode(record))
    return record


def _load_registry(root):
    r=json.loads((Path(root)/'registry.json').read_text())
    if r.get('version') not in ('1.0.0','1.1.0') or r.get('registry_id')!=digest({k:v for k,v in r.items() if k!='registry_id'}):
        raise ValueError('Registry fingerprint/version mismatch')
    _validate_plan(r['plan']);_time(r['created_at'])
    return r


def _extract(record, trial):
    if 'study' not in trial and (record.get('kind') is not None or any(record.get(k) for k in ('children','periods','folds','evaluations','contrasts'))):
        raise ValueError('Bind single research experiments, not parent studies')
    if record.get('manifest',{}).get('config')!=trial['config']:
        raise ValueError('Result configuration differs from registered configuration')
    if not isinstance(record.get('run_id'),str) or not record['run_id']:
        raise ValueError('Result requires run_id')
    _time(record['created_at'])
    status=record.get('status')
    if status not in ('completed','failed'):
        raise ValueError('Only completed or failed artifacts can be bound')
    if 'study' in trial:
        return extract_parent(record,trial,_validate_raw)
    tests=[]
    expected={str(h) for h in trial['config']['horizons']}
    if status=='completed' and set(record.get('metrics',{}))!=expected:
        raise ValueError('Completed result horizon set differs from plan')
    for horizon in trial['config']['horizons']:
        source=record.get('metrics',{}).get(str(horizon),{}).get('permutation',{})
        if status=='completed' and set(source)!=set(METRICS):
            raise ValueError('Completed experiment must contain every planned raw test')
        for metric in METRICS:
            test=source.get(metric,{}) if status=='completed' else {}
            p=test.get('p_value')
            if status=='completed':
                _validate_raw(test,trial)
            holm([p])
            tests.append({'trial_id':trial['trial_id'],'horizon':horizon,'metric':metric,
                'p_value':p,'status':test.get('status','failed'),'reason':test.get('reason',record.get('error')),
                'raw_test':test})
    return tests


def _validate_raw(test,trial):
    p=test.get('p_value')
    if test.get('method')!='nonoverlapping_date_block_sign_v1' or test.get('status') not in ('computed','unavailable'):
        raise ValueError('Unsupported raw test method/status')
    if (test['status']=='computed') != (p is not None):
        raise ValueError('Raw test status and p-value disagree')
    if test.get('block_days')!=trial['config']['permutation'].get('block_days',5):
        raise ValueError('Raw test block size differs from configuration')
    holm([p])


def bind_result(root, trial_id, artifact):
    root=Path(root);registry=_load_registry(root)
    trial=next((t for t in registry['plan']['trials'] if t['trial_id']==trial_id),None)
    if trial is None:
        raise ValueError('Unknown registered trial')
    path=Path(artifact).resolve()
    if path.is_dir():path=path/'experiment.json'
    raw=path.read_bytes();record=json.loads(raw)
    _extract(record,trial)
    checksum=hashlib.sha256(raw).hexdigest()
    binding={'trial_id':trial_id,'source_path':str(path),'source_sha256':checksum,
        'record':record,'bound_at':datetime.now(timezone.utc).isoformat()}
    binding['binding_id']=digest(binding)
    target=root/'results'/f'{trial_id}.json'
    # Publish only a fully written file. Hard-link creation is atomic and never replaces a binding.
    fd,temp=tempfile.mkstemp(prefix='.pending-',dir=root/'results')
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write(encode(binding));stream.flush();os.fsync(stream.fileno())
        try:os.link(temp,target)
        except FileExistsError:
            existing=json.loads(target.read_text())
            _validate_binding(existing,trial)
            if existing['source_sha256']!=checksum:
                raise ValueError('Trial already bound to a different artifact')
            return {'status':'unchanged','trial_id':trial_id,'binding_id':existing['binding_id']}
    finally:
        Path(temp).unlink(missing_ok=True)
    return {'status':'bound','trial_id':trial_id,'binding_id':binding['binding_id']}


def _validate_binding(binding,trial):
    if binding.get('trial_id')!=trial['trial_id'] or binding.get('binding_id')!=digest({k:v for k,v in binding.items() if k!='binding_id'}):
        raise ValueError('Binding fingerprint/identity mismatch')
    return _extract(binding['record'],trial)


def report_registry(root, destination):
    root=Path(root);registry=_load_registry(root);tests=[];trials=[];seen_runs=set();bindings={}
    for trial in registry['plan']['trials']:
        path=root/'results'/f"{trial['trial_id']}.json"
        if not path.exists():
            tests.extend({'trial_id':trial['trial_id'],**h,'p_value':None,
                'status':'not_run','reason':'no_bound_result','raw_test':{}} for h in hypotheses(trial))
            trials.append({'trial_id':trial['trial_id'],'status':'not_run','timing':'unbound'})
            continue
        binding=json.loads(path.read_text());extracted=_validate_binding(binding,trial);record=binding['record']
        runs=descendant_run_ids(record)
        if runs & seen_runs:raise ValueError('Duplicate root/descendant run bound in family')
        seen_runs.update(runs);bindings[trial['trial_id']]=binding
        tests.extend(extracted)
        trials.append({'trial_id':trial['trial_id'],'status':record['status'],'run_id':record['run_id'],
            'binding_id':binding['binding_id'],'source_sha256':binding['source_sha256'],
            'timing':'after_local_registration' if _time(record['created_at'])>=_time(registry['created_at']) else 'retrospective'})
    for test,p in zip(tests,holm([t['p_value'] for t in tests])):
        test.update(p_holm=p,reject_holm=p<=registry['plan']['alpha'] if p is not None else None)
    report={'registry_id':registry['registry_id'],'created_at':datetime.now(timezone.utc).isoformat(),
        'method':'holm_fwer','alpha':registry['plan']['alpha'],'planned_tests':len(tests),
        'available_tests':sum(t['p_value'] is not None for t in tests),'trials':trials,'tests':tests,'limitations':LIMITS}
    # Snapshot the plan and bound records so later source deletion cannot alter this report.
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    (destination/'registry.json').write_text(encode(registry))
    (destination/'bindings.json').write_text(encode(bindings))
    (destination/'report.json').write_text(encode(report))
    lines=['# 跨实验固定检验族报告','',f"计划 {len(tests)} 项，可检验 {report['available_tests']} 项；Holm alpha={report['alpha']}。",
        '未运行、失败、不可检验项保留名额。原始 p 值统一校正，未使用子实验 p_holm。',
        '本地登记不证明未见数据；retrospective 为登记前已生成结果。反复查看/择时停止及登记之外的探索未受控制。','',
        '| 试验 | 状态 | 时间关系 |','|---|---|---|']
    lines += [f"| {t['trial_id']} | {t['status']} | {t['timing']} |" for t in trials]
    lines += ['','| 试验 | 路径 | 持有期 | 指标 | 原始 p | Holm p | 状态 |','|---|---|---:|---|---:|---:|---|']
    lines += [f"| {t['trial_id']} | {t.get('path','study')} | {t['horizon']} | {t['metric']} | {t['p_value'] if t['p_value'] is not None else 'N/A'} | {t['p_holm'] if t['p_holm'] is not None else 'N/A'} | {t['status']} |" for t in tests]
    (destination/'report.md').write_text('\n'.join(lines)+'\n')
    return report
