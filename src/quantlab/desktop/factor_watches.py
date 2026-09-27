"""Native, explicit Watch archive selection, snapshot reading, and manual controls."""
import re
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from PyQt6 import sip
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QSpinBox, QDoubleSpinBox, QDateEdit, QTabWidget, QPlainTextEdit, QWidget, QTableWidgetItem)

from quantlab.agent.watchlist import WatchService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label, button, row, table, fmt
from .watch_snapshot_view import snapshot_projection, snapshot_source_label, maturity_rows, sequential_rows, sequential_status_label


class FactorWatchDialog(QDialog):
    def __init__(self, window, selected_id=None):
        super().__init__(window)
        self.window = window
        self.output = Path(window.output).resolve()
        self.data_root = Path(window.data_root).resolve() if window.data_root else None
        self.epoch = getattr(window, 'epoch', None)
        self.workspace_identity = self._identity(self.output)
        self.data_identity = self._identity(self.data_root)
        self.closed = False
        self.generation = 0
        self.busy = False
        self.selected = None
        self.snapshot_result = None
        self.shown_run_id = None
        self.requested_id = selected_id if isinstance(selected_id, str) else None
        self.service = WatchService(window.output, window.data_root)
        self.create_key = self.create_id = self.request_key = self.request_id = None
        self.setWindowTitle('因子跟踪池 · 手动刷新与历史快照')
        self.resize(1150, 900)
        box = QVBoxLayout(self)
        box.addWidget(label('固定规则与历史起点；新计算先生成提案并人工批准，完成后手动同步。这里没有定时任务，也不自动交易。', 'note', True))
        self.watches = QComboBox(); box.addWidget(row(label('已保存跟踪'), self.watches))
        self.history = QComboBox(); box.addWidget(row(label('快照历史（最近20次）'), self.history))
        self.snapshot_heading = label('尚未选择快照。', 'muted', True); box.addWidget(self.snapshot_heading)
        self.tabs = QTabWidget(); box.addWidget(self.tabs, 1)
        setup = QWidget()
        setup_box = QVBoxLayout(setup); form = QFormLayout(); setup_box.addLayout(form)
        self.source = QComboBox(); self.source.setAccessibleName('显式选择的已完成因子归档')
        self.pick_button = button('选择已有归档…', self.pick_source, True)
        form.addRow('已明确选择的归档', row(self.source, self.pick_button))
        self.name = QLineEdit('因子观察'); form.addRow('新跟踪名称', self.name)
        self.windows = QLineEdit('20 60 120'); form.addRow('观察窗口（已观察日期数）', self.windows)
        self.minimum = QSpinBox(); self.minimum.setRange(1, 1000); self.minimum.setValue(20)
        form.addRow('最少有效 IC 日期', self.minimum)
        self.seq_alpha = QDoubleSpinBox(); self.seq_alpha.setRange(.001, .2); self.seq_alpha.setDecimals(3); self.seq_alpha.setSingleStep(.005); self.seq_alpha.setValue(.05)
        form.addRow('序贯 family alpha', self.seq_alpha)
        self.seq_effect = QDoubleSpinBox(); self.seq_effect.setRange(0, .5); self.seq_effect.setDecimals(3); self.seq_effect.setSingleStep(.005); self.seq_effect.setValue(.02)
        form.addRow('最小 Rank IC 衰减幅度', self.seq_effect)
        self.seq_dates = QSpinBox(); self.seq_dates.setRange(1, 1000); self.seq_dates.setValue(10)
        form.addRow('最少新增成熟日期', self.seq_dates)
        self.seq_block = QSpinBox(); self.seq_block.setRange(1, 20); self.seq_block.setValue(5)
        form.addRow('序贯非重叠Block交易日', self.seq_block)
        self.create_button = button('从归档创建跟踪', self.create_watch, True)
        self.reload_button = button('刷新跟踪目录', self.reload)
        setup_box.addWidget(row(self.create_button, self.reload_button)); setup_box.addStretch(1)
        self.tabs.addTab(setup, '创建设置')

        sample = QWidget(); sample_box = QVBoxLayout(sample)
        self.maturity_table = table(['窗口 / 持有期','已成熟样本','待成熟样本','有效IC日期','样本状态','Rank IC','相对基线变化'], [])
        sample_box.addWidget(self.maturity_table, 1)
        self.sequential_heading = label('尚无序贯快照。', 'muted', True); sample_box.addWidget(self.sequential_heading)
        self.sequential_table = table(['持有期','保存的序贯状态','新增成熟日期','完整块 / 尾部日期','当前 e / 最大 e','固定证据阈值'], [])
        sample_box.addWidget(self.sequential_table, 1)
        sample_box.addWidget(label('以上仅展示已保存指标，不计算新信号。样本不足不是因子失效，未越阈值不证明没有衰减，越界也不自动停用因子。', 'note', True))
        self.sample_details = BusinessDetails({}); sample_box.addWidget(self.sample_details, 1)
        self.tabs.addTab(sample, '成熟样本与序贯摘要')
        self.raw_details = QPlainTextEdit(); self.raw_details.setReadOnly(True)
        self.tabs.addTab(self.raw_details, '原始快照 JSON')

        task = QWidget(); task_box = QVBoxLayout(task)
        self.end = QDateEdit(QDate.currentDate()); self.end.setCalendarPopup(True); self.end.setDisplayFormat('yyyy-MM-dd')
        self.propose_button = button('生成刷新提案并打开审批', self.propose_refresh, True)
        task_box.addWidget(row(label('刷新研究截止日期'), self.end, self.propose_button))
        self.requests = QComboBox(); self.sync_button = button('同步已完成的刷新结果', self.sync_refresh)
        self.progress_button = button('查看刷新任务进度（只读）', self.open_progress)
        task_box.addWidget(row(self.requests, self.sync_button, self.progress_button))
        self.attach_button = button('纳入上方已完成归档', self.attach)
        self.pause_button = button('暂停跟踪', self.toggle_pause)
        self.open_button = button('打开所选快照来源实验', self.open_source)
        task_box.addWidget(row(self.attach_button, self.pause_button, self.open_button))
        task_box.addWidget(label('历史详情通过精确 snapshot_id 重读；历史来源完整性仅针对所选快照。样本不足不表示因子失败。', 'muted', True))
        self.tabs.addTab(task, '刷新任务与历史')
        self.status = label('正在读取已保存跟踪…', 'muted', True); box.addWidget(self.status)
        self.controls = [self.source, self.pick_button, self.name, self.windows, self.minimum, self.seq_alpha,
            self.seq_effect, self.seq_dates, self.seq_block, self.create_button, self.reload_button,
            self.watches, self.end, self.propose_button, self.requests, self.sync_button,
            self.progress_button, self.attach_button, self.pause_button, self.open_button,
            self.history]
        self.edit_controls = [self.source,self.name,self.windows,self.minimum,self.seq_alpha,self.seq_effect,
            self.seq_dates,self.seq_block,self.watches,self.end,self.requests,self.history]
        self.watches.currentIndexChanged.connect(self.select_watch)
        self.history.currentIndexChanged.connect(self.select_history)
        self.source.currentIndexChanged.connect(self._actions)
        self.requests.currentIndexChanged.connect(self._actions)
        self.finished.connect(lambda *_: self._mark_closed())
        self.reload(self.requested_id)
        self._actions()

    @staticmethod
    def _identity(path):
        if path is None: return None
        try:
            stat = Path(path).stat()
            return stat.st_dev, stat.st_ino
        except OSError: return None

    def _valid_context(self):
        return (not self.closed and not sip.isdeleted(self) and not sip.isdeleted(self.window)
            and not getattr(self.window, 'closing', False) and self.output == Path(self.window.output).resolve()
            and self.data_root == (Path(self.window.data_root).resolve() if self.window.data_root else None)
            and self.epoch == getattr(self.window, 'epoch', None)
            and self.workspace_identity is not None and self.workspace_identity == self._identity(self.output)
            and self.data_identity == self._identity(self.data_root))

    def _actions(self, *_):
        valid = self._valid_context(); idle = valid and not self.busy
        for control in self.edit_controls: control.setEnabled(idle)
        active = bool(self.selected and self.selected.get('active'))
        self.pick_button.setEnabled(idle); self.reload_button.setEnabled(idle)
        self.create_button.setEnabled(idle and self.source.currentData() is not None)
        self.propose_button.setEnabled(idle and self.selected is not None and self.selected.get('active', False))
        self.attach_button.setEnabled(idle and active and self.source.currentData() is not None)
        self.pause_button.setEnabled(idle and self.selected is not None)
        self.sync_button.setEnabled(idle and active and self.requests.currentData() is not None)
        self.progress_button.setEnabled(idle and self.selected is not None and self.requests.currentData() is not None)
        self.open_button.setEnabled(idle and self.shown_run_id is not None and
            self.snapshot_result is not None and self.snapshot_result.get('source_integrity')=='verified')

    def _clear_details(self):
        self.snapshot_result = None; self.shown_run_id = None
        self.sample_details.setPlainText('{}'); self.raw_details.clear()
        self.maturity_table.setRowCount(0); self.sequential_table.setRowCount(0)
        self.snapshot_heading.setText('尚未核对所选快照。'); self.sequential_heading.setText('尚无序贯快照。')
        self._actions()

    def _clear_selection(self):
        self.generation += 1; self.selected = None
        for control in (self.requests,self.history):
            control.blockSignals(True);control.clear();control.blockSignals(False)
        self._clear_details()

    def work(self, fn, done, *, generation=None):
        if self.busy or not self._valid_context():
            self.status.setText('工作空间、数据根或窗口已变化；拒绝操作。'); return
        self.busy = True; self._actions()
        if generation is None:generation=self.generation
        def guarded_work():
            if not self._valid_context(): raise ValueError('工作空间/数据根身份在任务开始前已变化')
            if generation!=self.generation:raise ValueError('选择在任务开始前已变化；未执行旧操作')
            return fn()
        def finished(value, error):
            if sip.isdeleted(self): return
            self.busy = False
            if self.closed: return
            if not self._valid_context():
                self._clear_selection(); self.status.setText('工作空间/数据根已变化；丢弃迟到结果。')
            elif generation is not None and generation != self.generation:
                self._actions()
            elif error:
                self._clear_selection(); self.status.setText('未完成：' + str(error))
            else:
                try: done(value)
                except Exception as exc:
                    self._clear_selection(); self.status.setText('快照显示失败：'+type(exc).__name__+': '+str(exc))
            self._actions()
        try: self.window.async_call(guarded_work, finished, guarded=False)
        except Exception as exc: finished(None, str(exc))

    def pick_source(self):
        if self.busy or not self._valid_context(): return
        from .research_picker import ArchivePickerDialog
        generation = self.generation
        picker = ArchivePickerDialog(self.window, kind='factor', title='明确选择 Watch 来源归档')
        def finished(*_):
            if self.busy or not self._valid_context() or generation!=self.generation:return
            if picker.result_reference is not None:self.select_source(picker.result_reference)
        picker.finished.connect(finished)
        self.window.show_dialog(picker)

    @staticmethod
    def _verify_archive(output, expected):
        from quantlab.trading.research_evidence import archive_research_reference
        if not isinstance(expected,dict) or expected.get('kind')!='factor' or expected.get('status')!='completed':
            raise ValueError('必须明确选择已完成的因子归档')
        source = expected.get('source') or {}; run_id = source.get('run_id')
        current = archive_research_reference(output, run_id)
        now_source = current.get('source') or {}
        if (now_source.get('run_id') != run_id or now_source.get('fingerprint') != source.get('fingerprint')
                or current.get('kind') != expected.get('kind') or current.get('status') != 'completed'):
            raise ValueError('明确选择的归档指纹、ID、kind或status已变化；不会自动改选其他来源')
        return run_id

    def reload(self, selected_id=None):
        if self.busy or not self._valid_context():return
        selected_id = selected_id if isinstance(selected_id, str) else self.watches.currentData()
        self._clear_selection(); generation = self.generation
        def render(watches):
            self.watches.blockSignals(True); self.watches.clear()
            for r in watches['watches']:
                self.watches.addItem(('启用' if r['active'] else '暂停') + ' · ' + r['name'], r['watch_id'])
            if selected_id: self.watches.setCurrentIndex(self.watches.findData(selected_id))
            self.watches.blockSignals(False)
            self.status.setText(f"已载入 {len(watches['watches'])} 个跟踪；无法读取 {watches['unreadable']} 项。来源归档尚未扫描。")
            self.select_watch()
        self.work(lambda: self.service.store.list(), render, generation=generation)

    def select_watch(self, *_):
        watch_id = self.watches.currentData(); self.generation += 1; gen = self.generation
        self.selected = None; self._clear_details()
        for control in (self.requests,self.history):
            control.blockSignals(True);control.clear();control.blockSignals(False)
        if not watch_id:
            self.status.setText('请选择已保存的 Watch。'); return
        self.status.setText('正在读取所选 Watch…')
        def render(data):
            if self.watches.currentData() != watch_id: return
            self.selected = data
            self.pause_button.setText('暂停跟踪' if data['active'] else '重新启用跟踪')
            self.requests.blockSignals(True);self.history.blockSignals(True)
            try:
                for r in data['refresh_requests']:
                    self.requests.addItem(r['end'] + ' · ' + r['proposal_id'][:8], (r['proposal_id'], r['job_id']))
                if self.requests.count():self.requests.setCurrentIndex(self.requests.count()-1)
                if data.get('latest'):self.history.addItem('最新快照 · '+data['latest']['preview']['as_of'],data['latest']['snapshot_id'])
                for r in data.get('history', []):
                    if not data.get('latest') or r['snapshot_id'] != data['latest']['snapshot_id']:
                        self.history.addItem(r['as_of'] + ' · ' + r['change'], r['snapshot_id'])
                if self.history.count():self.history.setCurrentIndex(0)
            finally:
                self.requests.blockSignals(False);self.history.blockSignals(False)
            self.status.setText(f"已保存 {data['snapshot_count']} 个快照，本页省略历史 {data.get('history_omitted',0)} 项、刷新请求 {data.get('refresh_requests_omitted',0)} 项；未运行新研究。")
            if self.history.count(): self.select_history()
        self.work(lambda: self.service.get(watch_id), render, generation=gen)

    def select_history(self, *_):
        watch_id = self.watches.currentData(); snapshot_id = self.history.currentData()
        self.generation += 1; gen = self.generation; self._clear_details()
        if not watch_id or not snapshot_id: return
        self.status.setText('正在按精确 snapshot_id 核对所选快照…')
        def render(result):
            if self.watches.currentData() != watch_id or self.history.currentData() != snapshot_id: return
            if result.get('watch_id') != watch_id or result.get('snapshot_id') != snapshot_id:
                raise ValueError('快照回执与所选 watch/snapshot 不匹配')
            self.snapshot_result = result; snapshot = result['snapshot']
            self.shown_run_id = snapshot.get('source_run_id')
            self.sample_details.setPlainText(encode(snapshot_projection(snapshot)))
            self._render_table(self.maturity_table,maturity_rows(snapshot))
            self._render_table(self.sequential_table,sequential_rows(snapshot))
            self.sequential_heading.setText('保存的序贯状态：'+sequential_status_label((snapshot.get('sequential_monitor') or {}).get('status')))
            self.raw_details.setPlainText(encode(snapshot))
            latest = '当前最新' if result.get('is_latest') else '历史冻结快照'
            omitted=(self.selected or {}).get('history_omitted',0)
            self.snapshot_heading.setText(latest+' · '+str(snapshot['preview'].get('as_of'))+' · '+snapshot_source_label(result)+
                ' 历史目录省略 '+str(omitted)+' 项。')
            position = result.get('snapshot_position'); count = result.get('snapshot_count')
            self.status.setText(f"{latest} · snapshot {snapshot_id} · source_run {self.shown_run_id} · "
                f"所选快照来源：{result.get('source_integrity')}。{snapshot_source_label(result)} "
                f"序号 {position}/{count}；未计算指标，claim_verified=false。")
        self.work(lambda: self.service.inspect_snapshot(watch_id, snapshot_id), render, generation=gen)

    @staticmethod
    def _render_table(widget, rows):
        widget.setRowCount(len(rows))
        for i,values in enumerate(rows):
            for j,value in enumerate(values):widget.setItem(i,j,QTableWidgetItem(fmt(value)))

    def select_source(self, reference):
        if self.busy or not self._valid_context():return
        if not isinstance(reference,dict) or reference.get('kind')!='factor' or reference.get('status')!='completed':
            self.status.setText('只能明确选择已完成因子归档。');return
        source=reference.get('source') or {};run_id=source.get('run_id')
        if not isinstance(run_id,str) or not isinstance(source.get('fingerprint'),dict):
            self.status.setText('归档缺少身份或指纹；未采用。');return
        idx=self.source.findData(run_id)
        if idx<0 and self.source.count()>=20:
            self.status.setText('本窗口已选择20个来源，请重新打开窗口后选择；未自动移除旧来源。');return
        if idx<0:
            self.source.addItem(run_id[:8]+' · '+str(reference.get('question') or '已选归档'),run_id)
            idx=self.source.count()-1
        self.source.setItemData(idx,deepcopy(reference),Qt.ItemDataRole.UserRole+1);self.source.setCurrentIndex(idx)
        self.status.setText('已显式选中 '+run_id+'；创建或纳入前将重核来源，未运行研究。');self._actions()

    def _selected_reference(self):
        run_id = self.source.currentData()
        ref=self.source.itemData(self.source.currentIndex(),Qt.ItemDataRole.UserRole+1) if run_id else None
        if not isinstance(ref,dict) or (ref.get('source') or {}).get('run_id')!=run_id:return None
        return deepcopy(ref)

    def create_watch(self):
        if self.busy:return
        try: windows=[int(x) for x in re.split(r'[\s,，]+', self.windows.text().strip()) if x]
        except ValueError:self.status.setText('窗口须为整数。'); return
        reference=self._selected_reference()
        if not reference:self.status.setText('请先通过“选择已有归档”明确选择来源。'); return
        run_id=self.source.currentData(); name=self.name.text(); minimum=self.minimum.value()
        alpha=self.seq_alpha.value(); effect=self.seq_effect.value(); new_dates=self.seq_dates.value(); block=self.seq_block.value()
        key=(name,run_id,tuple(windows),minimum,alpha,effect,new_dates,block)
        if key!=self.create_key:self.create_key=key;self.create_id=str(uuid4())
        identifier=self.create_id
        def work():
            self._verify_archive(self.output,reference)
            return self.service.create(name,run_id,windows=windows,min_dates=minimum,watch_id=identifier,
                sequential_alpha=alpha,sequential_min_effect=effect,sequential_min_new_dates=new_dates,sequential_block_sessions=block)
        self.work(work,lambda result:self.reload(result['watch_id']))

    def attach(self):
        watch_id=self.watches.currentData(); reference=self._selected_reference()
        if not watch_id or not reference or not self.selected or not self.selected.get('active'):
            self.status.setText('请选择启用中的跟踪并通过归档选择器明确选择已完成来源。');return
        run_id=self.source.currentData()
        def work():
            self._verify_archive(self.output,reference)
            return self.service.observe(watch_id,run_id)
        self.work(work,lambda _:self.select_watch())

    def propose_refresh(self):
        watch_id=self.watches.currentData(); end=self.end.date().toString('yyyy-MM-dd')
        if not watch_id or not self.selected or not self.selected.get('active'):
            self.status.setText('请先选择启用中的跟踪。');return
        key=(watch_id,end)
        if key!=self.request_key:self.request_key=key;self.request_id=str(uuid4())
        request_id=self.request_id
        def show(proposal):
            from .agent_proposals import ProposalDialog
            self.window.show_dialog(ProposalDialog(self.window,selected_id=proposal['proposal_id']))
            self.select_watch()
        self.work(lambda:self.service.propose_refresh(watch_id,end,request_id),show)

    def _selected_request(self):
        value=self.requests.currentData()
        return tuple(value) if isinstance(value,(tuple,list)) and len(value)==2 and all(isinstance(v,str) for v in value) else None

    def sync_refresh(self):
        watch_id=self.watches.currentData(); request=self._selected_request()
        if not watch_id or not request or not self.selected or not self.selected.get('active'):
            self.status.setText('请选择启用中的Watch及属于它的刷新提案。');return
        proposal_id,job_id=request
        self.work(lambda:self.service.sync_refresh(watch_id,proposal_id),lambda _:self.select_watch())

    def open_progress(self):
        watch_id=self.watches.currentData(); request=self._selected_request()
        if not watch_id or not request or not self._valid_context():return
        proposal_id,job_id=request
        # Re-read membership immediately before opening; never infer association from a job alone.
        self.generation += 1; gen=self.generation
        self.work(lambda:self.service.get(watch_id),lambda data:self._open_verified_progress(data,watch_id,proposal_id,job_id),generation=gen)

    def _open_verified_progress(self,data,watch_id,proposal_id,job_id):
        if not self._valid_context() or self.watches.currentData()!=watch_id:return
        if self._selected_request()!=(proposal_id,job_id):return
        request=next((r for r in data.get('refresh_requests',[]) if r.get('proposal_id')==proposal_id and r.get('job_id')==job_id),None)
        if request is None:
            self.status.setText('所选提案/任务不再属于此Watch刷新请求；拒绝打开。');return
        from .proposal_progress import ProposalProgressDialog
        class _WatchProgressDialog(ProposalProgressDialog):
            def __init__(monitor, host, pid):
                monitor._watch_output = self.output
                monitor._watch_data_root = self.data_root
                monitor._watch_epoch = self.epoch
                monitor._watch_output_identity = self.workspace_identity
                monitor._watch_data_identity = self.data_identity
                super().__init__(host, pid)
            def _context_valid(monitor):
                return (super(_WatchProgressDialog, monitor)._context_valid()
                    and monitor._watch_output == Path(monitor.window.output).resolve()
                    and monitor._watch_data_root == (Path(monitor.window.data_root).resolve() if monitor.window.data_root else None)
                    and monitor._watch_epoch == getattr(monitor.window, 'epoch', None)
                    and monitor._watch_output_identity == FactorWatchDialog._identity(monitor._watch_output)
                    and monitor._watch_data_identity == FactorWatchDialog._identity(monitor._watch_data_root))
        dialog=_WatchProgressDialog(self.window,proposal_id)
        self.window.show_dialog(dialog)
        self.status.setText('只读查看原提案任务记录；running日志不代表进程在线，不会启动或重跑。')

    def toggle_pause(self):
        if not self.selected:return
        watch_id=self.watches.currentData(); active=not self.selected['active']; expected=self.selected.get('state_digest')
        if not expected:self.status.setText('Watch状态缺少state_digest；拒绝更改。');return
        self.work(lambda:self.service.store.set_active(watch_id,active,expected_state_digest=expected),lambda _:self.select_watch())

    def open_source(self):
        selected=self.snapshot_result
        if not selected or self.busy or not self._valid_context() or selected.get('source_integrity')!='verified':return
        watch_id=selected['watch_id'];snapshot_id=selected['snapshot_id'];expected=selected['view_digest']
        generation=self.generation
        def show(view):
            if view['source_integrity']!='verified':raise ValueError('所选快照来源已变化或不可读')
            run_id=view['snapshot']['source_run_id']
            self.window.catalog.file(run_id,'experiment.json');self.window.open_run(run_id)
        self.work(lambda:self.service.inspect_snapshot(watch_id,snapshot_id,expected_digest=expected),show,generation=generation)

    def _mark_closed(self):
        self.closed=True;self.generation+=1;self._clear_selection()

    def closeEvent(self,event):
        self._mark_closed();super().closeEvent(event)

    def reject(self):
        self._mark_closed();super().reject()
