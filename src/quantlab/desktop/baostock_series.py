"""Explicit batch rollover and stable data-directory selection; no download action."""
from uuid import uuid4
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QCheckBox, QPushButton
from quantlab.data.baostock_series import SeriesService
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.storage.codec import digest, encode
from .business_view import BusinessDetails
from .widgets import label, button, row


class BaostockSeriesDialog(QDialog):
    def __init__(self, window):
        super().__init__(window);self.window=window;self.output=window.output
        self.service=SeriesService(self.output);self.busy=False;self.plan=None
        self.create_id=str(uuid4());self.create_key=None
        self.setWindowTitle('Baostock 固定更新通道');self.resize(1050,820)
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.batches=QComboBox();self.channels=QComboBox();self.name=QLineEdit('日线更新通道')
        for title,control in [('已下载的新批次',self.batches),('新通道名称',self.name),('已有更新通道',self.channels)]:form.addRow(title,control)
        box.addWidget(label('同证券、同历史起点，完整历史批次接替。旧批次不覆盖；缺日阻止接入。仅改变明确选中的通道，不自动下载或授予研究权限。','note',True))
        self.confirm=QCheckBox('我已核对所选批次与完整预览，确认创建或更新通道。')
        self.revisions=QCheckBox('另行确认预览列出的历史价格／估值修订，保留旧批次。')
        box.addWidget(self.confirm);box.addWidget(self.revisions)
        box.addWidget(row(button('刷新列表',self.reload),button('从批次创建通道',self.create)))
        box.addWidget(row(button('核对接入计划',self.preview),button('确认接入批次',self.accept_plan,True)))
        box.addWidget(row(button('选择通道为研究数据源',self.select),button('查看发布历史',self.history)))
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('未启用任何下载或研究授权。','muted',True);box.addWidget(self.status)
        self.batches.currentIndexChanged.connect(self.dirty);self.channels.currentIndexChanged.connect(self.dirty)
        self.name.textChanged.connect(self.dirty);self.reload()
    def dirty(self,*_):
        self.plan=None;self.confirm.setChecked(False);self.revisions.setChecked(False)
    def work(self,fn,done):
        if self.busy:return
        self.busy=True;controls=[*self.findChildren(QPushButton),self.batches,self.channels,self.name,self.confirm,self.revisions]
        for c in controls:c.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for c in controls:c.setEnabled(True)
            if self.window.output!=self.output:self.dirty();self.status.setText('工作空间已变化，请重新打开窗口。');return
            if error:self.status.setText('未完成：'+error)
            else:done(value)
        self.window.async_call(fn,finished,guarded=False)
    def reload(self):
        selected=self.channels.currentData()
        def load():
            imports=MarketDataResearchAPI(self.output).call('list_baostock_imports',{'offset':0,'limit':20})
            if not imports['ok']:raise ValueError(imports['error']['message'])
            return imports['data']['imports'],self.service.list()
        def show(value):
            imports,listing=value;self.batches.clear();self.channels.clear()
            for r in imports:
                if r.get('dataset_ready'):self.batches.addItem(r['import_id'][:8]+' · '+r['status'],r['import_id'])
            for s in listing['series']:self.channels.addItem(s['name']+' · v'+str(s['generation']),s['series_id'])
            if selected:self.channels.setCurrentIndex(self.channels.findData(selected))
            self.dirty();self.status.setText('载入最近20个批次；通道异常 '+str(len(listing['errors']))+' 项。')
        self.work(load,show)
    def create(self):
        if self.busy or not self.confirm.isChecked():self.status.setText('请核对并勾选确认。');return
        name=self.name.text();import_id=self.batches.currentData()
        if not import_id:return
        key=(name,import_id)
        if key!=self.create_key:self.create_id=str(uuid4());self.create_key=key
        identifier=self.create_id
        def show(state):
            self.dirty();self.details.setPlainText(encode(state));self.status.setText('通道已创建；请刷新列表后明确选择为研究数据源。')
        self.work(lambda:self.service.create(name,import_id,confirmed=True,series_id=identifier),show)
    def preview(self):
        sid=self.channels.currentData();import_id=self.batches.currentData();self.dirty()
        if not sid or not import_id:return
        def show(plan):
            if (sid,import_id)!=(self.channels.currentData(),self.batches.currentData()):return
            self.plan=plan;self.details.setPlainText(encode(plan))
            self.status.setText('核对通过；请确认历史修订（如有），再接入。尚未发布。')
        self.work(lambda:self.service.preview(sid,import_id),show)
    def accept_plan(self):
        if self.busy or self.plan is None or not self.confirm.isChecked():return
        if self.window.queue and any(j['status'] in ('queued','running') for j in self.window.queue.list()):
            self.status.setText('先等待当前研究完成，避免正在执行的输入版本变化。');return
        plan=self.plan;allow=self.revisions.isChecked()
        def show(result):
            self.dirty();self.details.setPlainText(encode(result))
            self.status.setText('已接入新批次。旧批次未变；未新增研究授权或任务。')
        self.work(lambda:self.service.accept(plan,digest(plan),confirmed=True,accept_revisions=allow),show)
    def history(self):
        sid=self.channels.currentData()
        if sid:self.work(lambda:self.service.get(sid),lambda value:self.details.setPlainText(encode(value)))
    def select(self):
        sid=self.channels.currentData()
        if self.busy or not sid:return
        try:
            self.window.select_baostock_series(sid)
            self.status.setText('已选择固定更新通道；更换数据源后请核对跟踪和授权。')
        except (OSError,ValueError) as error:self.status.setText(str(error))
