"""Frozen theory-study split, rolling schedule and sensitivity-input selection."""
from copy import deepcopy
from PyQt6.QtCore import QDate,Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QDateEdit,QSpinBox,QComboBox,QCheckBox,QDialogButtonBox
from quantlab.app import default_registry
from quantlab.storage.codec import encode
import json
from .widgets import label,button,row
from .grid_editor import GridDialog

class TheoryDialog(QDialog):
    def __init__(self,parent,params,value,start,end):
        super().__init__(parent);self.setWindowTitle('理论全流程研究计划');self.resize(800,580);self.result_value=None
        self.params=deepcopy(params);self.value=deepcopy(value or {});self.grid=deepcopy(self.value.get('grid',{}))
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form);days=max(3,start.daysTo(end))
        self.train=QDateEdit(start.addDays(days//2));self.valid=QDateEdit(start.addDays(days*3//4))
        for c,key in ((self.train,'train_end'),(self.valid,'valid_end')):
            c.setDisplayFormat('yyyy-MM-dd');c.setCalendarPopup(True)
            if key in self.value.get('split',{}):c.setDate(QDate.fromString(self.value['split'][key],'yyyy-MM-dd'))
        form.addRow('留出训练结束日期',self.train);form.addRow('留出验证结束日期',self.valid)
        self.lengths={}
        for key,title,v in [('train_days','滚动训练自然日',days//2),('valid_days','滚动验证自然日',days//4),('test_days','滚动测试自然日',days//4)]:
            c=QSpinBox();c.setRange(1,10000);c.setValue(self.value.get('schedule',{}).get(key,max(1,v)));self.lengths[key]=c;form.addRow(title,c)
        self.expanding=QCheckBox('滚动窗口保留历史训练起点');self.expanding.setChecked(self.value.get('schedule',{}).get('expanding',False));form.addRow(self.expanding)
        self.source=QComboBox();self.definitions={v['definition']['factor_id']:v for v in json.loads(encode(default_registry().describe()))}
        for alias,spec in params.get('inputs',{}).items():self.source.addItem(self.definitions[spec['factor_id']]['definition']['name_cn']+' · '+alias,alias)
        if self.value.get('input'):self.source.setCurrentIndex(self.source.findData(self.value['input']))
        form.addRow('参数敏感性研究对象',self.source);form.addRow(button('配置固定参数候选值',self.edit_grid));self.source.currentIndexChanged.connect(self.change_source)
        self.audit=QCheckBox('保存每个理论分量的审计');self.audit.setChecked(self.value.get('audit_components',True));form.addRow(self.audit)
        self.status=label('一次计划执行分量拆解、组合消融、留出验证、滚动验证和固定参数敏感性。提交前固定配置，结果不会自动选择最佳参数。','note',True);box.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.finish);buttons.rejected.connect(self.reject);box.addWidget(buttons)
        for control in self.findChildren(QComboBox):control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def change_source(self):self.grid={}
    def edit_grid(self):
        alias=self.source.currentData()
        if alias is None:self.status.setText('请先配置至少两个输入的条件或评分组合。');return
        spec=self.params['inputs'][alias];dialog=GridDialog(self,self.definitions[spec['factor_id']],self.grid)
        if dialog.exec():self.grid=dialog.result_value
        self.raise_();self.activateWindow()
    def finish(self):
        from quantlab.experiments.theory_study import TheoryStudyPlan
        try:
            if len(self.params.get('inputs',{}))<2 or self.source.currentData() is None:raise ValueError('理论研究需要至少两个组合输入')
            if not self.grid:raise ValueError('请配置参数敏感性的固定候选值')
            result={'split':{'train_end':self.train.date().toString('yyyy-MM-dd'),'valid_end':self.valid.date().toString('yyyy-MM-dd')},'schedule':{**{k:c.value() for k,c in self.lengths.items()},'expanding':self.expanding.isChecked()},'input':self.source.currentData(),'grid':self.grid,'audit_components':self.audit.isChecked()}
            TheoryStudyPlan.parse(result)
        except (ValueError,TypeError) as error:self.status.setText('计划未通过：'+str(error));return
        self.result_value=result;self.accept()
