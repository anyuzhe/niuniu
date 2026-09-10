"""Higher-timeframe research background with registered factor controls."""
from copy import deepcopy
import json
from quantlab.storage.codec import encode
from PyQt6.QtCore import QDate,Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QComboBox,QDateEdit,QDoubleSpinBox,QCheckBox,QDialogButtonBox
from quantlab.app import default_registry
from .research_config import ParameterDialog
from .combination_editor import OPS
from .widgets import label,button

class ContextDialog(QDialog):
    def __init__(self,parent,value,start):
        super().__init__(parent);self.setWindowTitle('高周期背景条件');self.resize(760,520);self.result_value=None
        self.value=deepcopy(value or {});box=QVBoxLayout(self);self.enabled=QCheckBox('启用高周期背景筛选');self.enabled.setChecked(value is not None);box.addWidget(self.enabled)
        form=QFormLayout();box.addLayout(form);self.factor=QComboBox();self.definitions=json.loads(encode(default_registry().describe()))
        for d in self.definitions:self.factor.addItem(d['definition']['name_cn']+' · '+d['definition']['factor_id'],d['definition']['factor_id'])
        self.factor.setCurrentIndex(self.factor.findData(self.value.get('factor_id','BASE.MOMENTUM')))
        self.parameters=deepcopy(self.value.get('parameters',{}));self.factor.currentIndexChanged.connect(self.change_factor)
        self.start=QDateEdit(QDate.fromString(self.value['start'],'yyyy-MM-dd') if 'start' in self.value else start)
        self.start.setDisplayFormat('yyyy-MM-dd');self.start.setCalendarPopup(True)
        self.period=QComboBox()
        for title,key in [('日线','1d'),('60 分钟','60m'),('30 分钟','30m'),('15 分钟','15m'),('5 分钟','5m')]:self.period.addItem(title,key)
        self.period.setCurrentIndex(self.period.findData(self.value.get('timeframe','1d')))
        self.op=QComboBox()
        for title,key in OPS:self.op.addItem(title,key)
        self.op.setCurrentIndex(self.op.findData(self.value.get('op','gt')))
        self.threshold=QDoubleSpinBox();self.threshold.setRange(-1e15,1e15);self.threshold.setDecimals(10);self.threshold.setValue(self.value.get('value',0))
        for title,c in [('背景因子',self.factor),('背景起始日期',self.start),('背景周期',self.period),('比较条件',self.op),('阈值',self.threshold)]:form.addRow(title,c)
        box.addWidget(button('设置背景因子参数',self.edit_parameters));self.status=label('背景周期必须高于实验周期；只使用决策时已经收盘、已经可用的高周期数据。日线实验没有更高的已注册周期。','note',True);box.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.finish);buttons.rejected.connect(self.reject);box.addWidget(buttons)
        for control in self.findChildren(QComboBox):control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def change_factor(self):self.parameters=deepcopy(self.definitions[self.factor.currentIndex()]['defaults'])
    def edit_parameters(self):
        definition=self.definitions[self.factor.currentIndex()]
        if self.factor.currentData().startswith('COMB.'):
            from .combination_editor import CombinationDialog
            dialog=CombinationDialog(self,self.factor.currentData(),self.parameters)
        else:dialog=ParameterDialog(self,definition,self.parameters)
        if dialog.exec():self.parameters=dialog.result_value
        self.raise_();self.activateWindow()
    def finish(self):
        from quantlab.multitimeframe.config import DailyContextConfig
        try:
            result=None
            if self.enabled.isChecked():
                definition=self.definitions[self.factor.currentIndex()]['definition']
                factor=default_registry().get(self.factor.currentData(),definition['version']);parameters=factor.parameters(self.parameters)
                result={'factor_id':self.factor.currentData(),'version':definition['version'],'parameters':parameters,'start':self.start.date().toString('yyyy-MM-dd'),'timeframe':self.period.currentData(),'op':self.op.currentData(),'value':self.value.get('value',0.) if round(self.value.get('value',0.),10)==self.threshold.value() else self.threshold.value()}
                from datetime import date
                DailyContextConfig(**{**result,'start':date.fromisoformat(result['start'])})
        except (ValueError,TypeError,KeyError) as error:self.status.setText('背景条件未通过：'+str(error));return
        self.result_value=result;self.accept()
