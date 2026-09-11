"""Native manual monitoring and explicit refresh-proposal workflow."""
import re
from uuid import uuid4
from PyQt6 import sip
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QComboBox,QLineEdit,QSpinBox,QDateEdit
from quantlab.agent.watchlist import WatchService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row


class FactorWatchDialog(QDialog):
    def __init__(self, window, selected_id=None):
        super().__init__(window); self.window=window; self.busy=False; self.selected=None
        self.requested_id=selected_id if isinstance(selected_id,str) else None
        self.service=WatchService(window.output,window.data_root)
        self.create_key=None; self.create_id=None; self.request_key=None; self.request_id=None
        self.setWindowTitle('因子跟踪池 · 手动刷新与历史快照'); self.resize(1100,900)
        box=QVBoxLayout(self)
        box.addWidget(label('固定规则与历史起点；新增计算先生成提案并人工批准，完成后手动同步。这里没有定时任务，也不自动交易。','note',True))
        form=QFormLayout(); box.addLayout(form)
        self.source=QComboBox(); form.addRow('已完成因子归档（新建或纳入）',self.source)
        self.name=QLineEdit('因子观察'); form.addRow('新跟踪名称',self.name)
        self.windows=QLineEdit('20 60 120'); form.addRow('观察窗口（已观察日期数）',self.windows)
        self.minimum=QSpinBox(); self.minimum.setRange(1,1000); self.minimum.setValue(20)
        form.addRow('最少有效 IC 日期',self.minimum)
        self.create_button=button('从归档创建跟踪',self.create_watch,True)
        self.reload_button=button('刷新目录',self.reload)
        box.addWidget(row(self.create_button,self.reload_button))
        self.watches=QComboBox(); box.addWidget(row(label('已保存跟踪'),self.watches))
        self.end=QDateEdit(QDate.currentDate()); self.end.setCalendarPopup(True)
        self.end.setDisplayFormat('yyyy-MM-dd')
        self.propose_button=button('生成刷新提案并打开审批',self.propose_refresh,True)
        box.addWidget(row(label('刷新研究截止日期'),self.end,self.propose_button))
        self.requests=QComboBox(); self.sync_button=button('同步已完成的刷新结果',self.sync_refresh)
        box.addWidget(row(self.requests,self.sync_button))
        self.attach_button=button('纳入上方已完成归档',self.attach)
        self.pause_button=button('暂停跟踪',self.toggle_pause)
        self.open_button=button('打开当前来源实验',self.open_source)
        box.addWidget(row(self.attach_button,self.pause_button,self.open_button))
        self.history=QComboBox(); box.addWidget(row(label('历史快照（最近20次）'),self.history))
        self.details=BusinessDetails({}); box.addWidget(self.details,1)
        self.status=label('正在读取目录…','muted',True); box.addWidget(self.status)
        self.controls=[self.source,self.name,self.windows,self.minimum,self.create_button,
            self.reload_button,self.watches,self.end,self.propose_button,self.requests,
            self.sync_button,self.attach_button,self.pause_button,self.open_button,self.history]
        self.watches.currentIndexChanged.connect(self.select_watch)
        self.history.currentIndexChanged.connect(self.select_history)
        self.shown_run_id=None; self.reload(self.requested_id)
    def work(self, fn, done):
        if self.busy: return
        self.busy=True
        for c in self.controls: c.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self): return
            self.busy=False
            for c in self.controls: c.setEnabled(True)
            if error: self.status.setText('未完成：'+error)
            else: done(value)
        self.window.async_call(fn,finished,guarded=False)
    def reload(self, selected_id=None):
        selected_id=selected_id if isinstance(selected_id,str) else self.watches.currentData()
        old_source=self.source.currentData()
        def render(data):
            sources,watches=data
            self.source.clear()
            for r in sources['runs']: self.source.addItem(r['run_id'][:8]+' · '+r['question'],r['run_id'])
            if old_source: self.source.setCurrentIndex(self.source.findData(old_source))
            self.watches.blockSignals(True); self.watches.clear()
            for r in watches['watches']: self.watches.addItem(('启用' if r['active'] else '暂停')+' · '+r['name'],r['watch_id'])
            if selected_id: self.watches.setCurrentIndex(self.watches.findData(selected_id))
            self.watches.blockSignals(False)
            self.status.setText(f"已载入 {len(watches['watches'])} 个跟踪；无法读取 {watches['unreadable']} 项。")
            self.select_watch()
        self.work(lambda:(self.window.catalog.list(status='completed',kind='factor',limit=10000),self.service.store.list()),render)
    def select_watch(self):
        watch_id=self.watches.currentData(); self.selected=None; self.shown_run_id=None
        if not watch_id: self.details.setPlainText('{}'); return
        def render(data):
            if self.watches.currentData()!=watch_id: return
            self.selected=data; self.details.setPlainText(encode(data))
            self.pause_button.setText('暂停跟踪' if data['active'] else '重新启用跟踪')
            self.requests.clear()
            for r in data['refresh_requests']: self.requests.addItem(r['end']+' · '+r['proposal_id'][:8],r['proposal_id'])
            if self.requests.count(): self.requests.setCurrentIndex(self.requests.count()-1)
            self.history.blockSignals(True); self.history.clear()
            for r in data['history']: self.history.addItem(r['as_of']+' · '+r['change'],r['snapshot_id'])
            if self.history.count(): self.history.setCurrentIndex(self.history.count()-1)
            self.history.blockSignals(False)
            self.shown_run_id=data['latest']['source_run_id'] if data['latest'] else None
            self.status.setText('已保存 '+str(data['snapshot_count'])+' 个快照；当前来源：'+data['source_integrity']+'。未运行定时任务。')
        self.work(lambda:self.service.get(watch_id),render)
    def select_history(self):
        watch_id=self.watches.currentData(); key=self.history.currentData()
        if not watch_id or not key: return
        def show(value):
            if self.watches.currentData()!=watch_id or self.history.currentData()!=key: return
            self.details.setPlainText(encode(value)); self.shown_run_id=value['source_run_id']
            self.status.setText('历史冻结快照；当前原始来源可通过“打开当前来源实验”核对。')
        self.work(lambda:self.service.store.snapshot(watch_id,key),show)
    def create_watch(self):
        if self.busy: return
        try: windows=[int(x) for x in re.split(r'[\s,，]+',self.windows.text().strip()) if x]
        except ValueError: self.status.setText('窗口须为整数。'); return
        name=self.name.text(); run_id=self.source.currentData(); minimum=self.minimum.value()
        key=(name,run_id,tuple(windows),minimum)
        if key!=self.create_key: self.create_key=key; self.create_id=str(uuid4())
        identifier=self.create_id
        self.work(lambda:self.service.create(name,run_id,windows=windows,min_dates=minimum,watch_id=identifier),
                  lambda result:self.reload(result['watch_id']))
    def attach(self):
        watch_id=self.watches.currentData(); run_id=self.source.currentData()
        if not watch_id or not run_id: self.status.setText('请选择跟踪和已完成归档。'); return
        self.work(lambda:self.service.observe(watch_id,run_id),lambda _:self.select_watch())
    def propose_refresh(self):
        watch_id=self.watches.currentData(); end=self.end.date().toString('yyyy-MM-dd')
        if not watch_id: self.status.setText('请先选择跟踪。'); return
        key=(watch_id,end)
        if key!=self.request_key: self.request_key=key; self.request_id=str(uuid4())
        request_id=self.request_id
        def show(proposal):
            from .agent_proposals import ProposalDialog
            self.window.show_dialog(ProposalDialog(self.window,selected_id=proposal['proposal_id']))
            self.select_watch()
        self.work(lambda:self.service.propose_refresh(watch_id,end,request_id),show)
    def sync_refresh(self):
        watch_id=self.watches.currentData(); proposal_id=self.requests.currentData()
        if not watch_id or not proposal_id: self.status.setText('请选择已经批准并完成的刷新提案。'); return
        self.work(lambda:self.service.sync_refresh(watch_id,proposal_id),lambda _:self.select_watch())
    def toggle_pause(self):
        if not self.selected: return
        watch_id=self.watches.currentData(); active=not self.selected['active']
        self.work(lambda:self.service.store.set_active(watch_id,active),lambda _:self.select_watch())
    def open_source(self):
        if self.shown_run_id:
            self.window.catalog.file(self.shown_run_id,'experiment.json')
            self.window.open_run(self.shown_run_id)
