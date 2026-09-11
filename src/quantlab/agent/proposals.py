"""Human-approved submissions into the existing, shared research queue."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from quantlab.agent.planning import ProposalError, ResearchBudget, preview_experiment
from quantlab.agent.proposal_store import ProposalStore, now
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.codec import digest


def workspace_identity(path):
    path = Path(path).resolve()
    if not path.is_dir(): raise ProposalError('INVALID_WORKSPACE','工作空间目录不存在。')
    stat = path.stat()
    return {'path':str(path),'device':stat.st_dev,'inode':stat.st_ino}


class ProposalService:
    def __init__(self, output, data_root, *, budget=None):
        self.output = Path(output).resolve(); self.data_root = Path(data_root).resolve()
        self.budget = budget or ResearchBudget(); self.store = ProposalStore(self.output)

    def preview(self, spec):
        value = preview_experiment(spec,self.budget)
        value['binding'] = {'output':workspace_identity(self.output),
            'data_root':workspace_identity(self.data_root),'runtime':runtime_fingerprint()}
        return value

    def propose(self, request_id, spec):
        return self.store.create(request_id,self.preview(spec),self.budget.max_pending_proposals)

    def _current(self, record):
        if self.preview(record['plan']['spec']) != record['plan']:
            raise ProposalError('STALE_PROPOSAL','代码、工作空间、预算或解析规则已变化；请重新生成提案。')

    def approve_and_submit(self, proposal_id, expected_digest, get_queue):
        """Host UI only. Never register this method as a model-facing tool."""
        with self.store.transaction() as connection:
            record = self.store.load(proposal_id,connection)
            if record['proposal_digest'] != expected_digest:
                raise ProposalError('STALE_PROPOSAL','批准必须绑定当前完整提案校验值。')
            if record['status'] not in ('pending','approved','submitted'):
                raise ProposalError('INVALID_STATE','此提案不能批准或提交。')
            if record['status'] == 'pending':
                self._current(record)
                created = datetime.fromisoformat(record['created_at'])
                if datetime.now(timezone.utc)-created > timedelta(hours=24):
                    raise ProposalError('STALE_PROPOSAL','提案已超过 24 小时，请重新生成。')
                connection.execute("UPDATE proposals SET status='approved',approved_at=? WHERE id=?", (now(),proposal_id))
                self.store.event(connection,proposal_id,'approved_by_user')
        # Approval is durable before calling the queue. The same UUID recovers
        # a lost acknowledgement; it never creates a replacement research job.
        with self.store.transaction() as connection:
            record = self.store.load(proposal_id,connection)
            queue = get_queue()
            if Path(queue.root).resolve()!=self.output or Path(queue.data_root).resolve()!=self.data_root:
                raise ProposalError('INVALID_WORKSPACE','提交队列与批准的工作空间不一致。')
            jobs = queue.list(); existing = next((j for j in jobs if j['job_id']==record['job_id']),None)
            guard = {'runtime':record['plan']['binding']['runtime'],
                'cooperative_seconds':record['plan']['budget']['cooperative_seconds'],
                'max_active_jobs':record['plan']['budget']['max_active_jobs']}
            if existing is not None:
                if existing['spec']!=record['plan']['spec'] or existing.get('execution_guard')!=guard:
                    raise ProposalError('CONFLICT','已存在任务与批准内容不一致，拒绝复用。')
                result = existing
            else:
                if record['status']=='submitted':
                    raise ProposalError('LOST_JOB','已提交任务日志缺失；拒绝自动重新运行。')
                self._current(record)
                active = sum(j['status'] in ('queued','running') for j in jobs)
                if active >= self.budget.max_active_jobs:
                    raise ProposalError('BUDGET_EXCEEDED','共享队列活动任务已达上限；批准记录保留，可稍后重试。')
                result = queue.submit(record['job_id'],record['plan']['spec'],execution_guard=guard)
            if record['status']!='submitted':
                connection.execute("UPDATE proposals SET status='submitted' WHERE id=?",(proposal_id,))
                self.store.event(connection,proposal_id,'submitted_to_shared_queue')
            updated = self.store.load(proposal_id,connection)
        return {'proposal':updated,'job':result,
            'evidence':[{'kind':'job','job_id':record['job_id']}]}
