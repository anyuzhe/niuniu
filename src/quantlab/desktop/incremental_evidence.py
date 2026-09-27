"""Host-only execution of fixed incremental-evidence proposals."""
from pathlib import Path
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QCheckBox,QPushButton
from quantlab.agent.incremental_evidence import IncrementalEvidenceService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row


class IncrementalEvidenceDialog(QDialog):
    def __init__(self,window,selected_id=None):
        super().__init__(window);self.window=window;self.output=window.output;self.busy=False;self.current=None
        self.service=IncrementalEvidenceService(self.output);self.selected_id=selected_id
        self.data_root=window.data_root;self.epoch=getattr(window,'epoch',None);self.closed=False
        stat=Path(self.output).stat();self.workspace_identity=(stat.st_dev,stat.st_ino)
        self.finished.connect(lambda *_:setattr(self,'closed',True))
        self.setWindowTitle('候选增量证据包 · 宿主确认执行');self.resize(1050,800)
        box=QVBoxLayout(self)
        box.addWidget(label('模型只能预览和保存固定计划；这里人工核对后才运行。失败测试保留在Holm检验族中，不自动补做或换候选。','note',True))
        self.proposals=QComboBox();self.reload_button=button('刷新证据包',self.reload)
        box.addWidget(row(self.proposals,self.reload_button))
        self.confirm=QCheckBox('我已核对候选、控制因子、训练截止、持有期和全部计划测试，确认执行固定证据包。')
        box.addWidget(self.confirm)
        self.run_button=button('执行固定证据包',self.execute,True);self.open_button=button('打开结果归档',self.open_result)
        box.addWidget(row(self.run_button,self.open_button))
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('未选择证据包。','muted',True);box.addWidget(self.status)
        self.proposals.currentIndexChanged.connect(self.select);self.confirm.toggled.connect(self.buttons)
        self.buttons();self.reload()
    def valid_context(self):
        if self.closed or sip.isdeleted(self) or getattr(self.window,'closing',False):return False
        if self.output!=self.window.output or self.data_root!=self.window.data_root or self.epoch!=getattr(self.window,'epoch',None):return False
        try:
            stat=Path(self.output).stat();return self.workspace_identity==(stat.st_dev,stat.st_ino)
        except OSError:return False
    def closeEvent(self,event):self.closed=True;super().closeEvent(event)
    def buttons(self):
        ready=self.valid_context() and bool(self.current and self.current.get('status')!='completed')
        self.run_button.setEnabled(not self.busy and ready and self.confirm.isChecked())
        self.open_button.setEnabled(self.valid_context() and not self.busy and bool(self.current and self.current.get('result_run_id')))
    def work(self,fn,done):
        if self.busy or not self.valid_context():return
        self.busy=True
        for c in self.findChildren(QPushButton):c.setEnabled(False)
        self.proposals.setEnabled(False);self.confirm.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            if not self.valid_context():return
            self.proposals.setEnabled(True);self.confirm.setEnabled(True)
            self.reload_button.setEnabled(True)
            if error:
                self.current=None;self.confirm.setChecked(False);self.details.setPlainText('{}')
                self.status.setText('未完成：'+str(error))
            else:done(value)
            self.buttons()
        def guarded():
            if not self.valid_context():raise ValueError('原增量证据窗口上下文已变化')
            return fn()
        self.window.async_call(guarded,finished,guarded=False)
    def reload(self):
        selected=self.proposals.currentData() or self.selected_id
        def show(value):
            self.proposals.blockSignals(True);self.proposals.clear()
            for item in value['proposals']:
                self.proposals.addItem(item['status']+' · '+item['proposal_id'][:8],item['proposal_id'])
            if selected:self.proposals.setCurrentIndex(self.proposals.findData(selected))
            self.proposals.blockSignals(False);self.select()
            self.status.setText('已读取 '+str(len(value['proposals']))+' 个固定证据包；异常 '+str(len(value['errors']))+' 项。')
        self.work(self.service.list,show)
    def select(self):
        proposal_id=self.proposals.currentData();self.current=None;self.confirm.setChecked(False)
        if not proposal_id:self.details.setPlainText('{}');self.buttons();return
        def show(value):
            if self.proposals.currentData()!=proposal_id:return
            self.current=value;self.details.setPlainText(encode(value));self.buttons()
        self.work(lambda:self.service.get(proposal_id),show)
    def execute(self):
        if self.busy or not self.valid_context():return
        if not self.current or not self.confirm.isChecked():return
        proposal_id=self.current['proposal_id'];expected=self.current['prepared_digest']
        def show(value):
            self.current=value;self.confirm.setChecked(False);self.details.setPlainText(encode(value))
            self.status.setText('固定证据包已完成；没有自动追加测试或候选。')
        self.work(lambda:self.service.execute(proposal_id,expected,confirmed=True),show)
    def open_result(self):
        if self.busy or not self.valid_context():return
        if not self.current or not self.current.get('result_run_id'):return
        run_id=self.current['result_run_id']
        self.window.catalog.file(run_id,'experiment.json');self.window.open_run(run_id)
