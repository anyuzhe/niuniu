"""Parameter sweep candidates without JSON syntax."""
import re
from copy import deepcopy
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QDialogButtonBox,QScrollArea,QWidget
from .research_config import NAMES
from .widgets import label

class GridDialog(QDialog):
    def __init__(self,parent,definition,value):
        super().__init__(parent);self.setWindowTitle('参数扫描候选值');self.resize(680,520)
        if not isinstance(value,dict):raise ValueError('扫描网格必须为对象')
        self.original=deepcopy(value);self.result_value=None;self.controls={};self.types={}
        box=QVBoxLayout(self);box.addWidget(label('每项填写多个候选值，用空格或逗号分隔；开关填写“启用 禁用”，留空表示不扫描该参数。','note',True))
        page=QWidget();form=QFormLayout(page);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);box.addWidget(scroll,1)
        for key,v in definition.get('defaults',{}).items():
            if type(v) not in (int,float,str,bool):continue
            control=QLineEdit(' '.join(('启用' if n else '禁用') if type(n) is bool else str(n) for n in value.get(key,[])));control.setAccessibleName(NAMES.get(key,key));form.addRow(NAMES.get(key,key),control);self.controls[key]=control;self.types[key]=type(v)
        self.status=label('候选值的范围及组合数量在实验提交前统一校验。','muted',True);box.addWidget(self.status);box.addStretch()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.finish);buttons.rejected.connect(self.reject);box.addWidget(buttons)
    def finish(self):
        try:
            result=deepcopy(self.original)
            for key,control in self.controls.items():
                values=[s for s in re.split(r'[\s,，]+',control.text().strip()) if s]
                if values:
                    if self.types[key] is bool:
                        choices={'启用':True,'禁用':False,'是':True,'否':False,'true':True,'false':False}
                        if any(s.lower() not in choices for s in values):raise ValueError('开关候选请填写“启用 禁用”')
                        result[key]=[choices[s.lower()] for s in values]
                    else:result[key]=[self.types[key](s) for s in values]
                else:result.pop(key,None)
            if not result:raise ValueError('至少设置一个扫描参数')
        except ValueError as error:self.status.setText('候选值未通过：'+str(error));return
        self.result_value=result;self.accept()
