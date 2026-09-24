"""Optional data-connected host; reuses the original workbench and research core."""
from pathlib import Path
import hashlib
import json
import re
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication,QDialog
from quantlab.desktop.app import MainWindow
from quantlab.desktop.research_chat import ResearchChatDialog
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.agent.peer_review_tools import PeerReviewResearchAPI
from quantlab.data.baostock_ingest import load_import
from quantlab.data.baostock_dataset import dataset_manifest,check_dataset_file,read_dataset_bytes


class DataConnectedResearchAPI(MarketDataResearchAPI,PeerReviewResearchAPI):
    """Cooperative union of data and full daily-assistant read/propose tools."""
    def schemas(self):
        return list({tool['name']:tool for tool in super().schemas()}.values())


class DataWorkbenchReadAPI:
    """Add only missing imported-data readers; retain the canonical runtime tool chain."""
    def __init__(self, inner, output, data_root):
        from quantlab.agent.market_data_tools import TOOLS
        self.inner = inner
        self.reader = MarketDataResearchAPI(output, data_root)
        existing = {tool['name'] for tool in inner.schemas()}
        self.spec_locked = bool(getattr(inner, 'active_spec', None))
        self.extra = [] if self.spec_locked else [tool for tool in TOOLS if tool['name'] not in existing]
        self.extra_names = {tool['name'] for tool in self.extra}

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def schemas(self):
        return self.inner.schemas() + json.loads(json.dumps(self.extra, ensure_ascii=False))

    def call(self, name, arguments):
        if name in self.extra_names:
            return self.reader.call(name, arguments)
        result = self.inner.call(name, arguments)
        if name == 'get_capabilities' and result.get('ok') and not self.spec_locked:
            from quantlab.agent.archived_data_tools import _ok
            data = {**result['data'], 'tools': [tool['name'] for tool in self.schemas()],
                    'imported_market_data_available': True, 'data_download_tool': False}
            return _ok(name, data, evidence=result.get('evidence'), warnings=result.get('warnings'))
        return result


def _assert_job_input_safe(record):
    if record.get('status') in ('failed', 'cancelled', 'interrupted'):
        guard = record.get('execution_guard') or {}
        if not isinstance(guard, dict) or not isinstance(guard.get('approval_freeze'), dict):
            raise ValueError('存在可恢复但未冻结输入的旧任务；请保留旧工作空间，用独立工作空间开展新输入研究')


def _assert_no_durable_input_work(output):
    """Inspect existing task/authorization records without starting or recovering a queue."""
    from quantlab.agent.research_session_grant import grant_status, TERMINAL_JOBS
    from quantlab.agent.tracking_control_store import ControlStore
    from quantlab.agent.tracking_daemon import daemon_active
    if daemon_active(output):
        raise ValueError('跟踪守护进程仍在使用当前工作空间；请先由宿主处理，不能直接切换输入')
    grant = grant_status(output)
    if grant['enabled'] or any(job.get('status') not in TERMINAL_JOBS for job in grant['jobs']):
        raise ValueError('请先撤销有效研究会话授权并处理其未终止任务；新数据不能继承旧授权')
    controls = ControlStore(output).list()
    if controls['errors'] or any(control.get('enabled') or any(
            cycle.get('status') not in TERMINAL_JOBS | {'synced'} for cycle in control.get('cycles', []))
            for control in controls['controls']):
        raise ValueError('跟踪授权仍有效、任务未结束或回执损坏；请先核对旧授权')
    directory = Path(output) / '_jobs'
    if directory.is_symlink():
        raise ValueError('任务目录不能是符号链接')
    if not directory.exists():
        return
    count = 0
    for path in directory.iterdir():
        if path.suffix != '.json':
            continue
        count += 1
        if count > 20000 or path.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000:
            raise ValueError('任务记录不可安全核验；请先检查任务目录')
        with path.open('rb') as stream:
            payload = stream.read(4_000_001)
        if len(payload) > 4_000_000:
            raise ValueError('任务记录超出核验范围')
        record = json.loads(payload)
        if not isinstance(record, dict) or record.get('status') not in TERMINAL_JOBS:
            raise ValueError('仍有未终止或不可识别的任务，不能切换研究数据源')
        _assert_job_input_safe(record)


