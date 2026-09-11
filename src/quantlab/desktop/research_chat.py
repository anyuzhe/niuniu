"""Native research conversation with separately rendered host evidence."""
import json
from datetime import datetime
from threading import Event
from PyQt6 import sip
from PyQt6.QtCore import QObject,Qt,pyqtSignal
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QWidget,QComboBox,QPlainTextEdit,
    QCheckBox,QGroupBox,QScrollArea,QListWidget,QListWidgetItem,QSplitter)
from quantlab.agent.model_config import load_model_config,save_model_config
from quantlab.agent.chat_runtime import ChatRuntime,make_provider
from quantlab.storage.codec import digest
from .model_settings import ModelSettings
from .business_view import BusinessDetails
from .widgets import label,button,row


class ChatSignals(QObject):
    event=pyqtSignal(str,object)


class ResearchChatDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.output=window.output;self.data_root=window.data_root
        self.runtime=ChatRuntime(self.output,self.data_root);self.busy=False;self.close_requested=False
        self.stop_event=Event();self.references={};self.session_id=None
        self.setWindowTitle('牛牛 · AI 研究助手');self.resize(1180,900)
        box=QVBoxLayout(self)
        box.addWidget(label('模型负责讨论与提案；真实状态和证据来自工具。研究仍须在宿主界面批准。','note',True))
        self.sessions=QComboBox();self.new_button=button('新会话',self.new_session)
        self.save_button=button('保存模型配置',self.save_settings)
        self.probe_button=button('测试连接／刷新模型',self.probe)
        box.addWidget(row(label('会话（最近100项）'),self.sessions,self.new_button,self.save_button,self.probe_button))
        self.settings=ModelSettings(load_model_config(self.output),self)
        self.group=QGroupBox('模型连接与预算设置（可展开）');self.group.setCheckable(True);self.group.setChecked(False)
        layout=QVBoxLayout(self.group);self.settings_scroll=QScrollArea();self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setWidget(self.settings);self.settings_scroll.setMaximumHeight(330)
        layout.addWidget(self.settings_scroll);self.settings_scroll.hide()
        self.group.toggled.connect(self.settings_scroll.setVisible);box.addWidget(self.group)
        self.consent=QCheckBox();box.addWidget(self.consent)
        self.settings.changed.connect(self.config_changed);self.config_changed()
        split=QSplitter();left=QWidget();left_box=QVBoxLayout(left)
        self.transcript=QPlainTextEdit();self.transcript.setReadOnly(True)
        self.transcript.setAccessibleName('研究助手对话');left_box.addWidget(self.transcript,1)
        self.input=QPlainTextEdit();self.input.setMaximumHeight(110)
        self.input.setPlaceholderText('例如：查询已有动量因子，然后为三只股票拟定一份研究提案。')
        self.input.setAccessibleName('研究问题');left_box.addWidget(self.input)
        self.send_button=button('发送研究问题',self.send,True)
        self.stop_button=button('停止助手（不取消研究）',self.stop);self.stop_button.setEnabled(False)
        left_box.addWidget(row(self.send_button,self.stop_button));split.addWidget(left)
        right=QWidget();right_box=QVBoxLayout(right);right_box.addWidget(label('实际工具记录与证据'))
        self.tool_list=QListWidget();self.tool_list.setMaximumHeight(140);right_box.addWidget(self.tool_list)
        self.details=BusinessDetails({});right_box.addWidget(self.details,1)
        self.evidence=QListWidget();self.evidence.setMaximumHeight(150);right_box.addWidget(self.evidence)
        self.open_button=button('打开选中的真实引用',self.open_reference);right_box.addWidget(self.open_button)
        self.approvals_button=button('打开人工提案审批',self.open_proposals);right_box.addWidget(self.approvals_button)
        split.addWidget(right);split.setSizes([700,400]);box.addWidget(split,1)
        self.status=label('尚未调用模型。Codex 登录连接仍使用上游模型服务，不是离线推理。','muted',True)
        box.addWidget(self.status);self.signals=ChatSignals(self);self.signals.event.connect(lambda kind,value:self.receive(kind,value) if self.busy else None)
        self.tool_list.currentItemChanged.connect(self.show_tool)
        self.sessions.currentIndexChanged.connect(self.select_session)
        records=self.runtime.store.list()
        if not records:self.new_session()
        else:self.refresh_sessions(records[0]['id'])

    def config_changed(self):
        self.consent.setChecked(False)
        target='Codex CLI 的 ChatGPT 登录服务' if self.settings.provider.currentData()=='codex_cli' else self.settings.fields['base_url'].text()
        self.consent.setText('允许将本次对话和有限工具摘要发送至：'+target)

    def set_busy(self,busy):
        self.busy=busy
        for control in (self.sessions,self.new_button,self.save_button,self.probe_button,self.group,
            self.consent,self.input,self.send_button,self.open_button,self.approvals_button):control.setEnabled(not busy)
        self.stop_button.setEnabled(busy)

    def refresh_sessions(self,selected):
        self.sessions.blockSignals(True);self.sessions.clear()
        for record in self.runtime.store.list():self.sessions.addItem(record['title'],record['id'])
        self.sessions.setCurrentIndex(self.sessions.findData(selected));self.sessions.blockSignals(False)
        self.select_session()

    def new_session(self):
        if self.busy:return
        identifier=self.runtime.store.create('研究会话 '+datetime.now().strftime('%m-%d %H:%M:%S'))
        self.refresh_sessions(identifier)

    def select_session(self):
        if self.busy:return
        self.session_id=self.sessions.currentData()
        if not self.session_id:return
        try:history=self.runtime.store.events(self.session_id)
        except Exception as error:
            self.status.setText('会话记录无法读取：'+type(error).__name__);return
        self.transcript.clear();self.tool_list.clear();self.evidence.clear();self.references={}
        self.details.setPlainText('{}')
        if history['omitted']:self.transcript.appendPlainText('仅展示最近500条事件；更早记录仍保留在会话目录。')
        for event in history['events']:
            kind=event['kind'];value=event['payload']
            if kind in ('user','assistant'):
                title='你' if kind=='user' else '助手 · '+value.get('model','')+'（模型生成文字）'
                self.transcript.appendPlainText(title+'：\n'+value['text']+'\n')
            elif kind in ('tool_start','tool_result'):self.receive(kind,value)
            elif kind=='state' and value.get('status') in ('failed','cancelled'):
                self.transcript.appendPlainText('【本轮状态】'+value.get('error',value['status']))
        self.status.setText('已读取本地会话；旧助手文字不是新的研究证据。')

    def receive(self,kind,value):
        if sip.isdeleted(self):return
        if kind=='delta':
            from PyQt6.QtGui import QTextCursor
            cursor=self.transcript.textCursor();cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(value);self.transcript.setTextCursor(cursor)
        elif kind=='model':self.status.setText('当前模型：'+value['provider']+' / '+value['model'])
        elif kind in ('tool_start','tool_result'):
            item=QListWidgetItem(('调用 ' if kind=='tool_start' else '完成 ' if value['result']['ok'] else '失败 ')+value['name'])
            item.setData(Qt.ItemDataRole.UserRole,value);self.tool_list.addItem(item)
            if kind=='tool_result':
                for ref in value['result'].get('evidence',[]):
                    key=digest(ref)
                    if key in self.references:continue
                    self.references[key]=ref
                    identifier=ref.get('run_id',ref.get('proposal_id',ref.get('factor_id',ref.get('job_id',''))))
                    entry=QListWidgetItem(ref['kind']+' · '+identifier)
                    entry.setData(Qt.ItemDataRole.UserRole,ref);self.evidence.addItem(entry)

    def show_tool(self,item,previous=None):
        if item:self.details.setPlainText(json.dumps(item.data(Qt.ItemDataRole.UserRole),ensure_ascii=False,indent=2))

    def save_settings(self):
        try:save_model_config(self.output,self.settings.collect());self.status.setText('已保存模型配置；没有保存 API Key。')
        except Exception as error:self.status.setText('未保存：'+str(error))

    def probe(self):
        if self.busy:return
        if not self.consent.isChecked():self.status.setText('请先确认模型数据发送目的地。');return
        try:config=self.settings.collect()
        except ValueError as error:self.status.setText(str(error));return
        key=self.settings.key.text();self.stop_event=Event();stop=self.stop_event
        self.set_busy(True);self.status.setText('正在检查连接并读取实际模型列表…')
        def done(info,error):
            if sip.isdeleted(self):return
            self.set_busy(False)
            if error:self.status.setText('连接检查未完成：'+error)
            else:
                self.settings.apply_models(info);self.details.setPlainText(json.dumps(info,ensure_ascii=False,indent=2))
                self.status.setText('连接检查完成，返回 '+str(len(info.get('models',[])))+' 个模型；列表检查不等于一次推理验收。')
            if self.close_requested:self.close()
        self.window.async_call(lambda:make_provider(config,key).probe(stop),done,guarded=False)

    def send(self):
        if self.busy:return
        if not self.consent.isChecked():self.status.setText('请先确认模型数据发送目的地。');return
        try:
            config=self.settings.collect();text=self.input.toPlainText().strip()
            if not text:raise ValueError('请输入研究问题')
        except ValueError as error:self.status.setText(str(error));return
        session=self.session_id;key=self.settings.key.text();self.stop_event=Event();stop=self.stop_event
        self.input.clear();self.set_busy(True)
        self.transcript.appendPlainText('你：\n'+text+'\n\n助手（生成中，非完成状态）：\n')
        self.status.setText('正在请求模型…')
        def done(result,error):
            if sip.isdeleted(self):return
            self.set_busy(False)
            if error:self.status.setText('未完成：'+error);self.input.setPlainText(text)
            else:
                self.select_session()
                self.status.setText('模型本轮完成；调用 '+str(result['tool_calls'])+' 次工具。研究任务状态请以实际归档为准。'
                    if result['status']=='completed' else result.get('error','本轮未完成'))
            if self.close_requested:self.close()
        self.window.async_call(lambda:self.runtime.run(session,text,config,network_allowed=True,
            api_key=key,stop=stop,emit=self.signals.event.emit),done,guarded=False)

    def stop(self):
        self.stop_event.set();self.stop_button.setEnabled(False)
        self.status.setText('已请求停止助手；HTTP 当前请求可能需等到返回或超时。已批准研究不会被取消。')

    def open_proposals(self,selected_id=None):
        if self.busy:return
        if self.data_root is None:self.status.setText('请先在工作台指定行情目录，再打开研究提案。');return
        from .agent_proposals import ProposalDialog
        identifier=selected_id if isinstance(selected_id,str) else None
        dialog=ProposalDialog(self.window,selected_id=identifier)
        self.window.show_dialog(dialog)

    def open_reference(self):
        if self.busy:return
        item=self.evidence.currentItem()
        if item is None:self.status.setText('请先选择工具返回的真实引用。');return
        ref=item.data(Qt.ItemDataRole.UserRole)
        try:
            if ref['kind']=='proposal':self.open_proposals(ref['proposal_id'])
            elif ref['kind']=='experiment':
                self.window.catalog.file(ref['run_id'],'experiment.json')
                self.hide();self.window.open_run(ref['run_id'])
            elif ref['kind']=='factor':
                self.hide();self.window.registry_page('factor',query=ref['factor_id'])
            elif ref['kind']=='job':self.hide();self.window.show_jobs()
        except Exception as error:self.status.setText('引用未打开：'+str(error))

    def closeEvent(self,event):
        if self.busy:
            self.close_requested=True;self.stop();event.ignore();return
        self.close_requested=False;self.settings.key.clear();event.accept()
