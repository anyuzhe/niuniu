"""Explicit baseline rebuild and version link, separate from research approval."""
from uuid import uuid4
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QComboBox,QLineEdit,QCheckBox
from quantlab.agent.watch_rebase import WatchRebaseService
from quantlab.storage.codec import digest,encode
from .business_view import BusinessDetails
from .widgets import label,button,row


class WatchRebaseDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.busy=False;self.plan=None
        self.service=WatchRebaseService(window.output,window.data_root)
        self.request_ids={};self.setWindowTitle('跟踪基准换版：保留旧历史');self.resize(1050,780)
        box=QVBoxLayout(self)
        box.addWidget(label('先暂停旧跟踪并撤销授权。通过原审批计算同区间新版基准，再核对历史数值。确认后另建暂停的新跟踪；不继承授权，不合并快照。','note',True))
        form=QFormLayout();box.addLayout(form)
        self.old=QComboBox();self.candidate=QComboBox();self.name=QLineEdit('新版基准跟踪')
        for title,control in [('旧跟踪',self.old),('已完成新版基准',self.candidate),('新跟踪名称',self.name)]:
            form.addRow(title,control)
        self.reload_button=button('刷新列表',self.reload)
        self.propose_button=button('生成同区间重建提案',self.propose)
        self.preview_button=button('核对换版计划',self.preview)
        box.addWidget(row(self.reload_button,self.propose_button,self.preview_button))
        self.confirm=QCheckBox('我已核对：只新建暂停跟踪并记录版本关系，不续用旧授权。')
        box.addWidget(self.confirm)
        self.accept_button=button('确认建立新版暂停跟踪',self.accept_plan,True)
        self.history_button=button('查看旧跟踪的换版记录',self.show_history)
        box.addWidget(row(self.accept_button,self.history_button))
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('仅在你确认后写入版本关系；重建研究仍须原审批。','muted',True);box.addWidget(self.status)
        self.controls=[self.old,self.candidate,self.name,self.reload_button,self.propose_button,
            self.preview_button,self.confirm,self.accept_button,self.history_button]
        self.old.currentIndexChanged.connect(self.dirty)
        self.candidate.currentIndexChanged.connect(self.dirty);self.name.textChanged.connect(self.dirty)
        self.confirm.toggled.connect(self.buttons);self.buttons();self.reload()
    def buttons(self,*_):
        self.accept_button.setEnabled(not self.busy and self.plan is not None and self.confirm.isChecked())
    def dirty(self,*_):
        self.plan=None;self.confirm.setChecked(False);self.buttons()
    def work(self,fn,done):
        if self.busy:return
        self.busy=True
        for control in self.controls:control.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for control in self.controls:control.setEnabled(True)
            if error:self.status.setText('未完成：'+error)
            else:done(value)
            self.buttons()
        self.window.async_call(fn,finished,guarded=False)
    def reload(self):
        self.dirty()
        def show(value):
            watches,runs=value;self.old.clear();self.candidate.clear()
            for r in watches['watches']:
                self.old.addItem(('暂停' if not r['active'] else '启用')+' · '+r['name'],r['watch_id'])
            for r in runs['runs']:
                self.candidate.addItem(r['run_id'][:8]+' · '+r['question'],r['run_id'])
            self.status.setText('旧跟踪须暂停；候选基准须为当前代码下同区间重新计算的结果。')
        self.work(lambda:(self.service.watch.store.list(),
            self.window.catalog.list(status='completed',kind='factor',limit=10000)),show)
    def propose(self):
        old=self.old.currentData()
        if not old:self.status.setText('请选择旧跟踪。');return
        request=self.request_ids.setdefault(old,str(uuid4()))
        def show(proposal):
            from .agent_proposals import ProposalDialog
            self.window.show_dialog(ProposalDialog(self.window,selected_id=proposal['proposal_id']))
            self.status.setText('重建提案已保存；批准并完成后刷新列表选择新版基准。')
        self.work(lambda:self.service.propose(old,request),show)
    def preview(self):
        old=self.old.currentData();candidate=self.candidate.currentData();name=self.name.text()
        self.dirty()
        if not old or not candidate:self.status.setText('请选择旧跟踪和已完成候选基准。');return
        def show(plan):
            if (self.old.currentData(),self.candidate.currentData(),self.name.text()) != (old,candidate,name):
                self.status.setText('选择已变化，请重新核对换版计划。');return
            self.plan=plan;self.details.setPlainText(encode(plan))
            self.status.setText('同区间逐项核对通过；当前尚未创建新跟踪。')
        self.work(lambda:self.service.preview(old,candidate,name),show)
    def accept_plan(self):
        if self.busy or self.plan is None or not self.confirm.isChecked():return
        plan=self.plan
        def show(result):
            self.dirty();self.details.setPlainText(encode(result))
            self.status.setText('新版跟踪已创建并暂停；旧历史未改变，未继承授权：'+result['new_watch_id'])
        self.work(lambda:self.service.accept(plan,digest(plan),confirmed=True),show)
    def show_history(self):
        old=self.old.currentData()
        if not old:return
        self.work(lambda:self.service.history(old),lambda value:self.details.setPlainText(encode(value)))
