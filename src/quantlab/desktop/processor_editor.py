"""Ordered preprocessing choices over PipelineConfig, with explicit training dates."""
from copy import deepcopy
import json
from pathlib import Path
from PyQt6.QtCore import QDate,Qt
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QComboBox,QCheckBox,QDateEdit,
    QListWidget,QDoubleSpinBox,QDialogButtonBox,QFileDialog)
from .widgets import label,row,button

METHODS={'replace_inf':'无穷值转缺失','fill_na':'填充缺失值','winsorize':'训练期分位截尾','robust_zscore':'训练期稳健标准化','clip':'固定边界截断','cs_rank':'截面排名','cs_zscore':'截面标准化','industry_neutralization':'行业中性化','size_neutralization':'市值中性化','neutralization':'行业与市值联合中性化'}

class ProcessorDialog(QDialog):
    def __init__(self,parent,value,start,end):
        super().__init__(parent);self.setWindowTitle('因子预处理');self.resize(800,680);self.result_value=None
        self.original=deepcopy(value);self.records={};self.steps=deepcopy(value.get('steps',[])) if isinstance(value,dict) else ([{'method':value}] if value else [])
        box=QVBoxLayout(self);self.enabled=QCheckBox('启用因子预处理');self.enabled.setChecked(value is not None);box.addWidget(self.enabled)
        self.list=QListWidget();box.addWidget(self.list,1);form=QFormLayout();box.addLayout(form)
        self.method=QComboBox()
        for key,title in METHODS.items():self.method.addItem(title,key)
        self.lower=QDoubleSpinBox();self.upper=QDoubleSpinBox()
        for c in (self.lower,self.upper):c.setRange(-1e15,1e15);c.setDecimals(8)
        self.median=QCheckBox('由训练期中位数填充');self.median.setChecked(True)
        form.addRow('处理方法',self.method);form.addRow('下限 / 填充值',self.lower);form.addRow('上限',self.upper);form.addRow(self.median)
        box.addWidget(row(button('添加处理步骤',self.add),button('更新所选步骤',self.update_step),button('移除步骤',self.remove),button('上移',lambda:self.move(-1)),button('下移',lambda:self.move(1))))
        self.auto_fit=QCheckBox('训练日期跟随留出或滚动窗口');self.auto_fit.setChecked(not isinstance(value,dict) or not value.get('fit_start'))
        self.start=QDateEdit(start);self.end=QDateEdit(end)
        for c,k in ((self.start,'fit_start'),(self.end,'fit_end')):
            c.setDisplayFormat('yyyy-MM-dd');c.setCalendarPopup(True)
            if isinstance(value,dict) and value.get(k):c.setDate(QDate.fromString(str(value[k]),'yyyy-MM-dd'))
        form.addRow(self.auto_fit);form.addRow('训练开始',self.start);form.addRow('训练结束',self.end)
        self.auto_fit.toggled.connect(self.fit_controls);self.fit_controls()
        box.addWidget(row(button('载入历史行业资料',lambda:self.load_records('industry_events')),button('载入每日市值资料',lambda:self.load_records('size_events'))))
        self.status=label('处理顺序由上到下；行业、市值资料须包含生效时间、可用时间与来源。缺资料的样本不会补成已知。','note',True);box.addWidget(self.status)
        if isinstance(value,dict):self.records={k:deepcopy(value[k]) for k in ('industry_events','size_events') if k in value}
        self.list.currentRowChanged.connect(self.select);self.method.currentIndexChanged.connect(self.method_controls);self.render();self.method_controls()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.finish);buttons.rejected.connect(self.reject);box.addWidget(buttons)
        for control in self.findChildren(QComboBox):control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def fit_controls(self):
        for c in (self.start,self.end):c.setEnabled(not self.auto_fit.isChecked())
    def method_controls(self):
        key=self.method.currentData();self.lower.setEnabled(key in ('winsorize','clip','fill_na'));self.upper.setEnabled(key in ('winsorize','clip'));self.median.setEnabled(key=='fill_na')
    def select(self,index):
        if not 0<=index<len(self.steps):return
        v=self.steps[index];self.method.setCurrentIndex(self.method.findData(v['method']));self.lower.setValue(v.get('lower',v.get('value',.01)));self.upper.setValue(v.get('upper',.99));self.median.setChecked('value' not in v)
    def render(self):
        current=self.list.currentRow();self.list.blockSignals(True);self.list.clear()
        for s in self.steps:
            extra='；'.join(('下限' if k=='lower' else '上限' if k=='upper' else '填充值')+' '+str(v) for k,v in s.items() if k!='method')
            self.list.addItem(METHODS[s['method']]+(' · '+extra if extra else ''))
        self.list.blockSignals(False)
        if self.steps:self.list.setCurrentRow(min(max(current,0),len(self.steps)-1))
    def step(self):
        key=self.method.currentData();v={'method':key}
        if key in ('winsorize','clip'):v.update(lower=self.lower.value(),upper=self.upper.value())
        if key=='fill_na' and not self.median.isChecked():v['value']=self.lower.value()
        return v
    def add(self):self.steps.append(self.step());self.enabled.setChecked(True);self.render();self.list.setCurrentRow(len(self.steps)-1)
    def update_step(self):
        i=self.list.currentRow()
        if i>=0:self.steps[i]=self.step();self.render()
    def remove(self):
        i=self.list.currentRow()
        if i>=0:self.steps.pop(i);self.render()
    def move(self,delta):
        i=self.list.currentRow()
        if 0<=i+delta<len(self.steps):self.steps[i],self.steps[i+delta]=self.steps[i+delta],self.steps[i];self.render();self.list.setCurrentRow(i+delta)
    def load_records(self,key):
        path,_=QFileDialog.getOpenFileName(self,'选择历史行业资料' if key=='industry_events' else '选择每日市值资料','','JSON (*.json);;Parquet (*.parquet)')
        if not path:return
        try:
            if path.endswith('.parquet'):
                import polars as pl
                from quantlab.storage.codec import encode
                records=json.loads(encode(pl.read_parquet(path).to_dicts()))
            else:records=json.loads(Path(path).read_text())
            from quantlab.data.industry import IndustryHistory
            from quantlab.processing.neutralization import SizeHistory
            (IndustryHistory if key=='industry_events' else SizeHistory)(records)
            self.records[key]=records;self.status.setText(f'已载入 {len(records)} 条；保存时嵌入本次实验并保留来源时间。')
        except (ValueError,TypeError,OSError,KeyError) as error:self.status.setText('资料未通过：'+str(error))
    def finish(self):
        from quantlab.processing.pipeline import PipelineConfig
        try:
            value=None
            if self.enabled.isChecked():
                if len(self.steps)==1 and self.steps[0]['method'] in ('cs_rank','cs_zscore') and not isinstance(self.original,dict):value=self.steps[0]['method']
                else:
                    value={**self.records,'steps':deepcopy(self.steps)}
                    if not self.auto_fit.isChecked():value.update(fit_start=self.start.date().toString('yyyy-MM-dd'),fit_end=self.end.date().toString('yyyy-MM-dd'))
                    PipelineConfig(**value)
        except (ValueError,TypeError) as error:self.status.setText('预处理未通过：'+str(error));return
        self.result_value=value;self.accept()
