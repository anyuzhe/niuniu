"""Native registered-factor Factory drafts over the existing guarded service.

Editing and preview are local/read-only. Saving only creates a pending proposal;
approval/execution and Watch promotion stay in the existing host dialog.
"""
from copy import deepcopy
from uuid import uuid4

from PyQt6 import sip
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QWidget, QScrollArea,
    QGroupBox, QLineEdit, QComboBox, QDoubleSpinBox, QCheckBox)

from quantlab.agent.alpha_factory import AlphaFactoryService, PLAN_V2, normalize_plan, candidate_ref_id
from quantlab.app import default_registry
from quantlab.storage.codec import digest, encode
from quantlab.trading.research_evidence import archive_research_reference
from .business_view import BusinessDetails
from .widgets import button, label, row, table


class FactoryPlanDialog(QDialog):
    def __init__(self, window, initial_definition=None):
        super().__init__(window)
        self.window=window;self.output=window.output;self.data_root=window.data_root
        self.epoch=getattr(window,'epoch',None);self.closed=False;self.busy=False;self.generation=0
        self.service=AlphaFactoryService(self.output,self.data_root)
        self.baseline=None;self.controls=[];self.execution=None;self.candidate_refs=[]
        self.definition=None;self.parameters={};self.prepared=None;self.saved=None;self.request_id=str(uuid4())
        self.setWindowTitle('新建 Alpha Factory · 注册因子可视化计划');self.resize(1160,920)
        box=QVBoxLayout(self)
        box.addWidget(label('选择已有基准、控制因子和候选，预览后只保存待审批提案。不会运行研究、修改数据或自动进入观察池。','note',True))
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);box.addWidget(scroll,1)
        self.name=QLineEdit();self.name.setPlaceholderText('请填写本次研究计划名称')
        layout.addWidget(row(label('计划名称'),self.name))
        sources=QGroupBox('1. 明确选择已有归档');form=QFormLayout(sources)
        self.baseline_text=label('尚未选择基准','muted',True);self.control_text=label('尚未选择控制因子（1–5项）','muted',True)
        self.execution_text=label('未选择成本后执行基准','muted',True)
        self.baseline_button=button('选择因子基准',lambda:self.pick_archive('baseline'))
        self.control_button=button('增加控制因子',lambda:self.pick_archive('control'))
        self.clear_controls_button=button('清空控制因子',self.clear_controls)
        self.execution_button=button('选择执行基准',lambda:self.pick_archive('execution'))
        form.addRow(row(self.baseline_button,self.baseline_text))
        form.addRow(row(self.control_button,self.clear_controls_button,self.control_text))
        self.require_net=QCheckBox('同时检验成本后净收益增量（需要匹配的 execution 归档）')
        form.addRow(self.require_net);form.addRow(row(self.execution_button,self.execution_text));layout.addWidget(sources)
        candidates=QGroupBox('2. 固定候选集合（1–12项，不按收益自动筛选）');cbox=QVBoxLayout(candidates)
        self.factor_text=label('尚未选择候选因子','muted',True)
        self.factor_button=button('按名称或ID选择因子',self.pick_factor)
        self.params_button=button('编辑因子参数',self.edit_parameters)
        self.candidate_name=QLineEdit();self.candidate_name.setPlaceholderText('候选名称（不改变因子身份）')
        self.add_button=button('加入候选集合',self.add_candidate)
        cbox.addWidget(row(self.factor_button,self.params_button,self.factor_text))
        cbox.addWidget(row(self.candidate_name,self.add_button))
        self.candidate_table=table(['候选名称','因子 ID','版本','固定参数'],[])
        cbox.addWidget(self.candidate_table);self.remove_button=button('移除选中候选',self.remove_candidate);cbox.addWidget(self.remove_button)
        layout.addWidget(candidates)
        rules=QGroupBox('3. 明确研究区间与固定检验规则');rform=QFormLayout(rules)
        self.train_end=QLineEdit();self.train_end.setPlaceholderText('训练截止 YYYY-MM-DD（在基准区间内）')
        self.evaluation_start=QLineEdit();self.evaluation_start.setPlaceholderText('评价起点 YYYY-MM-DD（晚于训练截止）')
        self.horizon=QComboBox();self.horizon.setPlaceholderText('从所选基准的持有期中选择')
        rform.addRow('训练截止',self.train_end);rform.addRow('评价起点',self.evaluation_start);rform.addRow('持有期（根）',self.horizon)
        self.alpha=self.ratio(0.05,0.000001,0.2);self.common_ratio=self.ratio(0.5,0.000001,1.0);self.correlation=self.ratio(0.9,0.0,1.0)
        rform.addRow('全族显著性阈值 α',self.alpha);rform.addRow('共同有限样本最小比例',self.common_ratio);rform.addRow('最大绝对信号相关',self.correlation)
        self.positive=QCheckBox('要求配对 IC 差为正');self.positive.setChecked(True);rform.addRow(self.positive)
        rform.addRow(label('这些是可编辑的筛选阈值，不代表候选有Alpha。样本、周期、价格口径与预处理沿用所选基准；不可比时原服务会拒绝。','note',True))
        layout.addWidget(rules)
        self.details=BusinessDetails({});layout.addWidget(self.details)
        self.review=QCheckBox('我已核对本次预览，保存为待审批提案（不是批准执行）');box.addWidget(self.review)
        self.preview_button=button('预检并查看完整计划',self.preview_plan,True)
        self.save_button=button('保存待审批提案',self.save_plan)
        self.open_button=button('打开人工审批',self.open_approval)
        box.addWidget(row(self.preview_button,self.save_button,self.open_button))
        self.status=label('未预览。请明确选择归档、候选、日期和持有期。','muted',True);box.addWidget(self.status)
        self.finished.connect(self._finished)
        self.inputs=[self.name,self.train_end,self.evaluation_start,self.horizon,self.alpha,self.common_ratio,self.correlation,self.positive,self.require_net]
        self.editables=[*self.inputs,self.candidate_name,self.candidate_table,self.factor_button,self.params_button,self.add_button,self.remove_button,
            self.baseline_button,self.control_button,self.clear_controls_button,self.execution_button]
        for control in (self.name,self.train_end,self.evaluation_start):control.textChanged.connect(self.invalidate)
        self.horizon.currentIndexChanged.connect(self.invalidate)
        for control in (self.alpha,self.common_ratio,self.correlation):control.valueChanged.connect(self.invalidate)
        self.positive.toggled.connect(self.invalidate);self.require_net.toggled.connect(self.invalidate);self.review.toggled.connect(self.buttons)
        if initial_definition is not None:self.set_factor(initial_definition)
        self.buttons()

    @staticmethod
    def ratio(value,minimum,maximum):
        field=QDoubleSpinBox();field.setDecimals(6);field.setRange(minimum,maximum);field.setSingleStep(.01);field.setValue(value);return field

    def valid(self):
        return (not self.closed and not sip.isdeleted(self) and not sip.isdeleted(self.window)
                and not getattr(self.window,'closing',False) and self.output==self.window.output
                and self.data_root==self.window.data_root and self.epoch==getattr(self.window,'epoch',None))

    def _finished(self,*_):self.closed=True;self.generation+=1
    def closeEvent(self,event):self._finished();super().closeEvent(event)

    def buttons(self,*_):
        usable=self.valid() and not self.busy
        for control in self.editables:control.setEnabled(usable)
        self.execution_button.setEnabled(usable and self.require_net.isChecked())
        self.params_button.setEnabled(usable and self.definition is not None)
        self.add_button.setEnabled(usable and self.definition is not None and len(self.candidate_refs)<12)
        self.preview_button.setEnabled(usable)
        self.review.setEnabled(usable and self.prepared is not None and self.saved is None)
        self.save_button.setEnabled(usable and self.prepared is not None and self.review.isChecked() and self.saved is None)
        self.open_button.setEnabled(usable and self.saved is not None)

    def invalidate(self,*_):
        self.generation+=1;self.prepared=None;self.saved=None;self.request_id=str(uuid4())
        self.review.setChecked(False);self.details.setPlainText('{}')
        self.status.setText('计划已变化，请重新预检。');self.buttons()

    def work(self,fn,done):
        if not self.valid() or self.busy:return
        generation=self.generation;self.busy=True;self.buttons()
        def finished(value,error):
            if not self.valid():return
            self.busy=False
            if generation!=self.generation:self.buttons();return
            if error:
                self.prepared=None;self.review.setChecked(False)
                self.status.setText('未完成：'+error)
            else:
                try:done(value)
                except (ValueError,TypeError,KeyError) as exc:
                    self.prepared=None;self.review.setChecked(False);self.status.setText('结果不可用：'+str(exc))
            self.buttons()
        self.window.async_call(fn,finished,guarded=False)

    @staticmethod
    def reference_text(ref):
        identity=ref['rule_identity'];scope=ref['range']
        return f"{ref.get('question') or '未命名'} · {identity.get('factor_id')}@{identity.get('factor_version')} · {scope.get('start')} → {scope.get('end')} · {ref['source']['run_id']}"

    def pick_archive(self,role):
        if not self.valid() or self.busy:return
        from .research_picker import ArchivePickerDialog
        generation=self.generation
        dialog=ArchivePickerDialog(self.window,kind='execution' if role=='execution' else 'factor',title='选择'+{'baseline':'因子基准','control':'控制因子','execution':'执行基准'}[role])
        def finished(*_):
            if self.valid() and not self.busy and generation==self.generation and dialog.result_reference is not None:
                self.use_archive(role,dialog.result_reference)
        dialog.finished.connect(finished);self.window.show_dialog(dialog)

    def use_archive(self,role,ref):
        if not self.valid() or self.busy:return
        try:
            expected='execution' if role=='execution' else 'factor'
            if ref.get('kind')!=expected or ref.get('status')!='completed':raise ValueError('只能使用对应类型的已完成归档')
            if role=='baseline':
                self.baseline=deepcopy(ref);self.baseline_text.setText(self.reference_text(ref))
                self.horizon.blockSignals(True);self.horizon.clear()
                for horizon in ref.get('horizons') or []:self.horizon.addItem(str(horizon),horizon)
                self.horizon.setCurrentIndex(-1);self.horizon.blockSignals(False)
                # Do not silently inherit old controls, dates or execution baseline.
                self.controls=[];self.control_text.setText('基准已变化，请明确重选控制因子')
                self.execution=None;self.execution_text.setText('未选择成本后执行基准')
                self.train_end.clear();self.evaluation_start.clear()
            elif role=='control':
                if len(self.controls)>=5:raise ValueError('最多5个控制因子')
                if any(r['source']['run_id']==ref['source']['run_id'] for r in self.controls):raise ValueError('控制因子不能重复')
                self.controls.append(deepcopy(ref));self.control_text.setText('\n'.join(self.reference_text(r) for r in self.controls))
            elif role=='execution':self.execution=deepcopy(ref);self.execution_text.setText(self.reference_text(ref))
            else:raise ValueError('归档角色无效')
            self.invalidate()
        except (ValueError,KeyError,TypeError) as exc:self.status.setText(str(exc))

    def clear_controls(self):
        if not self.valid() or self.busy:return
        self.controls=[];self.control_text.setText('尚未选择控制因子（1–5项）');self.invalidate()

    def pick_factor(self):
        if not self.valid() or self.busy:return
        from .research_picker import FactorPickerDialog
        generation=self.generation;dialog=FactorPickerDialog(self.window,factory_only=True)
        def finished(*_):
            if self.valid() and not self.busy and generation==self.generation and dialog.result_definition is not None:self.set_factor(dialog.result_definition)
        dialog.finished.connect(finished);self.window.show_dialog(dialog)

    def set_factor(self,definition):
        if not self.valid() or self.busy:return
        try:
            d=definition['definition'];factor=default_registry().get(d['factor_id'],d['version'])
            params=factor.parameters(deepcopy(definition.get('defaults',{})))
            candidate_ref_id({'kind':'registered_factor','factor_id':d['factor_id'],'version':d['version'],'parameters':params,'name':d['name_cn'][:120]})
            self.definition=deepcopy(definition);self.parameters=params
            self.candidate_name.setText(d['name_cn'][:120]);self.factor_text.setText(d['factor_id']+'@'+d['version']+' · '+encode(params));self.buttons()
        except (ValueError,KeyError,TypeError) as exc:self.status.setText('候选不可用：'+str(exc))

    def edit_parameters(self):
        if not self.valid() or self.busy or self.definition is None:return
        from .research_config import ParameterDialog
        current=self.definition;dialog=ParameterDialog(self,self.definition,self.parameters)
        def finished(*_):
            if self.valid() and not self.busy and self.definition is current and dialog.result_value is not None:
                self.parameters=deepcopy(dialog.result_value);d=self.definition['definition']
                self.factor_text.setText(d['factor_id']+'@'+d['version']+' · '+encode(self.parameters))
        dialog.finished.connect(finished);self.window.show_dialog(dialog)

    def add_candidate(self):
        if not self.valid() or self.busy or self.definition is None:return
        try:
            if len(self.candidate_refs)>=12:raise ValueError('最多12个候选')
            d=self.definition['definition'];ref={'kind':'registered_factor','factor_id':d['factor_id'],'version':d['version'],
                'parameters':deepcopy(self.parameters),'name':self.candidate_name.text().strip()}
            cid=candidate_ref_id(ref)
            if any(candidate_ref_id(r)==cid for r in self.candidate_refs):raise ValueError('候选ID、版本和参数相同，不可通过改名重复加入')
            self.candidate_refs.append(ref);self.render_candidates();self.invalidate()
        except (ValueError,TypeError,KeyError) as exc:self.status.setText('加入失败：'+str(exc))

    def render_candidates(self):
        from PyQt6.QtWidgets import QTableWidgetItem
        self.candidate_table.setRowCount(len(self.candidate_refs))
        for i,ref in enumerate(self.candidate_refs):
            for j,value in enumerate((ref['name'],ref['factor_id'],ref['version'],encode(ref['parameters']))):
                self.candidate_table.setItem(i,j,QTableWidgetItem(str(value)))

    def remove_candidate(self):
        if not self.valid() or self.busy:return
        index=self.candidate_table.currentRow()
        if 0<=index<len(self.candidate_refs):self.candidate_refs.pop(index);self.render_candidates();self.invalidate()

    def collect(self):
        if not self.baseline:raise ValueError('请明确选择因子基准')
        return normalize_plan({'format':PLAN_V2,'name':self.name.text().strip(),'candidate_refs':deepcopy(self.candidate_refs),
            'baseline_run_id':self.baseline['source']['run_id'],'control_run_ids':[r['source']['run_id'] for r in self.controls],
            'baseline_execution_run_id':self.execution['source']['run_id'] if self.require_net.isChecked() and self.execution else None,
            'require_net_return':self.require_net.isChecked(),'train_end':self.train_end.text().strip(),
            'evaluation_start':self.evaluation_start.text().strip(),'horizon':self.horizon.currentData(),
            'alpha':self.alpha.value(),'min_common_finite_ratio':self.common_ratio.value(),'max_abs_signal_corr':self.correlation.value(),
            'require_positive_paired_ic_difference':self.positive.isChecked()})

    def preview_plan(self):
        if not self.valid() or self.busy:return
        self.prepared=None;self.saved=None;self.review.setChecked(False);self.buttons()
        try:plan=self.collect()
        except (ValueError,TypeError,KeyError) as exc:self.status.setText('配置未完成：'+str(exc));return
        sources=[deepcopy(self.baseline),*deepcopy(self.controls)]
        if plan['require_net_return']:sources.append(deepcopy(self.execution))
        def work():
            for ref in sources:
                current=archive_research_reference(self.output,ref['source']['run_id'])
                if current['source']['fingerprint']!=ref['source']['fingerprint']:raise ValueError('已选归档在选择后变化，请重新选择')
            return self.service.preview(plan)
        def done(value):
            self.prepared=value;self.details.setPlainText(encode(value))
            self.status.setText('预检通过：'+str(len(value['candidates']))+' 个候选，'+str(value['planned_test_count'])+' 个固定检验槽位。尚未保存或执行。')
        self.work(work,done)

    def save_plan(self):
        if not self.valid() or self.busy or self.prepared is None or not self.review.isChecked() or self.saved is not None:return
        try:
            plan=self.collect()
            if plan!=self.prepared['plan']:raise ValueError('表单与预览不一致，请重新预检')
        except (ValueError,TypeError,KeyError) as exc:self.invalidate();self.status.setText(str(exc));return
        request_id=self.request_id;expected=self.prepared['prepared_digest']
        def done(value):
            self.saved=value;self.review.setChecked(False);self.details.setPlainText(encode(value))
            self.status.setText('已保存待审批提案 '+value['proposal_id']+'。0次自动执行；请到人工审批核对并提交。')
        self.work(lambda:self.service.propose(request_id,plan,expected_digest=expected),done)

    def open_approval(self):
        if not self.valid() or self.busy or self.saved is None:return
        from .alpha_factory import AlphaFactoryDialog
        self.window.show_dialog(AlphaFactoryDialog(self.window,self.saved['proposal_id']))
