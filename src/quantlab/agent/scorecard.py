"""Read-only evidence scorecards for stable AI Team roles and deterministic system baselines.

No composite leaderboard is produced. Metrics stay separated by task type and only
use facts already persisted by Decision Ledger, Peer Review, Playbook and Paper stores.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import json

from quantlab.agent.agent_memory import ROLES
from quantlab.storage.codec import digest
from quantlab.trading.decision_store import DecisionStore
from quantlab.trading.paper_lifecycle import PaperLifecycleAnalytics
from quantlab.trading.playbook_store import PlaybookError,PlaybookStore

FORMAT='agent-scorecard-v1'
AGENT_ROLES=tuple(role for role in ROLES if role!='developer')
TERMINAL_REVIEW={'completed','failed','stopped','running'}


class AgentScorecardError(ValueError):
    pass


def _ratio(numerator,denominator):
    return {'numerator':int(numerator),'denominator':int(denominator),
        'value':(float(numerator)/denominator if denominator else None)}


def _sample_status(samples,minimum=3):
    if samples<=0:return 'NO_SAMPLES'
    if samples<minimum:return 'INSUFFICIENT_SAMPLES'
    return 'MEASURED'


def _pages(call,limit=200):
    offset=0;rows=[]
    while True:
        page=call(offset,limit);rows.extend(page['records'])
        next_offset=page.get('next_offset')
        if next_offset is None:return rows
        offset=next_offset
        if offset>100000:raise AgentScorecardError('分页超过安全预算。')


def _decision_evidence(row):
    return bool(row.get('research_evidence_ids') or row.get('market_snapshot_id') or row.get('rule_snapshot_id'))


def _risk_documented(row):
    return bool(row.get('risk_flags') or row.get('invalidation') or row.get('exit_condition') or row.get('reduce_condition'))


def _plan_complete(row):
    action=row.get('action')
    if action in ('DISCOVERED','WATCH','READY','REJECTED','EXPIRED'):return None
    if action=='PLAN_OPEN':return bool((row.get('buy_zone') or row.get('confirm_trigger')) and (row.get('invalidation') or row.get('exit_condition')))
    if action in ('OPEN','ADD','HOLD'):return bool((row.get('hold_reason') or row.get('ai_thesis') or row.get('machine_state')) and (row.get('invalidation') or row.get('exit_condition')))
    if action in ('REDUCE','EXIT','INVALIDATED'):return bool(row.get('exit_condition') or row.get('invalidation') or row.get('ai_thesis'))
    return None


class AgentScorecardService:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise AgentScorecardError('工作空间不存在。')

    def _decisions(self):
        store=DecisionStore(self.output)
        current=_pages(lambda offset,limit:store.list(include_superseded=False,offset=offset,limit=limit))
        history=_pages(lambda offset,limit:store.list(include_superseded=True,offset=offset,limit=limit))
        followups=defaultdict(int)
        for row in current:
            if row.get('frame') in ('D1','D2','D3_PLUS') and row.get('reference_decision_id'):
                followups[row['reference_decision_id']]+=1
        result=[]
        for role in AGENT_ROLES:
            rows=[row for row in current if row.get('role_id')==role]
            revisions=sum(1 for row in history if row.get('role_id')==role and row.get('revision_of'))
            timed=[row for row in rows if row.get('submission_status') in ('ON_TIME','EARLY','LATE','BACKFILL')]
            on_time=sum(row.get('submission_status')=='ON_TIME' for row in timed)
            off_window=sum(row.get('submission_status') in ('EARLY','LATE','BACKFILL') for row in timed)
            evidence=sum(_decision_evidence(row) for row in rows)
            model_identity=sum(bool(row.get('model_provider') and row.get('model_id') and row.get('prompt_version')) for row in rows)
            risk=sum(_risk_documented(row) for row in rows)
            plan_rows=[row for row in rows if _plan_complete(row) is not None]
            plan_complete=sum(bool(_plan_complete(row)) for row in plan_rows)
            originals=[row for row in rows if row.get('frame') in ('PREP','AUCTION','R1','R2','R3')]
            followed=sum(bool(followups.get(row['decision_id'])) for row in originals)
            result.append({'role_id':role,'task_type':'decision','sample_status':_sample_status(len(rows)),
                'samples':len(rows),'observed_models':sorted({(row.get('model_provider') or '')+':'+(row.get('model_id') or '') for row in rows if row.get('model_id')}),
                'metrics':{'on_time_rate':_ratio(on_time,len(timed)),'off_window_count':off_window,
                    'evidence_link_rate':_ratio(evidence,len(rows)),'model_identity_rate':_ratio(model_identity,len(rows)),
                    'risk_documentation_rate':_ratio(risk,len(rows)),'plan_completeness_rate':_ratio(plan_complete,len(plan_rows)),
                    'follow_up_rate':_ratio(followed,len(originals)),'revision_count':revisions},
                'not_scored':['evidence_correctness','profitability','alpha'],
                'notes':'Decision 指标只衡量已保存纪律和覆盖；不从字段齐全推断判断正确。'})
        return result,{'current_decisions':len(current),'historical_decisions':len(history)}

    def _peer_tasks(self):
        root=self.output/'_assistant'/'peer_reviews'
        if not root.exists():return [],0
        if root.is_symlink():raise AgentScorecardError('peer_reviews 目录不能是符号链接。')
        tasks=[];unreadable=0
        for path in sorted(root.glob('*.json')):
            if path.is_symlink() or path.stat().st_size>2_000_000:
                unreadable+=1;continue
            try:
                wrapped=json.loads(path.read_text(encoding='utf-8'));checksum=wrapped.pop('checksum',None)
                if checksum!=digest(wrapped):raise ValueError('checksum')
                if not isinstance(wrapped.get('spec'),dict) or not isinstance(wrapped.get('rounds'),list):raise ValueError('schema')
                tasks.append(wrapped)
            except (OSError,ValueError,TypeError,json.JSONDecodeError):unreadable+=1
            if len(tasks)>=5000:break
        return tasks,unreadable

    def _peer_rows(self,tasks):
        rows=[]
        attempted=[task for task in tasks if task.get('status') in TERMINAL_REVIEW]
        for role in ('market_scanner','skeptic','quant_researcher'):
            requested=[task for task in attempted if role in (task.get('spec') or {}).get('reviewers',[])]
            outputs=[]
            for task in requested:
                first=next((r for r in task.get('rounds',[]) if r.get('round')==1),None)
                output=next((o for o in (first or {}).get('outputs',[]) if o.get('role_id')==role),None)
                if output:outputs.append(output)
            completed=[o for o in outputs if o.get('status')=='completed']
            rows.append({'role_id':role,'task_type':'peer_review_independent','sample_status':_sample_status(len(requested)),
                'samples':len(requested),'observed_models':sorted({(o.get('provider') or '')+':'+(o.get('model') or '') for o in completed if o.get('model')}),
                'metrics':{'completion_rate':_ratio(len(completed),len(requested)),
                    'failure_count':sum(o.get('status')=='failed' for o in outputs),
                    'tool_use_rate':_ratio(sum((o.get('tool_calls') or 0)>0 for o in completed),len(completed)),
                    'explicit_evidence_rate':_ratio(sum(bool(o.get('evidence')) for o in completed),len(completed)),
                    'model_identity_rate':_ratio(sum(bool(o.get('provider') and o.get('model')) for o in completed),len(completed))},
                'not_scored':['answer_correctness','majority_vote','profitability'],
                'notes':'第一轮完成/证据引用是宿主可观察事实；文本观点正确性不由自评自动判定。'})
        synthesis=[]
        expected=[]
        for task in attempted:
            first=next((r for r in task.get('rounds',[]) if r.get('round')==1),None)
            if first and any(o.get('status')=='completed' for o in first.get('outputs',[])):expected.append(task)
            second=next((r for r in task.get('rounds',[]) if r.get('round')==2),None)
            if second:
                output=next((o for o in second.get('outputs',[]) if o.get('role_id')=='chief_researcher'),None)
                if output:synthesis.append(output)
        completed=[o for o in synthesis if o.get('status')=='completed']
        reviewer_slots=sum(len((task.get('spec') or {}).get('reviewers',[])) for task in expected)
        reviewer_completed=0
        for task in expected:
            first=next((r for r in task.get('rounds',[]) if r.get('round')==1),None)
            reviewer_completed+=sum(o.get('status')=='completed' for o in (first or {}).get('outputs',[]))
        rows.append({'role_id':'chief_researcher','task_type':'peer_review_synthesis','sample_status':_sample_status(len(expected)),
            'samples':len(expected),'observed_models':sorted({(o.get('provider') or '')+':'+(o.get('model') or '') for o in completed if o.get('model')}),
            'metrics':{'synthesis_completion_rate':_ratio(len(completed),len(expected)),
                'reviewer_input_completion_rate':_ratio(reviewer_completed,reviewer_slots),
                'tool_use_rate':_ratio(sum((o.get('tool_calls') or 0)>0 for o in completed),len(completed)),
                'explicit_evidence_rate':_ratio(sum(bool(o.get('evidence')) for o in completed),len(completed)),
                'model_identity_rate':_ratio(sum(bool(o.get('provider') and o.get('model')) for o in completed),len(completed))},
            'not_scored':['synthesis_correctness','consensus_strength','profitability'],
            'notes':'Chief 不按多数票得分；这里只记录综合是否完成及输入/证据覆盖。'})
        return rows,{'peer_review_tasks':len(tasks),'attempted_peer_reviews':len(attempted),
            'pending_peer_reviews':sum(task.get('status')=='pending' for task in tasks)}

    def _playbook_baseline(self):
        store=PlaybookStore(self.output)
        predictions=_pages(lambda offset,limit:store.list_selections(kind='SYSTEM_PREDICTION',offset=offset,limit=min(limit,2000)),limit=2000)
        full=strict=labels=ambiguous=exact=tp=pred_total=target_total=false_positive=false_negative=0;unreadable=0
        for prediction in predictions:
            try:
                candidate=store.get_candidate_set(prediction['candidate_set_id'])
                full+=candidate.get('completeness')=='FULL';strict+=candidate.get('pit_status')=='STRICT_PIT'
                observed=store.list_selections(candidate_set_id=candidate['candidate_set_id'],kind='OBSERVED_EXPERT',limit=2000)['records']
                if len(observed)!=1:
                    ambiguous+=int(len(observed)>1);continue
                labels+=1;truth=set(observed[0].get('selected_symbols') or []);pred=set(prediction.get('selected_symbols') or [])
                hits=truth&pred;tp+=len(hits);pred_total+=len(pred);target_total+=len(truth);false_positive+=len(pred-truth);false_negative+=len(truth-pred);exact+=truth==pred
            except (PlaybookError,KeyError,TypeError):unreadable+=1
        return {'task_type':'playbook_prediction','actor':'system','samples':len(predictions),
            'label_status':_sample_status(labels),'metrics':{'full_candidate_set_rate':_ratio(full,len(predictions)),
                'strict_pit_rate':_ratio(strict,len(predictions)),'no_trade_rate':_ratio(sum(not p.get('selected_symbols') for p in predictions),len(predictions)),
                'labeled_predictions':labels,'ambiguous_observed_labels':ambiguous,
                'exact_match_rate':_ratio(exact,labels),'micro_precision':_ratio(tp,pred_total),
                'micro_recall':_ratio(tp,target_total),'false_positive_count':false_positive,'false_negative_count':false_negative,'unreadable_count':unreadable},
            'not_scored':['alpha','profitability'],'notes':'只在同一 CandidateSet 恰有一个 OBSERVED_EXPERT 标签时计算选择匹配；不是 Alpha 认证。'}

    def build(self):
        stamp=self.now_fn()
        if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise AgentScorecardError('Scorecard 时钟必须带时区。')
        decision_rows,decision_meta=self._decisions();tasks,unreadable=self._peer_tasks();peer_rows,peer_meta=self._peer_rows(tasks)
        try:paper=PaperLifecycleAnalytics(self.output).build()
        except (OSError,ValueError,KeyError,TypeError,PlaybookError):paper={'unavailable':True}
        rows=decision_rows+peer_rows
        return {'format':FORMAT,'generated_at':stamp.astimezone(timezone.utc).isoformat(),'rows':rows,
            'system_baselines':{'playbook_prediction':self._playbook_baseline(),'paper_lifecycle':paper},
            'meta':{**decision_meta,**peer_meta,'unreadable_peer_reviews':unreadable},
            'policy':{'composite_score':False,'automatic_model_weighting':False,'task_type_separation':True,
                'minimum_samples_for_measured':3,'evidence_correctness_automatic_score':False,
                'profitability_is_agent_score':False,'rejected_constraint_attempts_observable':False},
            'warnings':['样本不足时保持 NO_SAMPLES/INSUFFICIENT_SAMPLES；不以多数票、字段齐全或收益替代判断正确性。',
                '宿主拦截但未持久化的约束违规尝试不可观察；Scorecard 不臆造 violation 次数。']}


__all__=['FORMAT','AgentScorecardError','AgentScorecardService']
