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

    def qualify(self,spec):
        from quantlab.data.qualification import qualify_spec
        try:return qualify_spec(self.data_root,spec)
        except ProposalError:raise
        except (ValueError,TypeError,KeyError,OSError) as error:
            raise ProposalError('DATA_QUALIFICATION_FAILED','数据资格检查未完成：'+str(error)[:240]) from error

    def _revision_sources(self, spec):
        """Verify immediate parents in this workspace; a reference is not approval."""
        nodes = spec.get('nodes', []) if spec.get('mode') == 'campaign' else [{'node_id': '', 'spec': spec}]
        verified = []
        for node in nodes:
            source = (node['spec'].get('strategy_package') or {}).get('package', {}).get('revision_source')
            if source is None:
                continue
            from quantlab.trading.strategy_run_catalog import verify_strategy_revision_source
            try:
                receipt = verify_strategy_revision_source(self.output, source)
            except (ValueError, TypeError, KeyError, OSError) as error:
                raise ProposalError('REVISION_SOURCE_INVALID', '改版父来源缺失、损坏或已变化；未批准：' + str(error)[:200]) from error
            verified.append({'node_id': node['node_id'], **receipt})
        return verified

    def preview(self, spec):
        value = preview_experiment(spec,self.budget)
        revision_sources = self._revision_sources(value['spec'])
        if revision_sources:
            value['strategy_revision_sources'] = revision_sources
        qualification=self.qualify(value['spec'])
        if not qualification['qualified']:
            raise ProposalError('DATA_QUALIFICATION_BLOCKED','请求的数据资格级别未满足：'+', '.join(qualification.get('blockers',[])[:12]))
        value['qualification']=qualification
        value['binding'] = {'output':workspace_identity(self.output),
            'data_root':workspace_identity(self.data_root),'runtime':runtime_fingerprint()}
        return value

    def propose(self, request_id, spec):
        return self.store.create(request_id,self.preview(spec),self.budget.max_pending_proposals)

    def get(self, proposal_id):
        record=self.store.get(proposal_id);folder=self.output/'_approval_input_freezes'/proposal_id
        if folder.is_dir():
            if record['status'] not in ('approved', 'submitted'):
                return {**record, 'unapproved_input_freeze': {
                    'status': 'not_approved', 'execution_authorized': False,
                    'message': '存在未批准的冻结候选，不是有效批准回执；改版提案须拒绝旧提案后新建。'}}
            from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
            freeze=ApprovalInputFreezeStore(self.output,self.data_root)
            receipt={'format':'niuniu-approval-input-freeze-receipt-v1','freeze_id':proposal_id,
                'manifest_hash':freeze._manifest_hash(folder),'spec_digest':digest(record['plan']['spec'])}
            freeze.verify(receipt,record['plan']['spec']);record={**record,'approval_freeze':receipt}
        return record

    def _current(self, record):
        if self.preview(record['plan']['spec']) != record['plan']:
            raise ProposalError('STALE_PROPOSAL','代码、工作空间、预算或解析规则已变化；请重新生成提案。')

    def approve_and_submit(self, proposal_id, expected_digest, get_queue):
        """Host UI only. Approval freezes actual normalized input bytes before queue submission."""
        freeze_receipt=None
        with self.store.transaction() as connection:
            record = self.store.load(proposal_id,connection)
            if record['proposal_digest'] != expected_digest:
                raise ProposalError('STALE_PROPOSAL','批准必须绑定当前完整提案校验值。')
            if record['status'] not in ('pending','approved','submitted'):
                raise ProposalError('INVALID_STATE','此提案不能批准或提交。')
            freeze_store=None
            if record['status'] in ('pending','approved'):
                from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
                freeze_store=ApprovalInputFreezeStore(self.output,self.data_root)
            if record['status'] == 'pending':
                if record['plan'].get('strategy_revision_sources') and freeze_store.path(proposal_id).exists():
                    raise ProposalError('UNAPPROVED_FREEZE_REQUIRES_NEW_PROPOSAL',
                        '先前改版批准未完成，遗留输入冻结不能复用；请拒绝此待批准提案并重新生成。')
                self._current(record)
                created = datetime.fromisoformat(record['created_at'])
                if datetime.now(timezone.utc)-created > timedelta(hours=24):
                    raise ProposalError('STALE_PROPOSAL','提案已超过 24 小时，请重新生成。')
                freeze_receipt=freeze_store.capture(proposal_id,record['plan']['spec'],record['plan']['qualification'])
                if self._revision_sources(record['plan']['spec']) != record['plan'].get('strategy_revision_sources', []):
                    raise ProposalError('REVISION_SOURCE_INVALID', '输入冻结期间改版来源已变化；批准未生效。')
                connection.execute("UPDATE proposals SET status='approved',approved_at=? WHERE id=?", (now(),proposal_id))
                self.store.event(connection,proposal_id,'approval_inputs_frozen')
                self.store.event(connection,proposal_id,'approved_by_user')
            elif record['status']=='approved':
                if not freeze_store.path(proposal_id).is_dir():
                    raise ProposalError('APPROVAL_FREEZE_MISSING','旧批准记录缺少审批时实际输入冻结；请新建提案并重新批准。')
                freeze_receipt=freeze_store.capture(proposal_id,record['plan']['spec'],record['plan']['qualification'])
        # Approval and its byte freeze are durable before queue submission. The same UUID
        # recovers a lost acknowledgement without rereading mutable source data.
        with self.store.transaction() as connection:
            record = self.store.load(proposal_id,connection)
            queue = get_queue()
            if Path(queue.root).resolve()!=self.output or Path(queue.data_root).resolve()!=self.data_root:
                raise ProposalError('INVALID_WORKSPACE','提交队列与批准的工作空间不一致。')
            jobs = queue.list(); existing = next((j for j in jobs if j['job_id']==record['job_id']),None)
            if freeze_receipt is None:
                from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
                freeze_store=ApprovalInputFreezeStore(self.output,self.data_root)
                if freeze_store.path(proposal_id).is_dir():
                    freeze_receipt=freeze_store.capture(proposal_id,record['plan']['spec'],record['plan']['qualification'])
            guard = {'runtime':record['plan']['binding']['runtime'],
                'cooperative_seconds':record['plan']['budget']['cooperative_seconds'],
                'max_active_jobs':record['plan']['budget']['max_active_jobs']}
            if freeze_receipt is not None:guard['approval_freeze']=freeze_receipt
            if existing is not None:
                if existing['spec']!=record['plan']['spec'] or existing.get('execution_guard')!=guard:
                    raise ProposalError('CONFLICT','已存在任务与批准内容不一致，拒绝复用。')
                result = existing
            else:
                if record['status']=='submitted':
                    raise ProposalError('LOST_JOB','已提交任务日志缺失；拒绝自动重新运行。')
                active = sum(j['status'] in ('queued','running') for j in jobs)
                if active >= self.budget.max_active_jobs:
                    raise ProposalError('BUDGET_EXCEEDED','共享队列活动任务已达上限；批准记录保留，可稍后重试。')
                result = queue.submit(record['job_id'],record['plan']['spec'],execution_guard=guard)
            if record['status']!='submitted':
                connection.execute("UPDATE proposals SET status='submitted' WHERE id=?",(proposal_id,))
                self.store.event(connection,proposal_id,'submitted_to_shared_queue')
            updated = self.store.load(proposal_id,connection)
        evidence=[{'kind':'job','job_id':record['job_id']}]
        if freeze_receipt is not None:evidence.append({'kind':'approval_input_freeze',**freeze_receipt})
        return {'proposal':updated,'job':result,'approval_freeze':freeze_receipt,'evidence':evidence}
