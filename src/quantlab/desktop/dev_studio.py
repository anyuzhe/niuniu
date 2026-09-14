"""P10 Dev Studio host UI. No model-facing merge or push capability."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog,QFormLayout,QHBoxLayout,QLineEdit,QPlainTextEdit,
    QSpinBox,QTableWidgetItem,QVBoxLayout,QWidget)

from quantlab.devstudio.service import DevStudioError,DevStudioService
from quantlab.devstudio.runtime import DevAgentRuntime,DevRuntimeError
from .widgets import button,label,row,table,raw


def repo_root():
    return Path(__file__).resolve().parents[3]


class DevTaskCreateDialog(QDialog):
    def __init__(self,window,service):
        super().__init__(window);self.window=window;self.service=service;self.created=None
        self.setWindowTitle('新建 DevTask');self.resize(760,720);box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.title=QLineEdit();form.addRow('任务标题',self.title)
        self.request=QPlainTextEdit();self.request.setMaximumHeight(150);form.addRow('开发需求',self.request)
        self.criteria=QPlainTextEdit();self.criteria.setPlaceholderText('每行一条验收标准');self.criteria.setMaximumHeight(120);form.addRow('验收标准',self.criteria)
        self.paths=QPlainTextEdit();self.paths.setPlaceholderText('每行一个 repo 相对路径，例如 src/quantlab/devstudio');self.paths.setMaximumHeight(100);form.addRow('允许写路径',self.paths)
        self.tests=QPlainTextEdit('[]');self.tests.setPlaceholderText('JSON 数组，例如 [["python","-m","unittest","tests.test_x"]]');self.tests.setMaximumHeight(100);form.addRow('冻结测试命令',self.tests)
        self.parallel=QSpinBox();self.parallel.setRange(1,3);self.parallel.setValue(3);form.addRow('最大并行 Subagent',self.parallel)
        self.notes=QPlainTextEdit();self.notes.setMaximumHeight(80);form.addRow('备注',self.notes)
        self.status=label('创建时冻结当前 main HEAD，并建立独立 git worktree。allowed_paths 不能为空。','note',True);box.addWidget(self.status)
        box.addWidget(row(button('创建 DevTask',self.save,True),button('取消',self.reject)))

    def payload(self):
        tests=json.loads(self.tests.toPlainText().strip() or '[]')
        return {'title':self.title.text().strip(),'request':self.request.toPlainText().strip(),
            'acceptance_criteria':[x.strip() for x in self.criteria.toPlainText().splitlines() if x.strip()],
            'allowed_paths':[x.strip() for x in self.paths.toPlainText().splitlines() if x.strip()],
            'test_commands':tests,'max_parallel_subagents':self.parallel.value(),'notes':self.notes.toPlainText().strip()}

    def save(self):
        try:self.created=self.service.create_task(self.payload())
        except (DevStudioError,ValueError,json.JSONDecodeError) as exc:self.status.setText(f'{getattr(exc,"code","INVALID")}: {exc}');return
        self.accept()


class DevMergeDialog(QDialog):
    def __init__(self,window,service,task):
        super().__init__(window);self.window=window;self.service=service;self.task=task;self.result=None
        self.setWindowTitle('Human Merge Gate');self.resize(680,300);box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.message=QLineEdit('feat: '+task['spec']['title']);form.addRow('Commit message',self.message)
        self.confirm=QLineEdit();self.confirm.setPlaceholderText('输入 MERGE');form.addRow('确认文本',self.confirm)
        self.status=label('只合并到本地 '+task['base_branch']+'；不会自动 push。main HEAD 必须仍等于任务 base SHA。','note',True);box.addWidget(self.status)
        box.addWidget(row(button('确认合并',self.merge,True),button('取消',self.reject)))
    def merge(self):
        if self.confirm.text().strip()!='MERGE':self.status.setText('必须准确输入 MERGE 才能执行 Human Merge。');return
        try:self.result=self.service.human_merge(self.task['task_id'],self.message.text().strip(),confirmed=True)
        except DevStudioError as exc:self.status.setText(f'{exc.code}: {exc}');return
        self.accept()


class DevStudioWidget(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.service=None;self.records=[];self.busy=False
        box=QVBoxLayout(self);self.status=label('正在初始化 Dev Studio…','muted',True)
        try:self.service=DevStudioService(window.output,repo_root())
        except DevStudioError as exc:self.status.setText(f'Dev Studio 不可用：{exc.code}: {exc}')
        box.addWidget(row(button('刷新',self.reload,True),button('＋ DevTask',self.new_task),button('运行 Main + Subagents',self.run_cycle),
            button('查看 Diff',self.show_diff),button('Human Merge',self.merge),button('清理已合并 Worktree',self.cleanup),self.status))
        self.table=table(['状态','标题','Subtasks','Tests','Reviewer','Main verdict','Base SHA','更新时间'],[])
        box.addWidget(self.table,1)
        box.addWidget(label('Main/Explorer/Tester/Reviewer 默认只读；只有 Implementer 的 lease_paths 可写。模型无 shell/commit/push/merge 工具。Human Merge 后仍需人工决定是否 push。','note',True))
        self.reload()

    def selected(self):
        row_index=self.table.currentRow()
        return self.records[row_index] if 0<=row_index<len(self.records) else None

    def set_busy(self,value,text=''):
        self.busy=value
        if text:self.status.setText(text)

    def reload(self):
        if not self.service:return
        try:self.records=self.service.list()
        except Exception as exc:self.status.setText(str(exc));return
        rows=[]
        for task in self.records:
            reviewer=next((s for s in reversed(task['subtasks']) if s['spec']['role']=='REVIEWER' and s.get('result')),None)
            rows.append([task['state'],task['spec']['title'],f"{sum(s['status']=='DONE' for s in task['subtasks'])}/{len(task['subtasks'])}",
                f"{sum(bool(t.get('passed')) for t in task['test_runs'])}/{len(task['spec']['test_commands'])}",
                (reviewer.get('result') or {}).get('verdict','—') if reviewer else '—',
                (task.get('main_acceptance') or {}).get('verdict','—'),task['base_sha'][:10],task['updated_at'].replace('T',' ')[:19]])
        self.table.setRowCount(len(rows));self.table.setColumnCount(8);self.table.setHorizontalHeaderLabels(['状态','标题','Subtasks','Tests','Reviewer','Main verdict','Base SHA','更新时间'])
        for r,values in enumerate(rows):
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value)))
        self.status.setText(f'DevTask {len(rows)} · 自动 merge=否 · 自动 push=否')

    def new_task(self):
        if not self.service or self.busy:return
        dialog=DevTaskCreateDialog(self.window,self.service);dialog.accepted.connect(self.reload);self.window.show_dialog(dialog)

    def run_cycle(self):
        task=self.selected()
        if not task or self.busy:return
        self.set_busy(True,'正在运行 Main / 动态 Subagents…')
        def done(value,error):
            self.set_busy(False,error or ('完成：'+value['state']));self.reload()
        self.window.async_call(lambda:DevAgentRuntime(self.service).run_cycle(task['task_id']),done,False)

    def show_diff(self):
        task=self.selected()
        if not task:return
        try:value=self.service.diff(task['task_id'])
        except DevStudioError as exc:self.status.setText(f'{exc.code}: {exc}');return
        dialog=QDialog(self.window);dialog.setWindowTitle(task['spec']['title']+' · DevTask Diff');dialog.resize(1000,760);layout=QVBoxLayout(dialog)
        layout.addWidget(label('Changed: '+', '.join(value['changed_files']) if value['changed_files'] else 'Changed: none','note',True));layout.addWidget(raw(value),1)
        self.window.show_dialog(dialog)

    def merge(self):
        task=self.selected()
        if not task:return
        if task['state']!='READY_FOR_HUMAN':self.status.setText('只有 READY_FOR_HUMAN 的 DevTask 可进入 Human Merge。');return
        dialog=DevMergeDialog(self.window,self.service,task);dialog.accepted.connect(self.reload);self.window.show_dialog(dialog)

    def cleanup(self):
        task=self.selected()
        if not task or self.busy:return
        if task['state']!='MERGED':self.status.setText('只有 MERGED DevTask 可清理 worktree。');return
        try:self.service.cleanup(task['task_id'])
        except DevStudioError as exc:self.status.setText(f'{exc.code}: {exc}');return
        self.reload()


__all__=['DevStudioWidget','DevTaskCreateDialog','DevMergeDialog','repo_root']
