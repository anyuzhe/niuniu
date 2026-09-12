"""Host approval, synchronization and watchlist promotion for Alpha Factory."""
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QCheckBox,QLineEdit,QPushButton
from quantlab.agent.alpha_factory import AlphaFactoryService
from quantlab.agent.dsl_candidates import DslCandidateService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row


class AlphaFactoryDialog(QDialog):
    def __init__(self,window,selected_id=None):
        super().__init__(window);self.window=window;self.busy=False;self.current=None
        self.service=AlphaFactoryService(window.output,window.data_root);self.selected_id=selected_id
        self.setWindowTitle('安全 Alpha Factory · 固定候选与全族检验');self.resize(1120,860)
        box=QVBoxLayout(self)
        box.addWidget(label('模型只能冻结Factory提案。这里人工一次批准后才提交原研究队列；运行中不能增删候选。进入Watchlist需要第二次人工确认。','note',True))
        self.proposals=QComboBox();self.reload_button=button('刷新Factory',self.reload)
        box.addWidget(row(self.proposals,self.reload_button))
        self.confirm=QCheckBox('我已核对候选集合、基准/控制因子、样本区间、全Factory Holm检验族和筛选规则，确认提交。')
        box.addWidget(self.confirm)
        self.submit_button=button('批准并提交固定Factory',self.submit,True)
        self.sync_button=button('同步Factory结果',self.sync)
        self.open_button=button('打开Factory结果',self.open_result)
        box.addWidget(row(self.submit_button,self.sync_button,self.open_button))
        self.candidates=QComboBox();self.watch_name=QLineEdit();self.watch_name.setPlaceholderText('观察池名称')
        self.promote_confirm=QCheckBox('我已复核完整Factory证据，确认只把当前推荐候选加入观察池；不创建自动刷新授权。')
        self.promote_button=button('人工加入Watchlist',self.promote)
        box.addWidget(row(self.candidates,self.watch_name));box.addWidget(self.promote_confirm);box.addWidget(self.promote_button)
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('未选择Factory。','muted',True);box.addWidget(self.status)
        self.proposals.currentIndexChanged.connect(self.select);self.confirm.toggled.connect(self.buttons)
        self.promote_confirm.toggled.connect(self.buttons);self.candidates.currentIndexChanged.connect(self.buttons)
        self.buttons();self.reload()
    def buttons(self):
        status=self.current.get('status') if self.current else None
        self.submit_button.setEnabled(not self.busy and status in ('pending','admitting') and self.confirm.isChecked())
        self.sync_button.setEnabled(not self.busy and status in ('submitted','running'))
        self.open_button.setEnabled(not self.busy and bool(self.current and self.current.get('result_run_id')))
        self.promote_button.setEnabled(not self.busy and status=='completed' and bool(self.candidates.currentData()) and self.promote_confirm.isChecked())
    def work(self,fn,done):
        if self.busy:return
        self.busy=True
        for c in self.findChildren(QPushButton):c.setEnabled(False)
        for c in (self.proposals,self.candidates,self.watch_name,self.confirm,self.promote_confirm):c.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for c in (self.proposals,self.candidates,self.watch_name,self.confirm,self.promote_confirm):c.setEnabled(True)
            self.reload_button.setEnabled(True)
            if error:self.status.setText('未完成：'+error)
            else:done(value)
            self.buttons()
        self.window.async_call(fn,finished,guarded=False)
    def reload(self):
        selected=self.proposals.currentData() or self.selected_id
        def show(value):
            self.proposals.blockSignals(True);self.proposals.clear()
            for item in value['factories']:
                self.proposals.addItem(item['status']+' · '+item['prepared']['plan']['name']+' · '+item['proposal_id'][:8],item['proposal_id'])
            if selected:self.proposals.setCurrentIndex(self.proposals.findData(selected))
            self.proposals.blockSignals(False);self.select()
            self.status.setText('已读取 '+str(len(value['factories']))+' 个Factory；异常 '+str(len(value['errors']))+' 项。')
        self.work(self.service.list,show)
    def select(self):
        proposal_id=self.proposals.currentData();self.current=None
        self.confirm.setChecked(False);self.promote_confirm.setChecked(False);self.candidates.clear()
        if not proposal_id:self.details.setPlainText('{}');self.buttons();return
        def show(value):
            if self.proposals.currentData()!=proposal_id:return
            self.current=value;self.details.setPlainText(encode(value));self.candidates.clear()
            registered=DslCandidateService(self.window.output)
            promoted={r['candidate_id'] for r in value.get('promotions',[])}
            for cid in value.get('recommended_candidate_ids',[]):
                if cid in promoted:continue
                try:name=registered.get(cid)['plan']['name']
                except Exception:name=cid[:8]
                self.candidates.addItem(name,cid)
            self.buttons()
        self.work(lambda:self.service.get(proposal_id),show)
    def submit(self):
        if not self.current or not self.confirm.isChecked():return
        proposal_id=self.current['proposal_id'];expected=self.current['prepared_digest']
        def show(value):
            self.current=value;self.confirm.setChecked(False);self.details.setPlainText(encode(value))
            self.status.setText('Factory任务已提交原研究队列；完成后点击同步结果。')
        self.work(lambda:self.service.submit(proposal_id,expected,self.window.get_research_queue,confirmed=True),show)
    def sync(self):
        if not self.current:return
        proposal_id=self.current['proposal_id']
        def show(value):
            self.current=value;self.details.setPlainText(encode(value))
            if value['status']=='completed':
                self.status.setText('Factory已完成；推荐候选仍需第二次人工确认才能进入Watchlist。')
            else:self.status.setText('Factory尚未全部终态：'+value['status'])
            self.select()
        self.work(lambda:self.service.sync(proposal_id),show)
    def open_result(self):
        if not self.current or not self.current.get('result_run_id'):return
        run_id=self.current['result_run_id'];self.window.catalog.file(run_id,'experiment.json');self.window.open_run(run_id)
    def promote(self):
        if not self.current or not self.promote_confirm.isChecked() or not self.candidates.currentData():return
        cid=self.candidates.currentData();name=self.watch_name.text().strip()
        if not name:
            try:name=DslCandidateService(self.window.output).get(cid)['plan']['name']+' · Factory观察'
            except Exception:name='Factory候选 '+cid[:8]
        proposal_id=self.current['proposal_id']
        def show(value):
            self.promote_confirm.setChecked(False);self.details.setPlainText(encode(value))
            self.status.setText('已加入Watchlist；未创建自动跟踪授权。')
            self.select()
        self.work(lambda:self.service.promote(proposal_id,cid,name,confirmed=True),show)
