"""Freeze an explicit family before computing paired net-return tests."""
from datetime import date,datetime,timezone
from pathlib import Path
from uuid import uuid4
import json
import hashlib
from quantlab.experiments.return_increment import compare_returns
from quantlab.statistics.permutation import holm,PermutationConfig
from quantlab.storage.codec import encode,digest
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.experiments import LocalExperimentStore


def run_return_family(plan, output):
    if set(plan)!={'name','alpha','comparisons'} or not isinstance(plan['comparisons'],list) or not plan['comparisons'] or not plan['name']:raise ValueError('Require name, alpha, comparisons')
    PermutationConfig(alpha=plan['alpha']);seen=set();pairs=set();entries=[]
    for item in plan['comparisons']:
        if set(item)!={'id','candidate','baseline','start'} or not isinstance(item['id'],str) or not item['id']:raise ValueError('Comparison requires id/candidate/baseline/start')
        start=date.fromisoformat(item['start']);paths=[Path(item[k]).resolve() for k in ('candidate','baseline')]
        if paths[0]==paths[1]:raise ValueError('Candidate and baseline must differ')
        pair=(tuple(sorted(map(str,paths))),start)
        if item['id'] in seen or pair in pairs:raise ValueError('Duplicate or reversed return comparison')
        seen.add(item['id']);pairs.add(pair)
        entries.append({**item,'candidate':str(paths[0]),'baseline':str(paths[1])})
    directory=Path(output)/'_return_families'/str(uuid4());directory.mkdir(parents=True,exist_ok=False)
    frozen={'created_at':datetime.now(timezone.utc).isoformat(),'plan':{**plan,'comparisons':entries},
        'method':'paired_net_daily_return_difference; fixed default date-block test; Holm across all planned comparisons',
        'limitations':'Registered before these tests, after underlying executions exist. Local clock, retrospective research; no proof of unseen data or prospective strategy selection.'}
    frozen['registry_id']=digest(frozen);(directory/'plan.json').write_text(encode(frozen))
    tests=[]
    def file_hash(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    for item in entries:
        try:
            inputs=[Path(item[k])/name for k in ('candidate','baseline') for name in ('experiment.json','observations.parquet')]
            before=[file_hash(p) for p in inputs]
            result=compare_returns(item['candidate'],item['baseline'],date.fromisoformat(item['start']),output)
            if before!=[file_hash(p) for p in inputs]:raise ValueError('Source changed while return test was running')
            test=result['summary']['permutation']
            tests.append({'id':item['id'],'status':test['status'],'raw_test':test,'p_value':test.get('p_value'),'run_id':result['run_id'],'artifact_path':result['artifact_path'],'source_hashes':before})
        except (ValueError,OSError,KeyError,TypeError) as error:
            tests.append({'id':item['id'],'status':'failed','p_value':None,'error':str(error)})
        (directory/'progress.json').write_text(encode({'completed':len(tests),'planned':len(entries),'tests':tests}))
    for row,p in zip(tests,holm([r['p_value'] for r in tests])):
        row.update(p_holm=p,reject=p<=plan['alpha'] if p is not None else None)
    report={'registry_id':frozen['registry_id'],'planned_tests':len(entries),'available_tests':sum(r['p_value'] is not None for r in tests),'tests':tests,'limitations':frozen['limitations']}
    (directory/'report.json').write_text(encode(report));(directory/'report.md').write_text('# 固定净收益检验族\n\n```json\n'+encode(report)+'\n```\n')
    run_id=str(uuid4())
    manifest={'config':{'research_question':plan['name']},'runtime':runtime_fingerprint(),'registry':frozen,'report_hash':digest(report)}
    record={'run_id':run_id,'experiment_id':digest(manifest),'created_at':datetime.now(timezone.utc).isoformat(),'kind':'return_family','status':'completed','manifest':manifest,'summary':report,
        'children':[{'run_id':t['run_id'],'artifact_path':t['artifact_path'],'name':t['id']} for t in tests if 'run_id' in t]}
    archive=LocalExperimentStore(output).save(run_id,record,None)
    return {'artifact_path':str(directory),'report':report,'run_id':run_id,'archive_path':str(archive)}