class DataResearchChatDialog(ResearchChatDialog):
    DEFAULT_PROFILE='research'

    def __init__(self,window):
        super().__init__(window)
        self.runtime.api=DataWorkbenchReadAPI(self.runtime.api,window.output,window.data_root)
    def receive(self,kind,value):
        super().receive(kind,value)
        if kind=='tool_result':
            for index in range(self.evidence.count()):
                item=self.evidence.item(index);ref=item.data(Qt.ItemDataRole.UserRole)
                if ref.get('kind')=='market_data':item.setText('数据批次 · '+ref['import_id'])
    def open_reference(self):
        item=self.evidence.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole).get('kind')=='market_data':
            self.window.open_baostock_data();return
        super().open_reference()


class DataConnectedWorkbench(MainWindow):
    def __init__(self,output,data_root=None):
        super().__init__(output,data_root)
        menu=self.menuBar().addMenu('Baostock 数据')
        self._archived_selection_pending = False
        menu.addAction('归档日线研究输入（预检 / 生成 / 选择）', self.open_archived_daily_dataset)
        menu.addAction('固定更新通道（跨批次接入）',self.open_baostock_series)
        menu.addAction('AI主动研究议程',self.research_agenda)
        menu.addAction('安全Alpha Factory',self.open_alpha_factory)
        menu.addAction('候选因子对照（只读）',self.open_candidate_review)
        menu.addAction('候选增量证据包',self.open_incremental_evidence)
        menu.addAction('受限DSL候选注册',self.open_dsl_candidates)
        menu.addAction('跟踪基准换版（保留旧历史）',self.open_watch_rebase)
        menu.addAction('导入、查看和选择数据集',self.open_baostock_data)
        menu.addAction('日历驱动的跟踪到期检查',self.open_readiness)
        menu.addAction('打开带数据工具的研究助手',self.research_chat)
        from .tracking_controller import TrackingController
        action=menu.addAction('受控自动跟踪与提醒',self.open_tracking_control)
        self.tracking_controller=TrackingController(self,action)
        from .notification_controller import NotificationController
        self.notification_controller=NotificationController(self,menu.addMenu("桌面通知"))
    def data_page(self):
        super().data_page()
        from .widgets import button
        self.body.insertWidget(1, button('归档日线研究输入：预检 / 生成 / 选择', self.open_archived_daily_dataset))

    def open_archived_daily_dataset(self):
        from .archived_daily_dataset import ArchivedDailyDatasetDialog
        self.show_dialog(ArchivedDailyDatasetDialog(self))

    def get_research_queue(self):
        with self.queue_lock:
            if getattr(self, '_archived_selection_pending', False):
                raise ValueError('正在核验研究输入切换，暂不接受新任务')
            return super().get_research_queue()

    def _assert_archived_switch_idle(self, keep_dialog=None):
        if self.closing or self.callbacks:
            raise ValueError('请先结束当前读取和研究，再切换输入')
        if self.queue and any(job.get('status') not in ('completed','failed','cancelled','interrupted')
                              for job in self.queue.list()):
            raise ValueError('仍有未终止研究任务，不能切换输入')
        if self.queue:
            for job in self.queue.list():
                _assert_job_input_safe(job)
        for child in self.findChildren(QDialog):
            if child is not keep_dialog and not sip.isdeleted(child) and getattr(child, 'busy', False):
                raise ValueError('仍有工作台对话正在处理任务，不能切换输入')

    def select_archived_daily_dataset(self, path, expected_dataset_id, on_complete, keep_dialog=None):
        """Host-only asynchronous revalidation; never creates a grant or research task."""
        if not isinstance(expected_dataset_id, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_dataset_id):
            raise ValueError('请先核验输入包的完整 dataset_id')
        if not callable(on_complete):
            raise ValueError('需要输入选择完成回调')
        with self.queue_lock:
            if self._archived_selection_pending:
                raise ValueError('已有研究输入正在核验')
            self._assert_archived_switch_idle(keep_dialog)
            output, old_root = self.output, self.data_root
            self._archived_selection_pending = True
        from quantlab.data.archived_daily_dataset import (
            MARKER, inspect_archived_daily_dataset, _safe_package_root, _read_bounded_regular)
        def marker_bytes():
            root = _safe_package_root(path)
            return root, _read_bounded_regular(root / MARKER, 2_000_000, MARKER)
        def package_stamp(root, payload):
            # Cheap UI-thread drift fence around the full background byte validation.
            # Provider/approval still revalidate bytes; this is not an immutable-file lease.
            from quantlab.data.archived_daily_dataset import _validate_relative, _exact_tree, _parse_symbols
            manifest = json.loads(payload)
            symbols = _parse_symbols(' '.join(manifest['request']['symbols']))
            _exact_tree(root, symbols)
            entries = manifest['files']
            if not isinstance(entries, list) or len(entries) > 24:
                raise ValueError('输入包文件清单超出范围')
            stamp = []
            for entry in entries:
                relative = _validate_relative(entry['path'])
                item = root / relative
                stat = item.stat()
                if not item.is_file() or stat.st_size != entry['bytes']:
                    raise ValueError('输入包文件在核验期间发生变化')
                stamp.append((relative, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino))
            return tuple(stamp)
        def verify():
            _assert_no_durable_input_work(output)
            root, before = marker_bytes()
            before_stamp = package_stamp(root, before)
            checked = inspect_archived_daily_dataset(path)
            after_root, after = marker_bytes()
            if root != after_root or before != after or checked['dataset_id'] != expected_dataset_id or package_stamp(after_root, after) != before_stamp:
                raise ValueError('输入包与刚才核验的身份不同，请重新核对')
            return checked, hashlib.sha256(after).hexdigest(), before_stamp
        def finished(value, error):
            if sip.isdeleted(self):
                return
            result = None
            try:
                if error:
                    raise ValueError(error)
                if self.output != output or self.data_root != old_root:
                    raise ValueError('工作空间或数据目录已经变化，原选择失效')
                if keep_dialog is not None and (sip.isdeleted(keep_dialog) or
                        getattr(keep_dialog, 'closing', False) or getattr(keep_dialog, '_closed', False)):
                    raise ValueError('输入选择窗口已关闭；不应用迟到结果')
                with self.queue_lock:
                    self._assert_archived_switch_idle(keep_dialog)
                    _assert_no_durable_input_work(output)
                    checked, expected_marker, expected_stamp = value
                    root, payload = marker_bytes()
                    if hashlib.sha256(payload).hexdigest() != expected_marker or str(root) != checked['path'] or package_stamp(root, payload) != expected_stamp:
                        raise ValueError('输入包在核验后发生变化，未切换')
                    if root != old_root:
                        for child in self.findChildren(QDialog):
                            if child is keep_dialog or sip.isdeleted(child):
                                continue
                            for name in ('confirm', 'consent'):
                                control = getattr(child, name, None)
                                if control is not None and hasattr(control, 'setChecked'):
                                    control.setChecked(False)
                            if not child.close():
                                raise ValueError('旧对话尚未关闭，未切换输入')
                        if self.queue:
                            self.queue.close(); self.queue = None
                        self.data_root = root
                        self._research_chat_dialog = None
                        self.last_records = []
                        self.epoch += 1
                    result = checked
                    self.status.setText('已人工选择归档日线输入：'+expected_dataset_id+
                        '；仅 raw/1d/research_only。后续研究仍须新提案与人工批准，未启动研究。')
            except Exception as exc:
                error = str(exc)
                self.status.setText('输入未切换：'+error)
            finally:
                self._archived_selection_pending = False
            on_complete(result, error or '')
        try:
            self.async_call(verify, finished, guarded=False)
        except Exception:
            self._archived_selection_pending = False
            raise

    def open_watch_rebase(self):
        from .watch_rebase import WatchRebaseDialog
        self.show_dialog(WatchRebaseDialog(self))
    def open_baostock_series(self):
        from .baostock_series import BaostockSeriesDialog
        self.show_dialog(BaostockSeriesDialog(self))
    def select_baostock_series(self,identifier):
        if self._archived_selection_pending:raise ValueError('正在核验归档输入，请先结束当前选择')
        from quantlab.data.baostock_series import SeriesService
        from quantlab.agent.tracking_control_store import ControlStore
        service=SeriesService(self.output);service.get(identifier);directory=service.folder(identifier).resolve()
        if self.callbacks or (self.queue and any(j['status'] in ('queued','running') for j in self.queue.list())):
            raise ValueError('请先等待当前读取和研究完成')
        if self.data_root==directory:return
        controls=ControlStore(self.output).list()
        if controls['errors'] or any(s['enabled'] or any(c['status'] in ('reserved','queued','running') for c in s['cycles']) for s in controls['controls']):
            raise ValueError('切换数据源前请撤销旧授权并处理未完成任务')
        if self.queue:self.queue.close();self.queue=None
        from .baostock_series import BaostockSeriesDialog
        for child in self.dialogs:
            if isinstance(child,QDialog) and not isinstance(child,BaostockSeriesDialog):child.close()
        self.data_root=directory;self._research_chat_dialog=None;self.last_records=[]
    def open_alpha_factory(self):
        from .alpha_factory import AlphaFactoryDialog
        self.show_dialog(AlphaFactoryDialog(self))
    def open_candidate_review(self):
        from .candidate_review import CandidateReviewDialog
        self.show_dialog(CandidateReviewDialog(self))
    def open_incremental_evidence(self):
        from .incremental_evidence import IncrementalEvidenceDialog
        self.show_dialog(IncrementalEvidenceDialog(self))
    def open_dsl_candidates(self):
        from .dsl_candidates import DslCandidateDialog
        self.show_dialog(DslCandidateDialog(self))
    def open_tracking_control(self):
        from .tracking_control import TrackingControlDialog
        self.show_dialog(TrackingControlDialog(self))
    def open_baostock_data(self):
        from .baostock_data import BaostockDataDialog
        self.show_dialog(BaostockDataDialog(self))
    def open_readiness(self):
        from .refresh_readiness import RefreshReadinessDialog
        self.show_dialog(RefreshReadinessDialog(self))
    def research_chat(self):
        dialog=getattr(self,'_research_chat_dialog',None)
        if dialog is None or sip.isdeleted(dialog) or dialog.output!=self.output or dialog.data_root!=self.data_root:
            dialog=DataResearchChatDialog(self);self._research_chat_dialog=dialog;self.show_dialog(dialog)
        else:dialog.show();dialog.raise_();dialog.activateWindow()
    def select_baostock_dataset(self,identifier):
        if self._archived_selection_pending:raise ValueError('正在核验归档输入，请先结束当前选择')
        if self.callbacks or (self.queue and any(j['status'] in ('queued','running') for j in self.queue.list())):
            raise ValueError('请先等待当前读取和研究完成，再切换数据集')
        directory,receipt=load_import(self.output,identifier);dataset=directory/'dataset'
        manifest,_=dataset_manifest(dataset)
        if receipt.get('status') not in ('completed','completed_with_errors') or not receipt.get('dataset_ready') or not manifest['ready']:raise ValueError('该批尚未具备可研究的行情')
        for relative in manifest['files']:
            read_dataset_bytes(dataset,relative,manifest)
        if self.queue:self.queue.close();self.queue=None
        from .baostock_data import BaostockDataDialog
        for child in self.dialogs:
            if isinstance(child,QDialog) and not isinstance(child,BaostockDataDialog):child.close()
        self._research_chat_dialog=None;self.data_root=dataset.resolve();self.last_records=[]
        self.status.setText('已人工选择Baostock管理数据集：'+identifier+'；原行情未移动，当前资料为回顾性口径。')


def main():
    import argparse,sys
    parser=argparse.ArgumentParser(description='原牛牛工作台＋独立Baostock数据入口')
    parser.add_argument('--output',default='artifacts');parser.add_argument('--data-root')
    args=parser.parse_args();app=QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('牛牛 · 数据接入');app.setStyle('Fusion')
    window=DataConnectedWorkbench(args.output,args.data_root);window.show();window.open_baostock_data()
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
