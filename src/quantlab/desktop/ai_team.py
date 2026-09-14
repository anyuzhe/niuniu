"""Native AI Team configuration and host-launched finite peer review."""
from threading import Event
from uuid import uuid4

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox,QComboBox,QDialog,QLineEdit,QPlainTextEdit,QScrollArea,
    QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)

from quantlab.agent.agent_memory import AgentMemoryLoader,ROLES
from quantlab.agent.model_config import load_model_config,save_model_config
from quantlab.agent.peer_review import PeerReviewService
from quantlab.agent.team_config import EFFORTS
from .business_view import BusinessDetails
from .model_settings import ModelSettings
from .widgets import button,label,row

ROLE_LABELS={'chief_researcher':'Chief Researcher','market_scanner':'Market Scanner','skeptic':'Skeptic / Risk',
    'quant_researcher':'Quant Researcher','developer':'Developer'}


class PeerReviewCreateDialog(QDialog):
    def __init__(self,window,service,on_saved):
        super().__init__(window);self.service=service;self.on_saved=on_saved;self.saved=None
        self.setWindowTitle('新建 Peer Review 请求');self.resize(760,650);box=QVBoxLayout(self)
        box.addWidget(label('这里只创建 pending 复核任务；保存不会调用任何模型。','note',True))
        self.question=QPlainTextEdit();self.question.setPlaceholderText('需要独立同行复核的问题');box.addWidget(self.question,2)
        self.context=QPlainTextEdit();self.context.setPlaceholderText('可选共享背景；不要粘贴 Chief 的结论作为第一轮锚点');box.addWidget(self.context,1)
        self.checks={}
        checks=[]
        for role in ('market_scanner','skeptic','quant_researcher'):
            control=QCheckBox(ROLE_LABELS[role]);control.setChecked(True);self.checks[role]=control;checks.append(control)
        box.addWidget(row(*checks));self.parent=QLineEdit();self.parent.setPlaceholderText('可选 parent_task_id UUID');box.addWidget(self.parent)
        self.status=label('','muted',True);box.addWidget(self.status);box.addWidget(row(button('保存 pending 请求',self.save,True),button('取消',self.reject)))

    def save(self):
        try:
            reviewers=[role for role,c in self.checks.items() if c.isChecked()]
            spec={'question':self.question.toPlainText(),'context':self.context.toPlainText(),'reviewers':reviewers,
                'parent_task_id':self.parent.text().strip() or None}
            self.saved=self.service.propose(str(uuid4()),spec)
        except Exception as exc:self.status.setText(str(exc));return
        self.on_saved();self.accept()


class PeerReviewLaunchDialog(QDialog):
    def __init__(self,window,service,task,on_done):
        super().__init__(window);self.window=window;self.service=service;self.task=task;self.on_done=on_done;self.stop_flag=Event();self.busy=False
        self.setWindowTitle('启动 Peer Review · '+task['task_id'][:8]);self.resize(900,820);box=QVBoxLayout(self)
        box.addWidget(label('第一轮 Reviewer 相互不可见；第二轮仅 Chief 综合。启动后最多两轮，不自动修改任何研究/交易状态。','note',True))
        self.settings=ModelSettings(load_model_config(window.output));scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.settings);scroll.setMaximumHeight(330);box.addWidget(scroll)
        self.details=BusinessDetails({'question':task['spec']['question'],'reviewers':task['spec']['reviewers'],'status':task['status']});box.addWidget(self.details,1)
        self.status=label('必须勾选模型发送许可后才能启动。','muted',True);box.addWidget(self.status)
        self.start_button=button('启动有限复核',self.start,True);self.stop_button=button('停止',self.stop);self.stop_button.setEnabled(False)
        box.addWidget(row(self.start_button,self.stop_button,button('关闭',self.close)))

    def set_busy(self,value):
        self.busy=value;self.settings.setEnabled(not value);self.start_button.setEnabled(not value);self.stop_button.setEnabled(value)

    def start(self):
        if self.busy:return
        try:
            cfg=self.settings.collect();key=self.settings.key.text();allowed=self.settings.allow.isChecked()
            if not allowed:raise ValueError('请先勾选模型发送许可。')
            save_model_config(self.window.output,cfg)
        except Exception as exc:self.status.setText(str(exc));return
        self.set_busy(True);self.stop_flag=Event();self.status.setText('Peer Review 正在运行；Reviewer 第一轮保持独立。')
        def done(result,error):
            if sip.isdeleted(self):return
            self.set_busy(False);self.settings.key.clear();self.on_done()
            self.status.setText(error or ('复核完成：'+result.get('stop_reason','completed')))
            if not error:self.details.setPlainText(result)
        self.window.async_call(lambda:self.service.run(self.task['task_id'],cfg,api_key=key,allow_send=True,stop=self.stop_flag),done,guarded=False)

    def stop(self):
        self.stop_flag.set();self.status.setText('已请求停止；不会启动新的 Reviewer。')


