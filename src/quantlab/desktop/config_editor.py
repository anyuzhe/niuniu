"""Typed tree editing for existing advanced configuration contracts."""
import json
import math
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QTreeWidget,QTreeWidgetItem,QLineEdit,QComboBox,QDialogButtonBox
from .widgets import label,button,row


class ConfigEditor(QDialog):
    def __init__(self,parent,value,title='配置字段'):
        super().__init__(parent);self.setWindowTitle(title);self.resize(780,640);self.result_value=None
        box=QVBoxLayout(self);self.tree=QTreeWidget();self.tree.setHeaderLabels(['字段','类型','值']);box.addWidget(self.tree,1)
        self.key=QLineEdit();self.kind=QComboBox();self.kind.addItems(['对象','列表','文本','整数','小数','布尔','空值']);self.value=QLineEdit()
        form=QFormLayout();box.addLayout(form);form.addRow('字段名（列表内自动编号）',self.key);form.addRow('类型',self.kind);form.addRow('值（布尔填 true 或 false）',self.value)
        box.addWidget(row(button('应用字段',self.apply),button('添加子字段',self.add),button('删除字段',self.remove)))
        self.status=label('选择字段后编辑；对象和列表展开查看。运行前仍由平台校验参数含义和范围。','muted',True);box.addWidget(self.status)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);controls.accepted.connect(self.finish);controls.rejected.connect(self.reject);box.addWidget(controls)
        self.tree.currentItemChanged.connect(self.selected)
        self.root=self.append(self.tree.invisibleRootItem(),'配置',value);self.tree.expandToDepth(1);self.tree.setCurrentItem(self.root)

    def append(self,parent,key,value):
        kind='空值' if value is None else '布尔' if isinstance(value,bool) else '对象' if isinstance(value,dict) else '列表' if isinstance(value,list) else '整数' if isinstance(value,int) else '小数' if isinstance(value,float) else '文本'
        text='' if kind in ('对象','列表','空值') else str(value).lower() if kind=='布尔' else str(value)
        node=QTreeWidgetItem([str(key),kind,text]);parent.addChild(node)
        if isinstance(value,dict):
            for k,v in value.items():self.append(node,k,v)
        elif isinstance(value,list):
            for i,v in enumerate(value):self.append(node,str(i),v)
        return node

    def selected(self,node,previous=None):
        if node is None:return
        self.key.setText(node.text(0));self.kind.setCurrentText(node.text(1));self.value.setText(node.text(2))
        self.key.setEnabled(node.parent() is not None and node.parent().text(1)=='对象')

    @staticmethod
    def scalar(kind,text):
        if kind=='空值':return None
        if kind=='布尔':
            if text.lower() not in ('true','false'):raise ValueError('布尔值只能是 true 或 false。')
            return text.lower()=='true'
        if kind=='整数':return int(text)
        if kind=='小数':
            value=float(text)
            if not math.isfinite(value):raise ValueError('小数必须是有限数值。')
            return value
        return text

    def apply(self):
        node=self.tree.currentItem()
        if node is None:return True
        kind=self.kind.currentText();key=self.key.text()
        try:
            if node.childCount() and kind!=node.text(1):raise ValueError('请先移除子字段，再更改容器类型。')
            if node.parent() and node.parent().text(1)=='对象':
                if not key.strip():raise ValueError('字段名不能为空。')
                if any(node.parent().child(i) is not node and node.parent().child(i).text(0)==key for i in range(node.parent().childCount())):raise ValueError('同一对象中字段名不能重复。')
            if kind not in ('对象','列表'):self.scalar(kind,self.value.text())
        except ValueError as error:self.status.setText(str(error));return False
        if self.key.isEnabled():node.setText(0,key)
        node.setText(1,kind);node.setText(2,self.value.text() if kind not in ('对象','列表','空值') else '');return True

    def add(self):
        node=self.tree.currentItem()
        if node is None or node.text(1) not in ('对象','列表'):self.status.setText('请选择对象或列表再添加子字段。');return
        index=node.childCount();key=str(index) if node.text(1)=='列表' else 'field_'+str(index+1)
        keys={node.child(i).text(0) for i in range(node.childCount())}
        while key in keys:index+=1;key='field_'+str(index+1)
        child=self.append(node,key,'');node.setExpanded(True);self.tree.setCurrentItem(child)

    def remove(self):
        node=self.tree.currentItem()
        if node and node.parent():
            parent=node.parent();parent.takeChild(parent.indexOfChild(node))
            if parent.text(1)=='列表':
                for i in range(parent.childCount()):parent.child(i).setText(0,str(i))

    def decode(self,node=None):
        node=node or self.root;kind=node.text(1)
        if kind=='对象':return {node.child(i).text(0):self.decode(node.child(i)) for i in range(node.childCount())}
        if kind=='列表':return [self.decode(node.child(i)) for i in range(node.childCount())]
        return self.scalar(kind,node.text(2))

    def finish(self):
        if not self.apply():return
        self.result_value=self.decode();self.accept()


def edit_config(parent,control,title):
    getter=control.toPlainText if hasattr(control,'toPlainText') else control.text
    setter=control.setPlainText if hasattr(control,'setPlainText') else control.setText
    try:value=json.loads(getter())
    except ValueError as error:parent.status.setText('原配置无法解析：'+str(error));return
    dialog=ConfigEditor(parent,value,title)
    if dialog.exec():setter(json.dumps(dialog.result_value,ensure_ascii=False,indent=2))
