"""Native tree editor preserving the existing nested sequence grammar."""
from copy import deepcopy
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QTreeWidget,QTreeWidgetItem,QComboBox,QCheckBox,QSpinBox,QDialogButtonBox,QListWidget,QListWidgetItem
from quantlab.sequence.specification import normalize_steps
from .widgets import button,row,label


class SequenceEditor(QDialog):
    def __init__(self,parent,steps,sources,names):
        super().__init__(parent);self.setWindowTitle('编辑事件步骤与嵌套组');self.resize(800,700)
        self.sources=sources;self.names=names;self.result_steps=None
        box=QVBoxLayout(self);self.tree=QTreeWidget();self.tree.setHeaderLabels(['步骤 / 组','可选','组超时（秒）']);box.addWidget(self.tree,1)
        self.event=QComboBox()
        for source in sources:self.event.addItem(names.get(source,source),source)
        self.optional=QCheckBox('此步骤或组可选');self.timeout=QSpinBox();self.timeout.setRange(0,31536000);self.timeout.setSpecialValueText('继承外层约束')
        self.invalidators=QListWidget();self.invalidators.setMaximumHeight(100)
        for source in sources:
            item=QListWidgetItem(names.get(source,source));item.setData(Qt.ItemDataRole.UserRole,source);item.setCheckState(Qt.CheckState.Unchecked);self.invalidators.addItem(item)
        form=QFormLayout();box.addLayout(form);form.addRow('事件',self.event);form.addRow(self.optional);form.addRow('组独立超时',self.timeout);form.addRow('组内失效事件',self.invalidators)
        box.addWidget(row(button('添加同级事件',lambda:self.add(False)),button('添加同级组',lambda:self.add(True)),button('添加组内事件',lambda:self.add(False,True)),button('添加子组',lambda:self.add(True,True))))
        box.addWidget(row(button('应用所选属性',self.apply),button('上移',lambda:self.move(-1)),button('下移',lambda:self.move(1)),button('删除所选',self.remove)))
        self.status=label('选择节点编辑属性；组最多嵌套四层，总计 2–12 个事件，首尾必选。','muted',True);box.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.finish);buttons.rejected.connect(self.reject);box.addWidget(buttons)
        self.tree.currentItemChanged.connect(self.selected)
        for step in deepcopy(steps):self.append(self.tree.invisibleRootItem(),step)
        self.tree.expandAll()
        if self.tree.topLevelItemCount():self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def append(self,parent,step):
        value={'event':step} if isinstance(step,str) else dict(step)
        children=value.pop('steps',None)
        if children is not None:value['group']=True
        node=QTreeWidgetItem();node.setData(0,Qt.ItemDataRole.UserRole,value);parent.addChild(node);self.render(node)
        for child in children or []:self.append(node,child)
        return node

    def render(self,node):
        value=node.data(0,Qt.ItemDataRole.UserRole)
        node.setText(0,'顺序组' if value.get('group') else self.names.get(value['event'],value['event']))
        node.setText(1,'可选' if value.get('optional') else '必选');node.setText(2,str(value.get('timeout_seconds','继承')) if value.get('group') else '—')

    def selected(self,node,previous=None):
        if node is None:return
        value=node.data(0,Qt.ItemDataRole.UserRole);group=value.get('group',False)
        self.event.setEnabled(not group);self.timeout.setEnabled(group);self.invalidators.setEnabled(group)
        self.event.setCurrentIndex(self.event.findData(value.get('event')));self.optional.setChecked(value.get('optional',False));self.timeout.setValue(value.get('timeout_seconds',0))
        for i in range(self.invalidators.count()):
            item=self.invalidators.item(i);item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in value.get('invalidators',[]) else Qt.CheckState.Unchecked)

    def apply(self):
        node=self.tree.currentItem()
        if node is None:return
        old=node.data(0,Qt.ItemDataRole.UserRole);value={'group':True} if old.get('group') else {'event':self.event.currentData()}
        if self.optional.isChecked():value['optional']=True
        if old.get('group'):
            invalid=[self.invalidators.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.invalidators.count()) if self.invalidators.item(i).checkState()==Qt.CheckState.Checked]
            if invalid and not self.timeout.value():self.status.setText('组内失效事件需要指定独立超时。');return False
            if self.timeout.value():value['timeout_seconds']=self.timeout.value()
            if invalid:value['invalidators']=invalid
        node.setData(0,Qt.ItemDataRole.UserRole,value);self.render(node);return True

    def add(self,group,inside=False):
        current=self.tree.currentItem();root=self.tree.invisibleRootItem()
        if inside:
            if current is None or not current.data(0,Qt.ItemDataRole.UserRole).get('group'):self.status.setText('请先选择一个顺序组。');return
            parent=current
        else:parent=current.parent() if current and current.parent() else root
        node=self.append(parent,{'steps':[]} if group else self.sources[0]);self.tree.setCurrentItem(node);parent.setExpanded(True)

    def remove(self):
        node=self.tree.currentItem()
        if node:
            parent=node.parent() or self.tree.invisibleRootItem();parent.takeChild(parent.indexOfChild(node))

    def move(self,delta):
        node=self.tree.currentItem()
        if node:
            parent=node.parent() or self.tree.invisibleRootItem();index=parent.indexOfChild(node)
            if 0<=index+delta<parent.childCount():parent.takeChild(index);parent.insertChild(index+delta,node);self.tree.setCurrentItem(node)

    def steps(self):
        def value(node):
            data=dict(node.data(0,Qt.ItemDataRole.UserRole))
            if data.pop('group',False):data['steps']=[value(node.child(i)) for i in range(node.childCount())]
            return data['event'] if set(data)=={'event'} else data
        return [value(self.tree.topLevelItem(i)) for i in range(self.tree.topLevelItemCount())]

    def finish(self):
        if self.apply() is False:return
        try:steps=self.steps();normalize_steps(steps,self.sources)
        except (ValueError,TypeError) as error:self.status.setText(str(error));return
        self.result_steps=steps;self.accept()
