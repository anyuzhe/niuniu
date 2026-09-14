"""Host-side gate for live Expert Playbook snapshots; no market-data download."""
from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from quantlab.storage.codec import digest
from .frame_policy import FramePolicyStore, assess_submission
from .playbook_store import PlaybookError, PlaybookStore

FORWARD_FRAMES = ('PREP', 'AUCTION', 'R1')
DATA_READY_CLOCK = {'AUCTION': time(9, 25), 'R1': time(9, 35)}
PAYLOAD_FIELDS = {
    'definition_id','trading_day','frame','as_of','source_ids','summary','notes',
    'candidate_set','prediction',
}


def _request_id(kind, value):
    return str(uuid5(NAMESPACE_URL, f'quantlab-forward-v1:{kind}:{digest(value)}'))


def _aware_now(now_fn):
    value = now_fn()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PlaybookError('INVALID_CLOCK','前瞻 Playbook 时钟必须返回带时区时间。')
    return value

def forward_frame_status(output, trading_day, frame, now_fn):
    if frame not in FORWARD_FRAMES:
        raise PlaybookError('INVALID_ARGUMENT','前瞻冻结只支持 PREP/AUCTION/R1。')
    try:
        day = date.fromisoformat(trading_day)
    except (TypeError, ValueError):
        raise PlaybookError('INVALID_ARGUMENT','trading_day 必须为 YYYY-MM-DD。') from None
    now = _aware_now(now_fn)
    policy = FramePolicyStore(output).load()
    assessment = assess_submission(trading_day,frame,now,policy)
    tz = ZoneInfo(policy['timezone']); local = now.astimezone(tz)
    if frame == 'PREP':
        ready_at = datetime.fromisoformat(assessment['frame_open_at'])
    else:
        ready_at = datetime.combine(day,DATA_READY_CLOCK[frame],tzinfo=tz)
    close_at = datetime.fromisoformat(assessment['frame_close_at'])
    if ready_at > close_at:
        raise PlaybookError('FRAME_POLICY_CONFLICT','Frame Policy 结束时间早于数据就绪时间。')
    ready = assessment['submission_status']=='ON_TIME' and local >= ready_at
    status = 'READY' if ready else ('WAIT_DATA' if assessment['submission_status']=='ON_TIME' else assessment['submission_status'])
    return {**assessment,'forward_status':status,'data_ready_at':ready_at.isoformat(),
        'can_freeze':ready,'now_local':local.isoformat()}


def _payload(value):
    if not isinstance(value,dict) or set(value)!=PAYLOAD_FIELDS:
        raise PlaybookError('INVALID_ARGUMENT','前瞻 payload 字段必须与合同完全一致。')
    if value['frame'] not in FORWARD_FRAMES:
        raise PlaybookError('INVALID_ARGUMENT','前瞻 payload 只支持 PREP/AUCTION/R1。')
    for name in ('candidate_set','prediction'):
        if not isinstance(value[name],dict):
            raise PlaybookError('INVALID_ARGUMENT',name+' 必须是对象。')
    return value

def _parse_as_of(value):
    if not isinstance(value,str):
        raise PlaybookError('INVALID_ARGUMENT','as_of 必须为带时区 ISO 8601 时间。')
    try:
        parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:
        raise PlaybookError('INVALID_ARGUMENT','as_of 必须为带时区 ISO 8601 时间。') from None
    if parsed.tzinfo is None:
        raise PlaybookError('INVALID_ARGUMENT','as_of 必须包含时区。')
    return parsed


def _assert_live_as_of(status, as_of, now):
    ready_at = datetime.fromisoformat(status['data_ready_at'])
    local_as_of = as_of.astimezone(ready_at.tzinfo)
    local_now = now.astimezone(ready_at.tzinfo)
    if local_as_of < ready_at:
        raise PlaybookError('FORWARD_DATA_NOT_READY','as_of 早于该 Frame 的数据就绪时点。')
    if local_as_of > local_now:
        raise PlaybookError('LOOKAHEAD_BLOCKED','as_of 不能晚于当前时钟。')
    if (local_now-local_as_of).total_seconds() > 600:
        raise PlaybookError('LOOKAHEAD_BLOCKED','前瞻快照必须在数据时点后10分钟内冻结。')


