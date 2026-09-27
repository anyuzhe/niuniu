"""Read-only deterministic research agenda."""
from PyQt6 import sip
from pathlib import Path
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QPushButton,QTableWidgetItem,QComboBox
from quantlab.agent.research_agenda import ResearchAgendaService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row,table
from .agenda_navigation import agenda_targets,canonical_target,read_agenda_target,open_agenda_target


class ResearchAgendaDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.busy=False
        self.output=Path(window.output);self.data_root=window.data_root;self.epoch=window.epoch
        stat=self.output.stat();self.workspace_identity=(stat.st_dev,stat.st_ino)
        self.closed=False;self.items=[];self.generation=0
        self.finished.connect(lambda *_:setattr(self,'closed',True))
        self.service=ResearchAgendaService(window.output,window.data_root)
        self.setWindowTitle('AI Research Agenda · 主动研究议程');self.resize(1080,820)
        box=QVBoxLayout(self)
        box.addWidget(label('只读汇总当前研究缺口和待办：不会运行实验、下载数据、注册候选或改变授权。优先级是工作流排序，不是收益预测。','note',True))
        self.refresh=button('刷新研究议程',self.reload)
        self.open_watch_button=button('打开所选观察池',self.open_watch)
        box.addWidget(row(self.refresh,self.open_watch_button))
        self.references=QComboBox();self.references.setAccessibleName('待办的精确证据引用')
        self.open_reference_button=button('核对后打开所选证据 / 原处理页',self.open_reference)
        self.open_reference_button.setEnabled(False)
        self.references.currentIndexChanged.connect(self.reference_changed)
        box.addWidget(row(self.references,self.open_reference_button))
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
    def closeEvent(self,event):self.closed=True;self.generation+=1;super().closeEvent(event)
    def selected_watch(self):
        index=self.listing.currentRow()
        if not 0<=index<len(self.items):return None
        targets,_=agenda_targets(self.items[index])
        ids={t['reference']['watch_id'] for t in targets if t['reference']['kind']=='watch'}
        return next(iter(ids)) if len(ids)==1 else None
    def select_item(self):
        self.generation+=1;index=self.listing.currentRow();self.references.clear()
        if 0<=index<len(self.items):
            item=self.items[index];targets,errors=agenda_targets(item)
            for target in targets:self.references.addItem(target['label'],target['reference'])
            self.references.setCurrentIndex(-1)
            self.details.setPlainText(encode({'agenda_item':item,'navigation_errors':errors}))
            self.status.setText('已读取 '+str(len(targets))+' 个可打开引用；请选择具体证据。'+
                ('另有 '+str(len(errors))+' 个不支持或无效引用，见明细。' if errors else '')+
                '仅导航，不批准、注册、运行或标记待办完成；不是全工作空间健康认证。')
        else:self.details.setPlainText('{}')
        self.actions()
    def actions(self):
        idle=not self.busy and self.valid_context()
        self.refresh.setEnabled(idle);self.listing.setEnabled(idle);self.references.setEnabled(idle)
        self.open_watch_button.setEnabled(idle and self.selected_watch() is not None)
        self.open_reference_button.setEnabled(idle and self.references.currentData() is not None)
    def reference_changed(self,*_):
        self.generation+=1
        if hasattr(self,'listing'):self.actions()
    def open_reference(self,*_):
        if self.busy or not self.valid_context():return
        value=self.references.currentData()
        if value is None:return
        try:target=canonical_target(value)
        except (ValueError,TypeError) as error:self.status.setText('引用未打开：'+str(error));return
        generation=self.generation;self.busy=True;self.actions();self.status.setText('正在重新核对精确来源…')
        def work():
            if not self.valid_context():raise ValueError('工作空间已变化；未读取旧引用')
            return read_agenda_target(self.output,target)
        def done(checked,error):
            if sip.isdeleted(self):return
            self.busy=False
            if not self.valid_context():return
            self.actions()
            if generation!=self.generation:return
            if error:self.status.setText('来源无法打开：'+str(error)+'；未换成其他同名记录。');return
            try:
                if checked['reference']!=target:raise ValueError('来源回执与所选引用不一致')
                open_agenda_target(self.window,checked)
                self.status.setText('已打开精确来源；未自动批准、运行、重试或标记待办完成。')
            except Exception as exc:self.status.setText('原页面未打开：'+str(exc))
        try:self.window.async_call(work,done,guarded=False)
        except Exception as exc:done(None,str(exc))
    def open_watch(self):
        if self.busy or not self.valid_context():return
        watch_id=self.selected_watch()
        if watch_id:self.window.factor_watches(watch_id)
    def reload(self):
        if self.busy:return
        if not self.valid_context():
            self.status.setText('工作空间或窗口已变化，请重新打开研究议程。');self.open_watch_button.setEnabled(False);return
        self.busy=True;self.generation+=1
        self.items=[];self.listing.setRowCount(0);self.references.clear();self.details.setPlainText('{}')
        generation=self.generation;self.actions()
        service=self.service
        def work():
            if not self.valid_context():raise ValueError('研究议程上下文已变化；未读取旧工作空间')
            return service.build(50)
        def done(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            if not self.valid_context():return
            self.actions()
            if generation!=self.generation:return
            if error:self.status.setText('未完成：'+str(error));return
            try:
                if not isinstance(value,dict) or not isinstance(value.get('items'),list) or type(value.get('total')) is not int:
                    raise ValueError('研究议程回执格式无效')
                if any(not isinstance(item,dict) for item in value['items']):raise ValueError('待办记录格式无效')
                self.items=value['items'];self.listing.blockSignals(True);self.listing.setRowCount(len(self.items))
                for i,item in enumerate(self.items):
                    for j,key in enumerate(('priority','title','reason','action')):
                        self.listing.setItem(i,j,QTableWidgetItem(str(item.get(key,''))))
                self.listing.clearSelection();self.listing.setCurrentCell(-1,-1);self.listing.blockSignals(False)
                self.details.setPlainText(encode(value))
                omitted=value.get('omitted_items',max(0,value['total']-len(self.items)))
                self.status.setText('当前有界扫描生成 '+str(value['total'])+' 项待办，显示 '+str(len(self.items))+
                    ' 项，省略 '+str(omitted)+' 项；本次生成研究任务 0。不是全工作空间健康认证。')
            except Exception as exc:
                self.listing.blockSignals(False);self.items=[];self.listing.setRowCount(0)
                self.references.clear();self.details.setPlainText('{}');self.status.setText('议程读取未完成：'+str(exc))
            self.actions()
        try:self.window.async_call(work,done,guarded=False)
        except Exception as exc:done(None,str(exc))
