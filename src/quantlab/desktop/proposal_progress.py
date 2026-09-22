"""Window-local, bounded read-only tracking; never starts a worker or resumes a job."""
from pathlib import Path
from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QCheckBox

from quantlab.agent.proposal_progress import read_proposal_progress
from quantlab.agent.proposal_store import identifier
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import button, label, row

PHASES = {
    'awaiting_approval':'等待人工批准', 'rejected':'提案已拒绝',
    'approved_not_enqueued':'已批准，尚无任务入队记录', 'missing_job':'已提交，但任务记录缺失',
    'queued':'任务记录：排队中', 'running':'任务记录：运行中（未核实进程在线）',
    'cancel_requested':'已请求取消，尚未记录终止', 'completed':'任务记录：已完成',
    'failed':'任务记录：失败', 'cancelled':'任务记录：已取消', 'interrupted':'任务记录：已中断',
    'inconsistent':'记录之间不一致', 'unavailable':'当前记录不可读取',
}


class ProposalProgressDialog(QDialog):
    INTERVAL_MS = 5000
    MAX_AUTO_READS = 120

    def __init__(self, window, proposal_id, *, expected_digest=None):
        super().__init__(window)
        self.window = window
        self.output = Path(window.output)
        stat = self.output.stat()
        self._workspace_identity = (stat.st_dev, stat.st_ino)
        self.proposal_id = identifier(proposal_id)
        self.expected_digest = expected_digest
        self.busy = False
        self._closed = False
        self._generation = 0
        self.report = None
        self._auto_reads_left = 0
        self.setWindowTitle('研究任务跟踪与结果回查 · 只读')
        self.resize(1000, 760)
        box = QVBoxLayout(self)
        box.addWidget(label('固定提案：'+self.proposal_id, 'note', True))
        box.addWidget(label('提案、任务日志、冻结清单和结果分层展示。不启动、取消、恢复或重跑。'
            '记录为运行中不代表进程在线；阶段计数不是总体百分比。', 'muted', True))
        self.status = label('尚未读取', 'note', True); box.addWidget(self.status)
        self.stage = label('', 'muted', True); box.addWidget(self.stage)
        self.refresh_button = button('刷新当前提案进度', self.refresh)
        self.open_button = button('核对后打开实际结果', self.open_result, True)
        box.addWidget(row(self.refresh_button, self.open_button, button('关闭', self.reject)))
        self.auto = QCheckBox('持续查看（每5秒、最多120次；终态、错误或关闭即停止）')
        box.addWidget(self.auto)
        self.details = BusinessDetails({}); box.addWidget(self.details, 1)
        self.timer = QTimer(self); self.timer.setInterval(self.INTERVAL_MS)
        self.timer.timeout.connect(self._tick)
        self.auto.toggled.connect(self._toggle_auto)
        self._actions()
        self.refresh()

    def _context_valid(self):
        if self._closed or Path(self.window.output) != self.output or getattr(self.window, 'closing', False):return False
        try:
            stat = self.output.stat()
            return (stat.st_dev, stat.st_ino) == self._workspace_identity
        except OSError:return False

    def _actions(self):
        self.refresh_button.setEnabled(not self.busy and not self._closed)
        self.open_button.setEnabled(not self.busy and not self._closed and bool(self.report and self.report.get('can_open_result')))

    def _stop_auto(self):
        self.timer.stop()
        self.auto.setChecked(False)

    def _toggle_auto(self, checked):
        if checked and self._context_valid():
            if self.report is not None and not self.report.get('refresh_recommended'):
                self._stop_auto(); return
            self._auto_reads_left = self.MAX_AUTO_READS
            self.timer.start()
        else:
            self.timer.stop()
            if checked:self.auto.setChecked(False)

    def _tick(self):
        if self.busy:return
        if not self._context_valid() or self._auto_reads_left <= 0:
            self._stop_auto()
            if not self._context_valid():
                self.report = None; self.details.setPlainText('{}'); self.stage.setText(''); self._actions()
            if not self._closed:self.status.setText('自动查看已停止；可手动刷新，不会改变任何任务。')
            return
        self._auto_reads_left -= 1
        self.refresh()
        if self._auto_reads_left <= 0:self._stop_auto()

    def _render(self, report):
        self.report = report
        self.details.setPlainText(encode(report))
        text = PHASES.get(report['phase'], report['phase'])
        if report['incomplete']:
            text += '；回查不完整：' + '；'.join(e['code']+': '+e['message'] for e in report['errors'])
        elif report.get('submission_receipt_pending'):
            text += '；队列已有记录，提案提交回执尚未同步'
        self.status.setText(text)
        job = report.get('job') or {}
        progress = job.get('progress') or {}
        parts = ['本次读取：'+report['observed_at']]
        if job:
            parts += ['任务：'+job['job_id'], '尝试次数：'+str(job.get('attempt'))]
            if progress.get('stage'):parts.append('当前阶段：'+str(progress['stage']))
            completed, total = progress.get('completed'), progress.get('total')
            if completed is not None and total is not None:
                parts.append('阶段内计数：'+str(completed)+' / '+str(total))
            if progress.get('updated_at'):parts.append('记录更新时间：'+str(progress['updated_at']))
            if job.get('error'):parts.append('执行错误：'+str(job['error']))
        self.stage.setText('\n'.join(parts))
        if not report.get('refresh_recommended'):self._stop_auto()

    def _read(self, open_expected=None):
        if self.busy or self._closed:return
        if not self._context_valid():
            self.report = None; self._stop_auto(); self._actions()
            self.details.setPlainText('{}'); self.stage.setText('')
            self.status.setText('工作空间已变化，请从正确的工作空间重新打开。');return
        self._generation += 1; generation = self._generation
        self.busy = True; self.report = None; self._actions()
        self.status.setText('只读回查中；尚未取得本次状态。')
        self.stage.setText(''); self.details.setPlainText('{}')
        def finished(value, error):
            if sip.isdeleted(self):return
            self.busy = False
            if self._closed or generation != self._generation:return
            try:
                if not self._context_valid():raise ValueError('工作空间已变化；不应用旧读取结果')
                if error:raise ValueError(str(error))
                if not isinstance(value, dict) or value.get('proposal_id') != self.proposal_id:
                    raise ValueError('进度回执未绑定所选提案')
                proposal = value.get('proposal')
                if self.expected_digest is not None and proposal is not None and proposal.get('proposal_digest') != self.expected_digest:
                    raise ValueError('提案配置身份与打开时所选记录不同，请重新核对。')
                self._render(value)
                if open_expected is not None:
                    result = value.get('result') or {}
                    if not value.get('can_open_result') or result.get('run_id') != open_expected:
                        self.status.setText('结果已变化或不可读取；未打开旧结果，请核对本次回执。')
                    else:
                        self._stop_auto()
                        self.window.open_run(open_expected)
            except Exception as exc:
                self.report = None; self._stop_auto(); self.details.setPlainText('{}'); self.stage.setText('')
                self.status.setText('进度回查失败：'+str(exc))
            self._actions()
        try:self.window.async_call(lambda:read_proposal_progress(self.output,self.proposal_id),finished,guarded=False)
        except Exception as exc:finished(None,str(exc))

    def refresh(self):
        self._read()

    def open_result(self):
        if self.busy or not self.report or not self.report.get('can_open_result'):return
        self._read(open_expected=self.report['result']['run_id'])

    def _close(self):
        self._closed = True; self._generation += 1; self.report = None
        self.busy = False; self._stop_auto(); self._actions()

    def closeEvent(self, event):
        self._close(); event.accept()

    def reject(self):
        self._close(); super().reject()

    def done(self, result):
        self._close(); super().done(result)
