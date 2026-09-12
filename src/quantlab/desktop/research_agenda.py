"""Read-only deterministic research agenda."""
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QPushButton
from quantlab.agent.research_agenda import ResearchAgendaService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row


class ResearchAgendaDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.busy=False
        self.service=ResearchAgendaService(window.output,window.data_root)
        self.setWindowTitle('AI Research Agenda · 主动研究议程');self.resize(1080,820)
        box=QVBoxLayout(self)
        box.addWidget(label('只读汇总当前研究缺口和待办：不会运行实验、下载数据、注册候选或改变授权。优先级是工作流排序，不是收益预测。','note',True))
        self.refresh=button('刷新研究议程',self.reload);box.addWidget(row(self.refresh))
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('尚未生成议程。','muted',True);box.addWidget(self.status)
        self.reload()
    def reload(self):
        if self.busy:return
        self.busy=True;self.refresh.setEnabled(False)
        def done(value,error):
            if sip.isdeleted(self):return
            self.busy=False;self.refresh.setEnabled(True)
            if error:self.status.setText('未完成：'+error);return
            self.details.setPlainText(encode(value))
            self.status.setText('当前 '+str(value['total'])+' 项研究待办；本次生成研究任务 0。')
        self.window.async_call(lambda:self.service.build(50),done,guarded=False)
