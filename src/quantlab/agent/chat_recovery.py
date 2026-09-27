"""Bounded continuation hints from the existing append-only chat journal.

Historical identifiers are not current facts or permission. Recovery acquires
no queue and cannot submit/retry an experiment.
"""
from uuid import UUID

RECOVERY_TOOLS = frozenset({
    'get_research_session_grant', 'get_job', 'get_experiment',
    'get_research_memory', 'search_research_memory', 'inspect_research_evidence',
    'get_run_research_links', 'list_experiments', 'record_finding',
})
RECOVERY_PROMPT = ('请整理这个会话已经产生的研究结果。先核对已有 job/run 和研究记忆，'
                   '实验已完成就不要重跑；对原假设尚未保存的结论核对证据后补存 finding，'
                   '已有结论则读回核验，不重复保存。保存finding时hypothesis_id引用假设查询的finding_parent_id，'
                   '即根假设的record.memory_id；record.hypothesis_id=null仅表示无父假设，不是缺少ID。报告已完成、未完成和限制。'
                   '本轮禁止新建、提交、批准或重跑研究，也不创建新假设。')
_REFERENCE_IDS = {'experiment':'run_id', 'job':'job_id', 'memory':'memory_id',
                  'proposal':'proposal_id', 'research_session_grant':'grant_id'}


def _reference(value):
    if not isinstance(value, dict):
        return None
    kind = value.get('kind')
    if not isinstance(kind, str):return None
    field = _REFERENCE_IDS.get(kind)
    identifier = value.get(field) if field else None
    try:
        if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
            return None
    except ValueError:
        return None
    return {'kind':kind, field:identifier}


def recovery_snapshot(store, conversation_id, *, limit=30):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('recovery reference limit must be 1–50')
    history = store.events(conversation_id, 2000)
    events = history['events']; turns = []
    for event in events:
        payload = event.get('payload', {})
        if event.get('kind') == 'user' and payload.get('turn_id'):
            turns.append(payload['turn_id'])
    last = turns[-1] if turns else None
    terminal = next((e['payload'] for e in reversed(events)
                     if e.get('kind') == 'assistant' and e.get('payload', {}).get('turn_id') == last), {})
    state = terminal.get('status', 'interrupted' if last else 'empty')
    references = []; seen = set(); total = 0
    # Earlier IDs matter when the latest turn itself failed during recovery.
    # Deduplicate old transport echoes without altering stored events.
    for event in reversed(events):
        payload = event.get('payload', {})
        if event.get('kind') == 'tool_result':
            refs = (payload.get('result') or {}).get('evidence', [])
        elif event.get('kind') == 'assistant':
            refs = (payload.get('metadata') or {}).get('evidence', [])
        else:
            continue
        if not isinstance(refs, list):
            continue
        for value in refs:
            ref = _reference(value)
            if not ref:
                continue
            key = tuple(sorted(ref.items()))
            if key in seen:
                continue
            seen.add(key); total += 1
            if len(references) < limit:
                references.append(ref)
    return {'format':'niuniu-chat-recovery-v1', 'conversation_id':conversation_id,
            'previous_turn_id':last, 'previous_status':state,
            'needs_followup':bool(last and (state != 'completed' or
                terminal.get('metadata', {}).get('needs_followup') is True)),
            'references':references, 'omitted_references':max(0, total-len(references)),
            'omitted_events':history['omitted'],
            'incomplete':bool(history['omitted'] or total > limit),
            'policy':'Historical journal references only. Re-read actual jobs, archives and memory before claims. '
                     'Not live process status, a research conclusion, or execution permission.'}


def failure_text(message, evidence, calls):
    refs = []
    for value in evidence:
        ref = _reference(value)
        if ref and ref not in refs:
            refs.append(ref)
    identifiers = '；'.join(next(v for k, v in ref.items() if k != 'kind') for ref in refs[:8])
    return ('【本轮未完成】' + message + '\n宿主已记录 ' + str(calls) +
            ' 次工具请求；已提交研究的实际状态须重新查询，不能从助手中断推断研究失败。'
            + ('\n历史引用：' + identifiers if identifiers else '')
            + '\n可使用“整理已有结果（不重跑）”核对原任务和证据；不会自动启动新研究。')
