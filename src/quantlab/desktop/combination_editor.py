"""Native factor inputs, score weights and nested boolean conditions."""
from copy import deepcopy
import json
from quantlab.storage.codec import encode
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QComboBox,QDoubleSpinBox,QTreeWidget,
    QTreeWidgetItem,QListWidget,QListWidgetItem,QDialogButtonBox)
from quantlab.app import default_registry
from .widgets import label,button,row
from .research_config import ParameterDialog

OPS=[('大于','gt'),('大于等于','ge'),('小于','lt'),('小于等于','le'),('等于','eq'),('不等于','ne')]

class CombinationDialog(QDialog):
    def __init__(self,parent,factor_id,value):
        super().__init__(parent);self.setWindowTitle('条件与评分组合');self.resize(900,780 if factor_id=='COMB.CONDITION' else 490)
        self.registry=default_registry();self.factor_id=factor_id
        self.value=deepcopy(self.registry.get(factor_id,'1.0.0').parameters(value));self.result_value=None
        self.definitions={v['definition']['factor_id']:v for v in json.loads(encode(self.registry.describe())) if not v['definition']['factor_id'].startswith('COMB.')}
        box=QVBoxLayout(self);box.setAlignment(Qt.AlignmentFlag.AlignTop);box.addWidget(label('从注册因子选择输入；评分为原始因子值乘权重求和，条件组合支持全部、任一及取反。','note',True))
        self.sources=QComboBox()
        for key,d in self.definitions.items():self.sources.addItem(d['definition']['name_cn']+' · '+key,key)
        box.addWidget(row(self.sources,button('添加因子输入',self.add_input)))
        self.inputs=QListWidget();self.inputs.setMaximumHeight(150);box.addWidget(self.inputs)
        self.weight=QDoubleSpinBox();self.weight.setRange(-1e9,1e9);self.weight.setDecimals(8)
        self.weight.setAccessibleName('评分权重')
        box.addWidget(row(button('设置所选因子参数',self.parameters),button('移除所选输入',self.remove_input),label('评分权重'),self.weight))
        self.weight.setEnabled(factor_id=='COMB.SCORE');self.weight.valueChanged.connect(self.set_weight)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['条件','比较','阈值']);box.addWidget(self.tree,1)
        self.kind=QComboBox()
        for title,key in [('因子比较','leaf'),('全部满足','all'),('任一满足','any'),('条件取反','not')]:self.kind.addItem(title,key)
        self.alias=QComboBox();self.op=QComboBox()
        for title,key in OPS:self.op.addItem(title,key)
        self.threshold=QDoubleSpinBox();self.threshold.setRange(-1e15,1e15);self.threshold.setDecimals(10)
        self.threshold.setAccessibleName('条件阈值')
        form=QFormLayout();form.addRow('条件类型',self.kind);form.addRow('输入因子',self.alias);form.addRow('比较方式',self.op);form.addRow('比较阈值',self.threshold)
        self.rules_box=row();self.rules_box.layout().addLayout(form);box.addWidget(self.rules_box)
        self.rule_buttons=row(button('应用所选条件',self.apply_rule),button('添加子条件',self.add_rule),button('移除条件',self.remove_rule));box.addWidget(self.rule_buttons)
        for control in (self.tree,self.rules_box,self.rule_buttons):control.setVisible(factor_id=='COMB.CONDITION')
        self.status=label('每个输入分别设置权重；不会隐式标准化，任一输入缺失则评分缺失。' if factor_id=='COMB.SCORE' else '修改输入后请核对条件；每个输入必须被条件使用。','muted',True);box.addWidget(self.status)
        self.inputs.currentRowChanged.connect(self.selected_input);self.tree.currentItemChanged.connect(self.selected_rule)
        self.kind.currentIndexChanged.connect(self.rule_controls)
        self.refresh_inputs()
        if 'rule' in self.value:self.append_rule(self.tree.invisibleRootItem(),self.value['rule']);self.tree.expandAll();self.tree.setCurrentItem(self.tree.topLevelItem(0))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.finish);buttons.rejected.connect(self.reject);box.addWidget(buttons)
        for control in self.findChildren(QComboBox):control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def refresh_inputs(self):
        previous=self.inputs.currentItem().data(Qt.ItemDataRole.UserRole) if self.inputs.currentItem() else None
        self.inputs.clear();self.alias.clear()
        for alias,spec in self.value['inputs'].items():
            name=self.definitions[spec['factor_id']]['definition']['name_cn']+' · '+alias
            item=QListWidgetItem(name);item.setData(Qt.ItemDataRole.UserRole,alias);self.inputs.addItem(item);self.alias.addItem(name,alias)
            if alias==previous:self.inputs.setCurrentItem(item)
        if self.inputs.currentRow()<0 and self.inputs.count():self.inputs.setCurrentRow(0)
        if self.tree.currentItem():self.selected_rule(self.tree.currentItem())

    def selected_input(self,index):
        item=self.inputs.item(index)
        if item is None:return
        alias=item.data(Qt.ItemDataRole.UserRole);self.weight.blockSignals(True);self.weight.setValue(self.value.get('weights',{}).get(alias,1));self.weight.blockSignals(False)

    def set_weight(self,value):
        item=self.inputs.currentItem()
        if item and 'weights' in self.value:self.value['weights'][item.data(Qt.ItemDataRole.UserRole)]=value

    def add_input(self):
        i=1
        while 'input_'+str(i) in self.value['inputs']:i+=1
        alias='input_'+str(i);key=self.sources.currentData();d=self.definitions[key]
        self.value['inputs'][alias]={'factor_id':key,'version':d['definition']['version'],'parameters':deepcopy(d['defaults'])}
        if 'weights' in self.value:self.value['weights'][alias]=1
        self.refresh_inputs();self.inputs.setCurrentRow(self.inputs.count()-1)

    def remove_input(self):
        item=self.inputs.currentItem()
        if item is None:return
        alias=item.data(Qt.ItemDataRole.UserRole);self.value['inputs'].pop(alias);self.value.get('weights',{}).pop(alias,None);self.refresh_inputs()

    def parameters(self):
        item=self.inputs.currentItem()
        if item is None:return
        spec=self.value['inputs'][item.data(Qt.ItemDataRole.UserRole)]
        editor=ParameterDialog(self,self.definitions[spec['factor_id']],spec['parameters'])
        if editor.exec():spec['parameters']=editor.result_value
        self.raise_();self.activateWindow()

    def append_rule(self,parent,rule):
        node=QTreeWidgetItem();parent.addChild(node)
        if 'input' in rule:node.setData(0,Qt.ItemDataRole.UserRole,deepcopy(rule));node.setText(0,rule['input']);node.setText(1,dict((v,k) for k,v in OPS).get(rule['op'],rule['op']));node.setText(2,str(rule['value']))
        else:
            kind=next(iter(rule));node.setData(0,Qt.ItemDataRole.UserRole,{'kind':kind});node.setText(0,{'all':'全部满足','any':'任一满足','not':'条件取反'}[kind])
            for child in ([rule[kind]] if kind=='not' else rule[kind]):self.append_rule(node,child)
        return node

    def rule_controls(self):
        for control in (self.alias,self.op,self.threshold):control.setEnabled(self.kind.currentData()=='leaf')

    def selected_rule(self,node,previous=None):
        if node is None:return
        rule=node.data(0,Qt.ItemDataRole.UserRole);self.kind.setCurrentIndex(self.kind.findData(rule.get('kind','leaf')))
        self.alias.setCurrentIndex(self.alias.findData(rule.get('input')));self.op.setCurrentIndex(max(0,self.op.findData(rule.get('op','gt'))));self.threshold.setValue(rule.get('value',0));self.rule_controls()

    def apply_rule(self):
        node=self.tree.currentItem()
        if node is None:return True
        kind=self.kind.currentData()
        if kind=='leaf':
            if node.childCount():self.status.setText('先移除子条件再改为因子比较。');return False
            if not self.alias.currentData():self.status.setText('请为条件选择有效输入。');return False
            old=node.data(0,Qt.ItemDataRole.UserRole) or {}
            threshold=self.threshold.value()
            if 'value' in old and round(old['value'],10)==threshold:threshold=old['value']
            rule={'input':self.alias.currentData(),'op':self.op.currentData(),'value':threshold}
            node.setData(0,Qt.ItemDataRole.UserRole,rule);node.setText(0,self.alias.currentText());node.setText(1,self.op.currentText());node.setText(2,str(rule['value']))
        else:
            if kind=='not' and node.childCount()>1:self.status.setText('取反只能有一个子条件。');return False
            node.setData(0,Qt.ItemDataRole.UserRole,{'kind':kind});node.setText(0,self.kind.currentText());node.setText(1,'');node.setText(2,'')
        return True

    def add_rule(self):
        if self.apply_rule() is False:return
        parent=self.tree.currentItem() or self.tree.invisibleRootItem()
        if parent is not self.tree.invisibleRootItem() and 'kind' not in (parent.data(0,Qt.ItemDataRole.UserRole) or {}):self.status.setText('请选择“全部满足”“任一满足”或“条件取反”再添加子条件。');return
        if not self.value['inputs']:self.status.setText('请先添加因子输入。');return
        node=self.append_rule(parent,{'input':next(iter(self.value['inputs'])),'op':'gt','value':0});parent.setExpanded(True);self.tree.setCurrentItem(node)

    def remove_rule(self):
        node=self.tree.currentItem()
        if node:
            parent=node.parent() or self.tree.invisibleRootItem();parent.takeChild(parent.indexOfChild(node))

    def rule(self,node):
        data=node.data(0,Qt.ItemDataRole.UserRole)
        if 'kind' not in data:return deepcopy(data)
        children=[self.rule(node.child(i)) for i in range(node.childCount())]
        if data['kind']=='not':
            if len(children)!=1:raise ValueError('取反必须且只能包含一个条件')
            return {'not':children[0]}
        return {data['kind']:children}

    def finish(self):
        try:
            value=deepcopy(self.value)
            if self.factor_id=='COMB.CONDITION':
                if self.apply_rule() is False:return
                if self.tree.topLevelItemCount()!=1:raise ValueError('条件必须有一个总入口')
                value['rule']=self.rule(self.tree.topLevelItem(0))
            self.result_value=self.registry.get(self.factor_id,'1.0.0').parameters(value)
        except (ValueError,TypeError,KeyError) as error:self.status.setText('组合未通过：'+str(error));return
        self.accept()