class AITeamWidget(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.service=PeerReviewService(window.output,window.data_root);self.tasks=[];self.controls={}
        box=QVBoxLayout(self);memory=AgentMemoryLoader().status()
        box.addWidget(label('Git-first Memory · '+str(memory['git_commit'] or 'unknown')[:12]+' · source='+memory['source_of_truth'],'note',True))
        self.team_table=QTableWidget(len(ROLES),4);self.team_table.setHorizontalHeaderLabels(['Role','启用','Model override','Effort override'])
        team=self.service.team.load()
        for i,role in enumerate(ROLES):
            self.team_table.setItem(i,0,QTableWidgetItem(ROLE_LABELS[role]));enabled=QCheckBox();enabled.setChecked(team['roles'][role]['enabled']);
            if role in ('chief_researcher','developer'):enabled.setEnabled(False)
            model=QLineEdit(team['roles'][role]['model']);effort=QComboBox();effort.addItem('继承','')
            for value in EFFORTS:
                if value:effort.addItem(value,value)
            effort.setCurrentIndex(max(0,effort.findData(team['roles'][role]['effort'])))
            self.team_table.setCellWidget(i,1,enabled);self.team_table.setCellWidget(i,2,model);self.team_table.setCellWidget(i,3,effort)
            self.controls[role]=(enabled,model,effort)
        box.addWidget(self.team_table);self.status=label('Role 与模型分离；Developer 在 P10 前默认关闭。','muted',True);box.addWidget(self.status)
        box.addWidget(row(button('保存 Team 配置',self.save_team),button('＋ 新建同行复核',self.new_task,True),button('Agent Scorecard',self.open_scorecard),button('刷新任务',self.reload)))
        self.table=QTableWidget();self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setHorizontalHeaderLabels(['状态','问题','Reviewers','轮数','Stop reason','创建时间']);box.addWidget(self.table,1)
        box.addWidget(row(button('启动选中 pending',self.launch,True),button('查看任务详情',self.open_task)))
        self.reload()

    def open_scorecard(self):
        from .agent_scorecard import AgentScorecardDialog
        self.window.show_dialog(AgentScorecardDialog(self.window))

    def save_team(self):
        team=self.service.team.load();team={'version':team['version'],'roles':{}}
        for role,(enabled,model,effort) in self.controls.items():
            team['roles'][role]={'enabled':enabled.isChecked(),'model':model.text().strip(),'effort':effort.currentData()}
        try:self.service.team.save(team);self.status.setText('AI Team 配置已保存；没有调用模型。')
        except Exception as exc:self.status.setText(str(exc))

    def reload(self):
        result=self.service.list();self.tasks=result['tasks'];self.table.setRowCount(len(self.tasks));self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['状态','问题','Reviewers','轮数','Stop reason','创建时间'])
        for i,task in enumerate(self.tasks):
            values=[task['status'],task['spec']['question'][:90],','.join(task['spec']['reviewers']),str(len(task.get('rounds',[]))),task.get('stop_reason') or '—',task['created_at'][:19]]
            for j,value in enumerate(values):self.table.setItem(i,j,QTableWidgetItem(value))
        self.table.resizeColumnsToContents();self.status.setText(f'Peer Review {len(self.tasks)} 项；不可读 {len(result["errors"])} 项。')

    def selected(self):
        row=self.table.currentRow();return self.tasks[row] if 0<=row<len(self.tasks) else None

    def new_task(self):
        self.window.show_dialog(PeerReviewCreateDialog(self.window,self.service,self.reload))

    def launch(self):
        task=self.selected()
        if not task:self.status.setText('请选择任务。');return
        if task['status']!='pending':self.status.setText('只有 pending 任务可以启动。');return
        self.window.show_dialog(PeerReviewLaunchDialog(self.window,self.service,task,self.reload))

    def open_task(self):
        task=self.selected()
        if not task:self.status.setText('请选择任务。');return
        dialog=QDialog(self.window);dialog.setWindowTitle('Peer Review · '+task['task_id'][:8]);dialog.resize(1000,800)
        layout=QVBoxLayout(dialog);layout.addWidget(BusinessDetails(self.service.get(task['task_id'])),1);layout.addWidget(button('关闭',dialog.close))
        self.window.show_dialog(dialog)
