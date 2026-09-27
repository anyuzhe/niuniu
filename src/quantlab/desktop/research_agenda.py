"""Read-only deterministic research agenda."""
from PyQt6 import sip
from pathlib import Path
from uuid import UUID
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QPushButton,QTableWidgetItem
from quantlab.agent.research_agenda import ResearchAgendaService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row,table


class ResearchAgendaDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.busy=False
        self.output=Path(window.output);self.data_root=window.data_root;self.epoch=window.epoch
        stat=self.output.stat();self.workspace_identity=(stat.st_dev,stat.st_ino)
        self.closed=False;self.items=[];self.finished.connect(lambda *_:setattr(self,'closed',True))
        self.service=ResearchAgendaService(window.output,window.data_root)
        self.setWindowTitle('AI Research Agenda · 主动研究议程');self.resize(1080,820)
        box=QVBoxLayout(self)
        box.addWidget(label('只读汇总当前研究缺口和待办：不会运行实验、下载数据、注册候选或改变授权。优先级是工作流排序，不是收益预测。','note',True))
        self.refresh=button('刷新研究议程',self.reload)
        self.open_watch_button=button('打开所选观察池',self.open_watch)
        box.addWidget(row(self.refresh,self.open_watch_button))
        self.listing=table(['优先级','待办','原因','建议的人工操作'],[]);box.addWidget(self.listing,1)
        self.listing.itemSelectionChanged.connect(self.select_item)
        self.open_watch_button.setEnabled(False)
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('尚未生成议程。','muted',True);box.addWidget(self.status)
        self.reload()
    def valid_context(self):
        if self.closed or sip.isdeleted(self) or sip.isdeleted(self.window) or getattr(self.window,'closing',False):return False
        if self.output!=self.window.output or self.data_root!=self.window.data_root or self.epoch!=self.window.epoch:return False
        try:
            stat=self.output.stat();return self.workspace_identity==(stat.st_dev,stat.st_ino)
        except OSError:return False
    def closeEvent(self,event):self.closed=True;super().closeEvent(event)
    def selected_watch(self):
        index=self.listing.currentRow()
        if not 0<=index<len(self.items):return None
        refs=self.items[index].get('evidence',[])
        ids={r.get('watch_id') for r in refs if r.get('kind')=='watch' and isinstance(r.get('watch_id'),str)}
        if len(ids)!=1:return None
        value=next(iter(ids))
        try:return value if str(UUID(value))==value else None
        except ValueError:return None
    def select_item(self):
        index=self.listing.currentRow()
        if 0<=index<len(self.items):self.details.setPlainText(encode(self.items[index]))
        self.open_watch_button.setEnabled(not self.busy and self.valid_context() and self.selected_watch() is not None)
    def open_watch(self):
        if self.busy or not self.valid_context():return
        watch_id=self.selected_watch()
        if watch_id:self.window.factor_watches(watch_id)
    def reload(self):
        if self.busy:return
        if not self.valid_context():
            self.status.setText('工作空间或窗口已变化，请重新打开研究议程。');self.open_watch_button.setEnabled(False);return
        self.busy=True;self.refresh.setEnabled(False);self.open_watch_button.setEnabled(False)
        self.items=[];self.listing.setRowCount(0);self.details.setPlainText('{}')
        service=self.service
        def work():
            if not self.valid_context():raise ValueError('研究议程上下文已变化；未读取旧工作空间')
            return service.build(50)
        def done(value,error):
            if not self.valid_context():return
            self.busy=False;self.refresh.setEnabled(True)
            if error:self.status.setText('未完成：'+error);return
            self.items=value['items'];self.listing.setRowCount(len(self.items))
            for i,item in enumerate(self.items):
                for j,key in enumerate(('priority','title','reason','action')):
                    self.listing.setItem(i,j,QTableWidgetItem(str(item.get(key,''))))
            self.details.setPlainText(encode(value))
            omitted=value.get('omitted_items',max(0,value['total']-len(self.items)))
            self.status.setText('当前有界扫描生成 '+str(value['total'])+' 项待办，显示 '+str(len(self.items))+
                ' 项，省略 '+str(omitted)+' 项；本次生成研究任务 0。不是全工作空间健康认证。')
        self.window.async_call(work,done,guarded=False)
