from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QCheckBox,QPushButton
from quantlab.agent.dsl_candidates import DslCandidateService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row

class DslCandidateDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.service=DslCandidateService(window.output);self.busy=False
        self.setWindowTitle('受限DSL候选注册');self.resize(1050,820)
        box=QVBoxLayout(self)
        box.addWidget(label('模型只能验证和保存候选提案；这里人工注册。注册不执行Alpha研究，也不生成任意Python。','note',True))
        self.pending=QComboBox();self.registered=QComboBox();self.confirm=QCheckBox('我已核对AST、验证来源和前缀检查，确认注册此不可变候选预设。')
        self.register_button=button('确认注册候选',self.register,True)
        box.addWidget(row(label('待注册提案'),self.pending,button('刷新',self.reload)))
        box.addWidget(self.confirm);box.addWidget(self.register_button)
        box.addWidget(row(label('已注册候选'),self.registered,button('查看已注册详情',self.show_registered)))
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('注册后仍需用原研究提案/审批验证Alpha。','muted',True);box.addWidget(self.status)
        self.pending.currentIndexChanged.connect(self.select_pending);self.confirm.toggled.connect(self.buttons)
        self.buttons();self.reload()
    def buttons(self):self.register_button.setEnabled(not self.busy and self.pending.currentData() is not None and self.confirm.isChecked())
    def work(self,fn,done):
        if self.busy:return
        self.busy=True
        for c in [*self.findChildren(QPushButton),self.pending,self.registered,self.confirm]:c.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for c in [*self.findChildren(QPushButton),self.pending,self.registered,self.confirm]:c.setEnabled(True)
            if error:self.status.setText('未完成：'+error)
            else:done(value)
            self.buttons()
        self.window.async_call(fn,finished,guarded=False)
    def reload(self):
        def show(value):
            pending,registered=value;self.pending.clear();self.registered.clear()
            for p in pending['proposals']:
                self.pending.addItem(p['plan']['name']+' · '+p['request_id'][:8],p['request_id'])
            for c in registered['candidates']:
                self.registered.addItem(c['name']+' · '+c['candidate_id'][:8],c['candidate_id'])
            self.confirm.setChecked(False);self.select_pending()
            self.status.setText(f"待注册 {len(pending['proposals'])} 项；已注册 {registered['total']} 项。")
        self.work(lambda:(self.service.pending(),self.service.list(limit=100)),show)
    def select_pending(self):
        request_id=self.pending.currentData();self.confirm.setChecked(False)
        if not request_id:self.details.setPlainText('{}');return
        try:self.details.setPlainText(encode(self.service.proposal(request_id)))
        except Exception as error:self.status.setText(str(error))
    def register(self):
        request_id=self.pending.currentData()
        if not request_id or not self.confirm.isChecked():return
        proposal=self.service.proposal(request_id)
        def show(value):
            self.details.setPlainText(encode(value));self.status.setText('候选已注册；未执行研究。')
            self.reload()
        self.work(lambda:self.service.register(request_id,proposal['plan_digest'],confirmed=True),show)
    def show_registered(self):
        candidate_id=self.registered.currentData()
        if candidate_id:self.work(lambda:self.service.get(candidate_id),lambda v:self.details.setPlainText(encode(v)))
