"""Typed, read-only agenda navigation. Labels and paths cannot dispatch code."""
from copy import deepcopy
from uuid import UUID
from quantlab.storage.codec import digest

FIELDS={'watch':'watch_id','alpha_factory':'proposal_id','memory':'memory_id','experiment':'run_id',
        'job':'job_id','dsl_candidate':'candidate_id','dsl_proposal':'request_id',
        'incremental_evidence':'proposal_id','proposal':'proposal_id'}
LABELS={'watch':'原观察池','alpha_factory':'原Factory审批/结果','memory':'原假设/结论',
        'experiment':'原实验归档','job':'精确任务记录（只读）','factor':'精确因子版本与参数',
        'dsl_candidate':'已注册DSL候选（只读）','dsl_proposal':'原DSL注册提案',
        'incremental_evidence':'原增量证据包','proposal':'原研究提案'}


def canonical_target(reference):
    if not isinstance(reference,dict):raise ValueError('证据引用必须为对象')
    kind=reference.get('kind')
    if not isinstance(kind,str) or kind not in LABELS:raise ValueError('此证据类型尚无安全的原生入口')
    if kind=='factor':
        fid=reference.get('factor_id');version=reference.get('version')
        if any(not isinstance(v,str) or not v.strip() or len(v)>200 for v in (fid,version)):
            raise ValueError('因子引用必须携带精确ID和版本，不能猜测latest')
        result={'kind':kind,'factor_id':fid,'version':version}
        if 'parameters' in reference:
            params=reference['parameters']
            if not isinstance(params,dict):raise ValueError('因子参数必须为对象')
            digest(params);result['parameters']=deepcopy(params)
        return result
    field=FIELDS[kind];value=reference.get(field)
    if not isinstance(value,str):raise ValueError('证据缺少精确'+field)
    try:
        if str(UUID(value))!=value:raise ValueError()
    except ValueError:raise ValueError('证据编号不是规范UUID') from None
    return {'kind':kind,field:value}


def agenda_targets(item):
    """Keep evidence order/identity; never choose a first plausible match."""
    refs=item.get('evidence',[]) if isinstance(item,dict) else []
    if not isinstance(refs,list):return [],['证据列表格式无效']
    targets=[];errors=[];seen=set()
    for ref in refs:
        try:
            # Legacy agenda discriminator is the producer kind, not a title/UUID guess.
            if isinstance(ref,dict) and ref.get('kind')=='proposal' and item.get('kind') in ('incremental_approval','incremental_running'):
                ref={**ref,'kind':'incremental_evidence'}
            target=canonical_target(ref);key=digest(target)
            if key in seen:continue
            seen.add(key)
            identity=(target['factor_id']+'@'+target['version'] if target['kind']=='factor' else target[FIELDS[target['kind']]])
            targets.append({'label':LABELS[target['kind']]+' · '+identity,'reference':target})
        except (ValueError,TypeError) as exc:errors.append(str(exc))
    return targets,errors


def read_agenda_target(output,reference):
    """Re-read one existing source without submitting/synchronizing/creating."""
    target=canonical_target(reference);kind=target['kind']
    if kind=='watch':
        from quantlab.agent.watch_store import WatchStore
        definition,state=WatchStore(output).read(target['watch_id']);data={'definition':definition,'state':state}
    elif kind=='alpha_factory':
        from quantlab.agent.alpha_factory import AlphaFactoryService
        data=AlphaFactoryService(output).get(target['proposal_id'])
    elif kind=='memory':
        from quantlab.agent.research_memory import ResearchMemory
        data=ResearchMemory(output).get(target['memory_id'])
    elif kind=='factor':
        from quantlab.app import default_registry
        factor=default_registry().get(target['factor_id'],target['version'])
        if 'parameters' in target and factor.parameters(target['parameters'])!=target['parameters']:
            raise ValueError('引用参数与当前精确版本不匹配；不自动换默认参数')
        data=target
    elif kind=='experiment':
        from quantlab.trading.research_evidence import archive_research_reference
        data=archive_research_reference(output,target['run_id'])
    elif kind=='job':
        from quantlab.agent.catalog import ReadOnlyResearchAPI
        result=ReadOnlyResearchAPI(output).call('get_job',{'job_id':target['job_id']})
        if not result['ok']:raise ValueError(str(result.get('error')))
        data=result['data']
    elif kind in ('dsl_candidate','dsl_proposal'):
        from quantlab.agent.dsl_candidates import DslCandidateService
        service=DslCandidateService(output)
        data=service.get(target['candidate_id']) if kind=='dsl_candidate' else service.proposal(target['request_id'])
    elif kind=='incremental_evidence':
        from quantlab.agent.incremental_evidence import IncrementalEvidenceService
        data=IncrementalEvidenceService(output).get(target['proposal_id'])
    else:
        from quantlab.agent.proposal_store import ProposalStore
        data=ProposalStore(output).get(target['proposal_id'])
    return {'reference':target,'source_digest':digest(data),
            'read_only_record':data if kind in ('job','dsl_candidate') else None}


def open_agenda_target(window,checked):
    """UI-thread routing after exact-source and window-context checks."""
    target=canonical_target(checked['reference']);kind=target['kind']
    if kind=='watch':window.factor_watches(target['watch_id'])
    elif kind=='alpha_factory':
        from .alpha_factory import AlphaFactoryDialog
        window.show_dialog(AlphaFactoryDialog(window,selected_id=target['proposal_id']))
    elif kind=='memory':window.research_memory(target['memory_id'])
    elif kind=='experiment':
        window.catalog.file(target['run_id'],'experiment.json');window.open_run(target['run_id'])
    elif kind=='factor':
        from .factor_evidence import FactorEvidenceDialog
        from quantlab.storage.codec import encode
        dialog=FactorEvidenceDialog(window,{'factor_id':target['factor_id'],'version':target['version']})
        if 'parameters' in target:dialog.params.setPlainText(encode(target['parameters']))
        window.show_dialog(dialog)  # Prefill only; user still chooses Query.
    elif kind=='incremental_evidence':
        from .incremental_evidence import IncrementalEvidenceDialog
        window.show_dialog(IncrementalEvidenceDialog(window,selected_id=target['proposal_id']))
    elif kind=='dsl_proposal':
        from .dsl_candidates import DslCandidateDialog
        window.show_dialog(DslCandidateDialog(window,selected_request_id=target['request_id']))
    elif kind=='proposal':
        from .agent_proposals import ProposalDialog
        window.show_dialog(ProposalDialog(window,selected_id=target['proposal_id']))
    else:
        from PyQt6.QtWidgets import QDialog,QVBoxLayout
        from .business_view import BusinessDetails
        from .widgets import label
        dialog=QDialog(window);dialog.setWindowTitle(LABELS[kind]);dialog.resize(1000,700)
        box=QVBoxLayout(dialog);box.addWidget(label('精确来源：'+target[FIELDS[kind]],'note',True))
        box.addWidget(label('本次读取的记录快照，不自动刷新、注册、取消或重跑。任务日志不是进程在线或研究有效性证明。','note',True))
        box.addWidget(BusinessDetails(checked['read_only_record']),1);window.show_dialog(dialog)