def _case_content(value):
    return {'definition_id':value['definition_id'],'trading_day':value['trading_day'],
        'frame':value['frame'],'as_of':value['as_of'],'source_ids':value['source_ids'],
        'summary':value['summary'],'notes':value['notes']}

def _candidate_content(value, case_id):
    item=value['candidate_set']
    allowed={'completeness','pit_status','universe_source','generation_method','candidates','evidence_ids'}
    if set(item)!=allowed:
        raise PlaybookError('INVALID_ARGUMENT','candidate_set 字段必须与前瞻合同完全一致。')
    return {'case_id':case_id,'definition_id':value['definition_id'],
        'trading_day':value['trading_day'],'frame':value['frame'],'as_of':value['as_of'],
        **item}


def _selection_content(value, candidate_set_id):
    item=value['prediction']
    allowed={'selected_symbols','ranked_symbols','reasons','evidence_ids','notes'}
    if set(item)!=allowed:
        raise PlaybookError('INVALID_ARGUMENT','prediction 字段必须与前瞻合同完全一致。')
    return {'candidate_set_id':candidate_set_id,'kind':'SYSTEM_PREDICTION',
        'as_of':value['as_of'],**item}


def _same_request(records, request_id):
    return next((row for row in records if row.get('request_id')==request_id),None)


def _reject_other(records, expected, message):
    other=[row for row in records if row.get('request_id')!=expected]
    if other:
        raise PlaybookError('FORWARD_FRAME_ALREADY_FROZEN',message)

def freeze_forward_snapshot(output, value, now_fn=None):
    value=_payload(value);now_fn=now_fn or (lambda:datetime.now().astimezone())
    now=_aware_now(now_fn)
    status=forward_frame_status(output,value['trading_day'],value['frame'],lambda:now)
    if not status['can_freeze']:
        raise PlaybookError('FORWARD_FRAME_NOT_OPEN',
            f"{value['frame']} 当前不能冻结：{status['forward_status']}。")
    _assert_live_as_of(status,_parse_as_of(value['as_of']),now)
    store=PlaybookStore(Path(output),now_fn=lambda:now)

    case_content=_case_content(value);case_request=_request_id('case',case_content)
    existing_cases=[row for row in store.list_cases(definition_id=value['definition_id'],
        trading_day=value['trading_day'],limit=200)['records'] if row['frame']==value['frame']]
    _reject_other(existing_cases,case_request,'该 definition/day/frame 已被其他前瞻 Case 冻结。')
    resumed_case=_same_request(existing_cases,case_request) is not None
    case=store.create_case(case_request,case_content)

    candidate_content=_candidate_content(value,case['case_id'])
    candidate_request=_request_id('candidate-set',candidate_content)
    existing_sets=store.list_candidate_sets(case_id=case['case_id'],limit=10)['records']
    _reject_other(existing_sets,candidate_request,'该前瞻 Case 的 CandidateSet 已被冻结。')
    resumed_set=_same_request(existing_sets,candidate_request) is not None
    candidate=store.create_candidate_set(candidate_request,candidate_content)

    selection_content=_selection_content(value,candidate['candidate_set_id'])
    selection_request=_request_id('selection',selection_content)
    existing_predictions=store.list_selections(candidate_set_id=candidate['candidate_set_id'],
        kind='SYSTEM_PREDICTION',limit=20)['records']
    _reject_other(existing_predictions,selection_request,
        '该前瞻 CandidateSet 已存在另一条 SYSTEM_PREDICTION。')
    resumed_prediction=_same_request(existing_predictions,selection_request) is not None
    prediction=store.create_selection(selection_request,selection_content)
    return {'ok':True,'status':status,'case':case,'candidate_set':candidate,
        'prediction':prediction,'resumed':{
            'case':resumed_case,'candidate_set':resumed_set,'prediction':resumed_prediction}}


__all__=['FORWARD_FRAMES','forward_frame_status','freeze_forward_snapshot']
