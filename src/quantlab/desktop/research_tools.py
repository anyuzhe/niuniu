"""Native entry points for existing archived residual and fixed-family studies."""
import json
from pathlib import Path
from uuid import uuid4
from PyQt6.QtCore import QDate,Qt
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QComboBox,QListWidget,QListWidgetItem,
    QDateEdit,QSpinBox,QLineEdit,QFileDialog,QTabWidget,QWidget,QPushButton,QScrollArea,QDoubleSpinBox)
from .widgets import label,button,row,raw
from .business_view import BusinessDetails

class ResearchToolsDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.registry_path=None;self.setWindowTitle('残差研究与固定检验族');self.resize(950,760)
        box=QVBoxLayout(self);tabs=QTabWidget();box.addWidget(tabs,1)
        residual=QWidget();form=QFormLayout(residual);tabs.addTab(residual,'样本外残差 IC')
        self.candidate=QComboBox();self.controls=QListWidget()
        self.controls.setStyleSheet('QListWidget::indicator {width:14px;height:14px;border:1px solid #738596;border-radius:2px;} QListWidget::indicator:checked {background:#f9ba2b;border-color:#f9ba2b;}')
        def display(record):return record['run_id'][:8]+' · '+record.get('kind','研究')+' · '+record.get('factor_id','')+' · '+record['question']
        records=window.catalog.list(kind='factor',limit=10000)['runs']
        for record in records:
            if record['status']!='completed':continue
            name=display(record);self.candidate.addItem(name,record['run_id'])
            item=QListWidgetItem(name);item.setData(Qt.ItemDataRole.UserRole,record['run_id']);item.setCheckState(Qt.CheckState.Unchecked);self.controls.addItem(item)
        self.train_end=QDateEdit(QDate.currentDate().addYears(-2));self.train_end.setCalendarPopup(True);self.train_end.setDisplayFormat('yyyy-MM-dd')
        self.horizon=QSpinBox();self.horizon.setRange(1,10000)
        form.addRow('候选因子归档',self.candidate);form.addRow('控制因子（勾选 1–20 项）',self.controls);form.addRow('训练结束',self.train_end);form.addRow('持有期',self.horizon)
        self.residual_button=button('运行样本外残差研究',self.residual,True);form.addRow(self.residual_button)
        form.addRow(label('使用相同快照与股票池的已完成因子归档；仅训练期拟合控制投影。系统会核验来源，不能将残差 IC 当成成交收益。','note',True))
        trial=QWidget();layout=QVBoxLayout(trial);tabs.addTab(trial,'固定检验族 / Holm')
        self.draft_trials=[];self.draft_specs=[];self.frozen_specs=None;self.draft_name=QLineEdit('固定研究检验族');self.draft_alpha=QDoubleSpinBox();self.draft_alpha.setRange(.001,.5);self.draft_alpha.setDecimals(3);self.draft_alpha.setValue(.05)
        layout.addWidget(row(label('计划名称'),self.draft_name,label('显著性水平'),self.draft_alpha))
        self.draft_list=QListWidget();self.draft_list.setMaximumHeight(110);layout.addWidget(self.draft_list)
        layout.addWidget(row(button('表单添加研究计划',self.add_trial_form),button('删除计划项',self.remove_trial),button('冻结以上计划',self.freeze_trials)))
        layout.addWidget(button('提交选定的冻结研究计划',self.run_frozen_trials))
        layout.addWidget(row(button('导入计划并冻结登记',self.create_registry),button('选择已有登记',self.load_registry)))
        self.registry_label=label('尚未选择登记','muted',True);layout.addWidget(self.registry_label)
        self.trial_id=QComboBox();self.run=QComboBox()
        for record in window.catalog.list(limit=10000)['runs']:self.run.addItem(display(record),record['run_id'])
        layout.addWidget(label('计划项编号','muted'));layout.addWidget(self.trial_id);layout.addWidget(label('待绑定实验归档','muted'));layout.addWidget(self.run)
        self.bind_button=button('绑定选定结果',self.bind);self.report_button=button('生成固定族 Holm 报告',self.report)
        layout.addWidget(button('刷新可绑定归档',self.refresh_runs))
        layout.addWidget(row(self.bind_button,self.report_button));layout.addWidget(label('本地登记不证明数据未被查看；不可检验和未运行项保留名额。绑定后不能改绑其他结果。','note',True));layout.addStretch()
        stability=QWidget();stable_box=QVBoxLayout(stability);tabs.addTab(stability,'参数与子样本验证')
        from .comparison_editor import ComparisonEditor
        self.stability_editor=ComparisonEditor(window,'stability',self.run_stability_plan);stable_box.addWidget(self.stability_editor)
        stable_box.addWidget(label('参数差异使用共同证券／日期；证券子样本与沪深验证使用不重叠证券组和相同日期；时间子样本分别填写两个不重叠时段，可以使用相同证券，截短标签自动剔除。预先设定容许差异，校正后的完整区间落在范围内才支持等效；未拒绝差异不等于等效。','note',True))
        stable_box.addWidget(button('导入并运行稳定性计划',self.stability));stable_box.addStretch()
        returns=QWidget();return_box=QVBoxLayout(returns);tabs.addTab(returns,'净收益固定检验族')
        self.return_editor=ComparisonEditor(window,'returns',self.run_return_plan);return_box.addWidget(self.return_editor)
        return_box.addWidget(label('先冻结比较清单，再检验已完成成交账户的配对日净收益差；失败项保留名额。源账户已存在，不能称为策略事前预注册。','note',True))
        return_box.addWidget(button('导入并运行净收益比较计划',self.return_family));return_box.addStretch()
        for index in (2,3):
            page=tabs.widget(index);title=tabs.tabText(index);tabs.removeTab(index)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);tabs.insertTab(index,scroll,title)
        self.output=BusinessDetails({});box.addWidget(self.output,1)
        # Enter while choosing an archive must not launch the first file dialog.
        for control in self.findChildren(QPushButton):control.setAutoDefault(False)
    def perform(self,work,done=None):
        if getattr(self,'busy',False):return
        self.busy=True
        self.busy_controls=[(control,control.isEnabled()) for control in self.findChildren(QPushButton)]
        for control,_ in self.busy_controls:control.setEnabled(False)
        self.output.setPlainText('正在执行…')
        def finished(result,error):
            self.busy=False
            for control,enabled in self.busy_controls:control.setEnabled(enabled)
            self.output.setPlainText(error if error else json.dumps(result,ensure_ascii=False,indent=2,default=str))
            if not error and done:done(result)
        self.window.async_call(work,finished,guarded=False)
    def stability(self):
        path,_=QFileDialog.getOpenFileName(self,'固定参数比较计划',str(self.window.output),'JSON (*.json)')
        if not path:return
        try:plan=json.loads(Path(path).read_text())
        except (OSError,ValueError) as error:self.output.setPlainText(str(error));return
        self.run_stability_plan(plan)
    def run_stability_plan(self,plan):
        from quantlab.experiments.stability import run_stability
        output=self.window.output
        self.perform(lambda:run_stability(plan,output),lambda result:self.window.open_run(result['run_id']))
    def return_family(self):
        path,_=QFileDialog.getOpenFileName(self,'固定净收益比较计划',str(self.window.output),'JSON (*.json)')
        if not path:return
        try:plan=json.loads(Path(path).read_text())
        except (OSError,ValueError) as error:self.output.setPlainText(str(error));return
        self.run_return_plan(plan)
    def run_return_plan(self,plan):
        from quantlab.experiments.return_family import run_return_family
        output=self.window.output;self.perform(lambda:run_return_family(plan,output),lambda result:self.window.open_run(result['run_id']))
    def residual(self):
        from quantlab.experiments.residual import run_residual
        candidate=self.candidate.currentData();controls=[self.controls.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.controls.count()) if self.controls.item(i).checkState()==Qt.CheckState.Checked]
        if not candidate or not controls or candidate in controls:self.output.setPlainText('请选择候选与不同的控制因子。');return
        train_end=self.train_end.date().toPyDate();horizon=self.horizon.value();root=self.window.output
        self.perform(lambda:run_residual(root/candidate,[root/v for v in controls],train_end,root,horizon),lambda result:self.window.open_run(result['run_id']))
    def select_registry(self,path):
        from quantlab.experiments.trial_registry import _load_registry
        registry=_load_registry(path);self.registry_path=Path(path);self.registry_label.setText(str(path));self.trial_id.clear()
        for trial in registry['plan']['trials']:self.trial_id.addItem(trial['trial_id'])
        self.frozen_specs=None
        if (Path(path)/'submissions.json').exists():
            from quantlab.workbench.trial_submission import load_submissions
            self.frozen_specs=(Path(path),load_submissions(path))
    def load_registry(self):
        path=QFileDialog.getExistingDirectory(self,'选择包含 registry.json 的目录',str(self.window.output))
        if not path:return
        try:self.select_registry(path)
        except (ValueError,OSError,KeyError,TypeError) as exc:self.output.setPlainText(str(exc))
    def create_registry(self):
        from quantlab.experiments.trial_registry import create_registry
        path,_=QFileDialog.getOpenFileName(self,'选择检验计划 JSON',str(self.window.output),'JSON (*.json)')
        if not path:return
        try:plan=json.loads(Path(path).read_text())
        except (ValueError,OSError) as exc:self.output.setPlainText(str(exc));return
        destination=self.window.output/'_trial_registries'/str(uuid4())
        self.perform(lambda:create_registry(plan,destination),lambda result:self.select_registry(destination))
    def add_trial_form(self):
        from .experiment import ExperimentDialog
        from quantlab.workbench.jobs import prepare
        from quantlab.storage.codec import encode
        from dataclasses import asdict
        from quantlab.statistics.permutation import PermutationConfig
        from quantlab.experiments.trial_registry import _validate_plan
        dialog=ExperimentDialog(self.window);dialog.setWindowTitle('添加固定族研究计划（不运行）')
        dialog.submit_button.setText('加入计划');dialog.submit_button.setEnabled(True);dialog.submit_button.clicked.disconnect()
        def add():
            try:
                spec=dialog.collect()
                if not spec.get('permutation'):spec['permutation']=asdict(PermutationConfig())
                from quantlab.workbench.trial_submission import planned_trial
                trial=planned_trial(spec,'trial_'+str(uuid4())[:8])
                _validate_plan({'name':self.draft_name.text(),'alpha':self.draft_alpha.value(),'trials':self.draft_trials+[trial]})
            except (ValueError,TypeError,KeyError) as error:dialog.status.setText('计划错误：'+str(error));return
            self.draft_trials.append(trial);self.draft_specs.append(spec);self.draft_list.addItem(trial['trial_id']+' · '+spec['question']);dialog.accept()
        dialog.submit_button.clicked.connect(add);dialog.exec();self.raise_();self.activateWindow()
    def remove_trial(self):
        index=self.draft_list.currentRow()
        if index>=0:self.draft_trials.pop(index);self.draft_specs.pop(index);self.draft_list.takeItem(index)
    def freeze_trials(self):
        from quantlab.experiments.trial_registry import create_registry
        if not self.draft_trials:self.output.setPlainText('请先添加研究计划。');return
        plan={'name':self.draft_name.text(),'alpha':self.draft_alpha.value(),'trials':[{k:v for k,v in t.items() if k!='layout'} for t in self.draft_trials]}
        destination=self.window.output/'_trial_registries'/str(uuid4())
        specs=json.loads(json.dumps(self.draft_specs))
        def work():
            from quantlab.workbench.trial_submission import save_submissions
            result=create_registry(plan,destination);save_submissions(destination,specs);return result
        self.perform(work,lambda result:self.select_registry(destination))
    def run_frozen_trials(self):
        if self.frozen_specs is None or self.registry_path!=self.frozen_specs[0]:self.output.setPlainText('此登记没有可执行表单配置；请选取客户端冻结的计划，或绑定已有实验归档。');return
        if not self.window.data_root:self.output.setPlainText('尚未配置行情数据目录。');return
        from quantlab.workbench.jobs import JobQueue
        window=self.window;entries=self.frozen_specs[1]
        def run():
            if window.queue is None:window.queue=JobQueue(window.output,window.data_root)
            return {'jobs':[window.queue.submit(job_id,spec) for job_id,spec in entries]}
        self.perform(run)
    def bind(self):
        from quantlab.experiments.trial_registry import bind_result
        if self.registry_path is None or not self.run.currentData():self.output.setPlainText('先选择登记与实验。');return
        registry=self.registry_path;trial=self.trial_id.currentText();artifact=self.window.output/self.run.currentData()
        self.perform(lambda:bind_result(registry,trial,artifact))
    def refresh_runs(self):
        current=self.run.currentData();self.run.clear()
        for record in self.window.catalog.list(limit=10000)['runs']:
            self.run.addItem(record['run_id'][:8]+' · '+record.get('kind','研究')+' · '+record['question'],record['run_id'])
        index=self.run.findData(current)
        if index>=0:self.run.setCurrentIndex(index)
    def report(self):
        from quantlab.experiments.trial_registry import report_registry
        if self.registry_path is None:self.output.setPlainText('先选择登记。');return
        registry=self.registry_path;destination=self.window.output/'_trial_reports'/str(uuid4())
        from quantlab.storage.trial_reproduction import archive_registry
        output=self.window.output
        def work():
            report_registry(registry,destination)
            return archive_registry(destination,output)
        self.perform(work,lambda result:self.window.open_run(result['run_id']))
