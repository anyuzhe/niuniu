"""Native dialogue with persisted turns and host-generated evidence links."""
import json
from threading import Event
from PyQt6 import sip
from PyQt6.QtCore import pyqtSignal,Qt,QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QPlainTextEdit,QScrollArea,QListWidget,QListWidgetItem
from quantlab.agent.model_config import load_model_config,save_model_config
from quantlab.agent.chat_runtime import ChatRuntime,probe_model
from .model_settings import ModelSettings
from .widgets import label,button,row


class AgentChatDialog(QDialog):
    event_received=pyqtSignal(str,object)
    def __init__(self,window):
        super().__init__(window);self.window=window;self.busy=False;self.stop_flag=Event();self.closing=False
        self.runtime=ChatRuntime(window.output,window.data_root);self.setWindowTitle('牛牛 AI 研究助手');self.resize(1100,950)
        box=QVBoxLayout(self);box.addWidget(label('模型对话与真实研究工具 · 查询、计划、提案；执行仍须你在批准面板确认。','note',True))
        self.settings=ModelSettings(load_model_config(window.output));scroll=QScrollArea()
        scroll.setWidgetResizable(True);scroll.setWidget(self.settings);scroll.setMaximumHeight(310);box.addWidget(scroll)
        self.probe_button=button('连接并读取模型列表',self.probe)
        self.save_button=button('保存模型配置（不保存密钥）',self.save_settings)
        box.addWidget(row(self.probe_button,self.save_button))
        self.sessions=QComboBox();self.new_button=button('新建对话',self.new_conversation)
        box.addWidget(row(label('本地会话'),self.sessions,self.new_button))
        self.transcript=QPlainTextEdit();self.transcript.setReadOnly(True);self.transcript.setAccessibleName('研究助手对话记录')
        box.addWidget(self.transcript,3)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(110)
        self.log.setAccessibleName('助手工具调用记录');box.addWidget(self.log)
        self.references=QListWidget();self.references.setMaximumHeight(90);box.addWidget(self.references)
        box.addWidget(row(button('打开选中实际证据',self.open_reference),button('研究提案与人工批准',self.open_proposals)))
        self.input=QPlainTextEdit();self.input.setMaximumHeight(90)
        self.input.setPlaceholderText('例如：先查已有动量因子，再为我指定的股票和区间生成研究提案。');box.addWidget(self.input)
        self.send_button=button('发送',self.send,True);self.stop_button=button('停止助手（不取消研究）',self.stop)
        box.addWidget(row(self.send_button,self.stop_button,button('关闭',self.close)))
        self.status=label('尚未连接；配置和会话保存在当前工作空间，密钥只在此窗口内存。','muted',True);box.addWidget(self.status)
        self.sessions.currentIndexChanged.connect(self.load_conversation)
        self.event_received.connect(self.on_event)
        self.refresh_sessions();self.set_busy(False)
    def refresh_sessions(self,selected=None):
        items=self.runtime.store.conversations()
        if not items:selected=self.runtime.store.create();items=self.runtime.store.conversations()
        self.sessions.blockSignals(True);self.sessions.clear()
        for item in items:self.sessions.addItem(item['title']+' · '+item['created_at'][:16],item['id'])
        if selected:self.sessions.setCurrentIndex(self.sessions.findData(selected))
        self.sessions.blockSignals(False);self.load_conversation()
    def new_conversation(self):
        if self.busy:return
        self.refresh_sessions(self.runtime.store.create('研究对话 '+str(len(self.runtime.store.conversations())+1)))
    def load_conversation(self):
        cid=self.sessions.currentData()
        if not cid:return
        lines=[];self.references.clear();self.log.clear()
        turns=self.runtime.store.turns(cid)
        if len(turns)>20:lines.append('界面仅展示最近 20 轮；较早记录保留在本地数据库。')
        for turn in turns[-20:]:
            lines.extend(['你：'+turn['user_text'],'助手：'+(turn['assistant_text'] or '['+turn['status']+'] '+turn['metadata'].get('error','')),''])
            for ref in turn['metadata'].get('evidence',[]):self.add_reference(ref)
        if turns:
            for event in self.runtime.store.events(turns[-1]['id']):
                if event['kind'] in ('tool_call','tool_result'):
                    self.log.appendPlainText(event['kind']+' '+json.dumps(event['payload'],ensure_ascii=False)[:3000])
        self.transcript.setPlainText('\n'.join(lines));self.transcript.moveCursor(QTextCursor.MoveOperation.End)
    def set_busy(self,busy):
        self.busy=busy
        for c in (self.settings,self.probe_button,self.save_button,self.sessions,self.new_button,self.send_button,self.input):c.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
    def save_settings(self):
        try:save_model_config(self.window.output,self.settings.collect());self.status.setText('已保存非敏感模型配置；未保存 Key，未发送请求。')
        except Exception as exc:self.status.setText('配置未保存：'+str(exc))
    def start_work(self,work,done):
        self.stop_flag=Event();self.set_busy(True)
        def finished(result,error):
            if sip.isdeleted(self):return
            self.set_busy(False)
            if error:self.status.setText(error)
            done(result,error)
            if self.closing:QTimer.singleShot(0,self.close)
        self.window.async_call(lambda:work(self.stop_flag),finished,guarded=False)
    def probe(self):
        if self.busy:return
        try:
            cfg=self.settings.collect();key=self.settings.key.text();allowed=self.settings.allow.isChecked()
            if not allowed:raise ValueError('请先勾选连接与数据发送许可')
        except Exception as exc:self.status.setText(str(exc));return
        self.status.setText('正在检查所选连接和实际模型列表…')
        def done(result,error):
            if error:return
            current=self.settings.model.currentText();self.settings.model.clear();self.settings.model.addItem('')
            for item in result['models']:self.settings.model.addItem(item.get('model') or item['id'])
            self.settings.model.setEditText(current)
            self.status.setText('连接成功 · '+result['provider']+' · '+str(len(result['models']))+' 个模型；可手动输入模型 ID。')
            self.log.setPlainText(json.dumps(result,ensure_ascii=False,indent=2))
        self.start_work(lambda stop:probe_model(cfg,key,allow_send=allowed,stop=stop),done)
    def send(self):
        if self.busy:return
        try:
            cfg=self.settings.collect();text=self.input.toPlainText();key=self.settings.key.text()
            allowed=self.settings.allow.isChecked();cid=self.sessions.currentData()
            if not allowed:raise ValueError('请先勾选允许向所选模型发送对话与研究摘要')
            if not text.strip():raise ValueError('请填写消息')
            save_model_config(self.window.output,cfg)
        except Exception as exc:self.status.setText(str(exc));return
        self.input.clear();self.log.clear();self.references.clear()
        self.transcript.appendPlainText('\n你：'+text+'\n助手：');self.status.setText('助手处理中；研究是否执行仍以任务和批准记录为准。')
        def done(result,error):
            self.load_conversation()
            if not error:self.status.setText('本轮完成 · '+str(result.get('model',''))+' · '+str(result['tool_calls'])+' 次工具调用。提案尚须人工批准。')
        self.start_work(lambda stop:self.runtime.send(cid,text,cfg,api_key=key,allow_send=allowed,
            stop=stop,emit=self.event_received.emit),done)
    def on_event(self,kind,value):
        if sip.isdeleted(self):return
        if kind=='text_delta':
            self.transcript.moveCursor(QTextCursor.MoveOperation.End);self.transcript.insertPlainText(value['text'])
        elif kind=='tool_call':
            self.log.appendPlainText('调用 '+str(value['name'])+'\n'+json.dumps(value['arguments'],ensure_ascii=False)[:3000])
        elif kind=='tool_result':
            self.log.appendPlainText('结果 '+str(value['name'])+'\n'+json.dumps(value['result'],ensure_ascii=False)[:3000])
            for ref in value['result'].get('evidence',[]):self.add_reference(ref)
        elif kind=='connection':self.status.setText('已连接 '+str(value.get('model',''))+'；正在处理…')
        elif kind=='turn_error':self.status.setText(value['message'])
    def add_reference(self,ref):
        if not isinstance(ref,dict) or ref.get('kind') not in ('experiment','proposal','job','factor','memory','watch','peer_review'):return
        for i in range(self.references.count()):
            if self.references.item(i).data(Qt.ItemDataRole.UserRole)==ref:return
        key={'experiment':'run_id','proposal':'proposal_id','job':'job_id','factor':'factor_id','memory':'memory_id','watch':'watch_id','peer_review':'task_id'}[ref['kind']]
        title={'experiment':'实验','proposal':'待核对提案','job':'任务','factor':'因子','memory':'研究记忆','watch':'因子跟踪','peer_review':'同行复核'}[ref['kind']]
        item=QListWidgetItem(title+' · '+str(ref[key]));item.setData(Qt.ItemDataRole.UserRole,ref)
        self.references.addItem(item)
    def open_reference(self):
        item=self.references.currentItem()
        if not item:return
        ref=item.data(Qt.ItemDataRole.UserRole)
        if ref['kind']=='proposal':self.open_proposals(ref['proposal_id'])
        elif ref['kind']=='experiment':self.window.open_run(ref['run_id'])
        elif ref['kind']=='watch':self.window.factor_watches(ref['watch_id'])
        elif ref['kind']=='memory':self.window.research_memory(ref['memory_id'])
        elif ref['kind']=='job':self.window.show_jobs()
        elif ref['kind']=='peer_review':self.window.navigate_root(5)
        else:self.window.registry_page('factor',ref['factor_id'])
    def open_proposals(self,selected_id=None):
        if not self.window.data_root:self.status.setText('当前未配置行情目录，不能提交研究提案');return
        from .agent_proposals import ProposalDialog
        self.window.show_dialog(ProposalDialog(self.window,selected_id if isinstance(selected_id,str) else None))
    def stop(self):
        self.stop_flag.set();self.status.setText('已请求停止助手；HTTP 请求在返回或超时后停止，不取消已批准研究。')
    def closeEvent(self,event):
        if self.busy:
            self.closing=True;self.stop();event.ignore();return
        self.settings.key.clear();event.accept()


def launch_chat(output,data_root=None):
    import sys
    from PyQt6.QtWidgets import QApplication
    from .app import MainWindow
    app=QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('牛牛 AI 研究助手');app.setStyle('Fusion')
    from .data_workbench import DataConnectedWorkbench
    window=DataConnectedWorkbench(output,data_root);window.show()
    window.research_chat()
    return app.exec()
