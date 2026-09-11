"""Execute a finite approved DAG inside the original single-worker queue."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from quantlab.agent.campaign_plan import prepare_campaign
from quantlab.agent.planning import ProposalError
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.experiments.trial_registry import create_registry, _load_registry, bind_result, report_registry
from quantlab.experiments.campaign_state import campaign_directory, read_checked, write_checked, input_signature, canonical_id
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore, load_record_fields
from quantlab.progress import checkpoint, ResearchCancelled

RECEIPT_FIELDS = {'run_id','experiment_id','manifest','status','kind','metrics','execution','summary',
    'children','periods','folds','comparisons','contrasts','stability','inference','pairs','groups'}


@dataclass(frozen=True)
class CampaignResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    summary: dict


def source_record(output,run_id):
    folder = Path(output)/canonical_id(run_id); path = folder/'experiment.json'
    if folder.is_symlink() or path.is_symlink(): raise ValueError('Campaign result symlink')
    record = load_record_fields(path,RECEIPT_FIELDS)
    if record['run_id'] != run_id or record['experiment_id'] != digest(record['manifest']):
        raise ValueError('Campaign result identity mismatch')
    return record


def result_receipt(output,result):
    record = source_record(output,result.run_id)
    if record['status'] != 'completed': raise ValueError('Node did not produce a completed artifact')
    return {'status':'completed','run_id':result.run_id,'experiment_id':result.experiment_id,
        'record_digest':digest(record)}


def verify_receipt(output,receipt):
    record = source_record(output,receipt['run_id'])
    if record['status']!='completed' or digest(record)!=receipt['record_digest']:
        raise ProposalError('CHANGED_ARTIFACT','已完成节点的归档身份或数值记录变化；拒绝静默复用。')
    return record


def initialize_family(folder,plan):
    target = folder/'family'
    if target.is_symlink(): raise ValueError('Registry directory symlink')
    if not target.exists():
        staging = folder/('family-'+str(uuid4()))
        value = {**plan,'trials':[{k:v for k,v in t.items() if k!='layout'} for t in plan['trials']]}
        create_registry(value,staging); staging.rename(target)
    if _load_registry(target)['plan'] != plan: raise ValueError('Campaign registry plan changed')
    return target


def run_campaign(submission,data_root,output,job_id=None):
    from quantlab.workbench.jobs import prepare, execute
    output = Path(output).resolve(); job_id = job_id or str(uuid4())
    preview = prepare_campaign(submission.plan); plan = preview['spec']; nodes = {n['node_id']:n for n in plan['nodes']}
    preview['output']=str(output)
    runtime = runtime_fingerprint(); inputs = {}
    for key in preview['order']:
        checkpoint('研究包数据核对 · '+key)
        inputs[key] = input_signature(nodes[key]['spec'],data_root)
    identity = {'plan':plan,'runtime':runtime,'inputs':inputs,'data_root':str(Path(data_root).resolve())}
    with campaign_directory(output,job_id) as folder:
        path = folder/'state.json'
        if path.exists():
            state = read_checked(path)
            if state.get('job_id')!=job_id or set(state.get('nodes',{}))-set(nodes):
                raise ProposalError('INVALID_ARTIFACT','研究包回执所属任务或节点集合不一致。')
            if digest(state['identity']) != digest(identity):
                raise ProposalError('STALE_CAMPAIGN','研究包的代码、计划或输入数据变化；需新建研究包，不能混合断点。')
        else:
            if (folder/'family').exists():
                raise ProposalError('LOST_RECEIPT','已登记研究包的回执缺失；拒绝自动重新计算。')
            state = {'job_id':job_id,'identity':identity,'nodes':{},'attempts':[], 'final':None}
            write_checked(path,state)
        family = initialize_family(folder,preview['registry_plan'])
        registered = {t['trial_id'] for t in preview['registry_plan']['trials']}
        for receipt in state['nodes'].values():
            if receipt['status']=='completed': verify_receipt(output,receipt)
        if state['final'] is not None:
            record = verify_receipt(output,state['final'])
            return CampaignResult(record['experiment_id'],record['run_id'],output/record['run_id'],record['summary'])
        run_id = str(uuid4()); attempt = {'run_id':run_id,'started_at':datetime.now(timezone.utc).isoformat(),'status':'running'}
        state['attempts'].append(attempt); write_checked(path,state)
        try:
            for index,key in enumerate(preview['order']):
                checkpoint('研究包节点 · '+key,index,len(nodes))
                node = nodes[key]; receipt = state['nodes'].get(key)
                if receipt is None:
                    blocked = [dep for dep in node['depends_on'] if state['nodes'][dep]['status']!='completed']
                    stopped = plan['failure_policy']=='stop' and any(r['status']=='failed' for r in state['nodes'].values())
                    if blocked or stopped:
                        receipt = {'status':'skipped','reason':'failed_dependency' if blocked else 'stop_after_failure','blocked_by':blocked}
                    else:
                        if digest(input_signature(node['spec'],data_root)) != digest(inputs[key]):
                            raise ProposalError('STALE_CAMPAIGN','节点运行前数据变化：'+key)
                        try:
                            result = execute(prepare(node['spec']),data_root,output)
                        except (ResearchCancelled,TimeoutError): raise
                        except Exception as error:
                            receipt = {'status':'failed','error':type(error).__name__+': '+str(error)[:500],
                                'family_binding':'unbound_failure_slot_retained'}
                        else:
                            receipt = result_receipt(output,result)
                        if digest(input_signature(node['spec'],data_root)) != digest(inputs[key]):
                            raise ProposalError('STALE_CAMPAIGN','节点运行期间数据变化；结果未纳入研究包：'+key)
                    state['nodes'][key] = receipt; write_checked(path,state)
                if key in registered and receipt['status']=='completed':
                    bind_result(family,key,output/receipt['run_id'])
            checkpoint('研究包固定检验族汇总',len(nodes),len(nodes))
            report = report_registry(family,folder/('report-'+run_id))
            summary = summarize(preview,state,report)
            record = make_record(run_id,preview,state,summary,'completed')
            target = LocalExperimentStore(output).save(run_id,record,None)
            result = CampaignResult(record['experiment_id'],run_id,target,summary)
            state['final'] = result_receipt(output,result)
            attempt.update(status='completed',finished_at=datetime.now(timezone.utc).isoformat())
            write_checked(path,state)
            return result
        except Exception as error:
            attempt.update(status='interrupted' if isinstance(error,(ResearchCancelled,TimeoutError)) else 'failed',
                error=type(error).__name__+': '+str(error)[:500],finished_at=datetime.now(timezone.utc).isoformat())
            record = make_record(run_id,preview,state,summarize(preview,state,None),'failed')
            record['error'] = attempt['error']
            if not (output/run_id).exists():
                try: LocalExperimentStore(output).save(run_id,record,None)
                except Exception as storage_error: error.add_note('Campaign failure archive: '+str(storage_error))
            write_checked(path,state)
            raise


def summarize(preview,state,report):
    nodes = [{'node_id':key,**state['nodes'].get(key,{'status':'not_run'})} for key in preview['order']]
    counts = {status:sum(n['status']==status for n in nodes) for status in ('completed','failed','skipped','not_run')}
    return {'workflow_status':'unfinished' if counts['not_run'] else 'completed_with_failures' if counts['failed'] or counts['skipped'] else 'completed',
        'nodes':nodes,'counts':counts,'family':report,'planned_tests':preview['estimate']['planned_tests'],
        'limitations':preview['warnings']+['执行失败和跳过项仍在原固定族中，未绑定项的原始p为空；具体原因见节点表。',
            '节点回执核对根归档身份与数值记录，不是全部子目录/Parquet字节的完整性认证；完整归档树校验尚未接入。',
            '支持原节点独立复算；研究包聚合归档的一键复算入口尚未实现。',
            '中断节点复用原有叶子研究断点；已终止失败不自动重试，诊断节点未做IC族显著性推断。']}


def make_record(run_id,preview,state,summary,status):
    manifest = {'config':{'research_question':preview['spec']['question']},'plan':preview['spec'],
        'runtime':state['identity']['runtime'],'input_signatures':{k:digest(v) for k,v in state['identity']['inputs'].items()},
        'node_outcomes':[{'node_id':n['node_id'],'status':n['status'],'experiment_id':n.get('experiment_id')}
            for n in summary['nodes']]}
    return {'run_id':run_id,'experiment_id':digest(manifest),'created_at':datetime.now(timezone.utc).isoformat(),
        'kind':'campaign','status':status,'manifest':manifest,'summary':summary,
        'campaign_job_id':state['job_id'],'registry_plan':preview['registry_plan'],
        'children':[{'name':n['node_id'],'run_id':n['run_id'],'artifact_path':str(Path(preview.get('output',''))/n['run_id'])}
            for n in summary['nodes'] if n.get('run_id')],
        'limitations':summary['limitations']}
