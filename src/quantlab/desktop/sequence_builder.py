"""Native drag-and-drop editor for the existing ordered event engine."""
import json
from pathlib import Path
from uuid import uuid4
from PyQt6.QtCore import Qt,QMimeData,QPointF
from PyQt6.QtGui import QColor,QPen,QBrush,QDrag
from PyQt6.QtWidgets import (QWidget,QHBoxLayout,QVBoxLayout,QListWidget,QGraphicsView,
    QGraphicsScene,QGraphicsRectItem,QGraphicsTextItem,QGraphicsItem,QSpinBox,QCheckBox,QFileDialog,QComboBox,QLineEdit)
from quantlab.factors.sequences import CustomOrderedSequence
from quantlab.sequence.specification import normalize_steps
from quantlab.factors.chan_sequence import ChanOrderedSequence
from .widgets import Card,label,button,row,raw

NAMES={'EVT.BREAKOUT_HIGH':'前高收盘突破','EVT.FAILED_BREAKOUT_LOW':'前低突破失败','EVT.FAILED_BREAKOUT_HIGH':'前高突破失败'}

NAMES.update(dict(zip(ChanOrderedSequence.SOURCES,('确认中枢形成','中枢延续','向上离开中枢','向下离开中枢'))))

class Library(QListWidget):
    def startDrag(self,actions):
        if not self.currentItem():return
        mime=QMimeData();mime.setText(self.currentItem().data(Qt.ItemDataRole.UserRole))
        drag=QDrag(self);drag.setMimeData(mime);drag.exec(Qt.DropAction.CopyAction)

class Node(QGraphicsRectItem):
    def __init__(self,source,index):
        super().__init__(0,0,176,100);self.source=source
        self.setBrush(QBrush(QColor('#102331')));self.setPen(QPen(QColor('#aa8129'),1.5))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable|QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        event=source if isinstance(source,str) else source['event']
        suffix='（可选）' if isinstance(source,dict) and source.get('optional') else ''
        text=QGraphicsTextItem(f'{index+1:02}  {NAMES[event]}{suffix}\n\n{event}',self);text.setDefaultTextColor(QColor('#edf4fb'));text.setTextWidth(162);text.setPos(6,5)
    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        self.scene().views()[0].reorder()

class Canvas(QGraphicsView):
    def __init__(self,change):
        super().__init__();self.setScene(QGraphicsScene(self));self.setAcceptDrops(True);self.nodes=[];self.change=change
        self.setMinimumHeight(260);self.setStyleSheet('background:#0a1721;border:1px solid #23384a;')
    def render(self,steps):
        self.scene().clear();self.nodes=[]
        for i,source in enumerate(steps):
            node=Node(source,i);self.scene().addItem(node);node.setPos(24+i*215,70);self.nodes.append(node)
            if i:
                x=24+i*215;pen=QPen(QColor('#f6b72f'),2)
                self.scene().addLine(x-38,120,x-5,120,pen);self.scene().addLine(x-12,115,x-5,120,pen);self.scene().addLine(x-12,125,x-5,120,pen)
        self.setSceneRect(0,0,max(620,len(steps)*215+30),250)
    def reorder(self):
        if not getattr(self,'grouped',False):self.change([n.source for n in sorted(self.nodes,key=lambda n:n.pos().x())])
    def dragEnterEvent(self,event):
        if event.mimeData().text() in NAMES:event.acceptProposedAction()
    def dragMoveEvent(self,event):
        if event.mimeData().text() in NAMES:event.acceptProposedAction()
    def dropEvent(self,event):
        if getattr(self,'grouped',False):return
        source=event.mimeData().text()
        if source not in NAMES:return
        index=max(0,min(len(self.nodes),int(self.mapToScene(event.position().toPoint()).x()/215)))
        steps=[n.source for n in self.nodes];steps.insert(index,source);self.change(steps);event.acceptProposedAction()

class SequenceBuilder(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.steps=['EVT.FAILED_BREAKOUT_LOW','EVT.BREAKOUT_HIGH']
        box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0)
        self.family=QComboBox();self.family.addItem('突破事件序列','SEQ.CUSTOM_ORDERED');self.family.addItem('缠论中枢序列','SEQ.CHAN_ORDERED');box.addWidget(self.family)
        panels=row();library=Card('事件库');library.setMaximumWidth(260);self.library=Library();self.library.setDragEnabled(True)
        from PyQt6.QtWidgets import QListWidgetItem
        for source,name in NAMES.items():
            item=QListWidgetItem(name+'\n'+source);item.setData(Qt.ItemDataRole.UserRole,source);self.library.addItem(item)
        library.add(self.library,1);library.add(button('添加所选事件',self.add));library.add(label('拖入画布添加；拖动节点改变步骤顺序。','muted',True))
        center=Card('状态流 · 拖动排序');self.canvas=Canvas(self.set_steps);center.add(self.canvas,1)
        center.add(row(button('左移',lambda:self.move(-1)),button('右移',lambda:self.move(1)),button('删除所选',self.remove),button('切换可选步骤',self.toggle_optional)))
        settings=Card('超时与失效条件');settings.setMaximumWidth(320)
        self.lookback=QSpinBox();self.lookback.setRange(1,10000);self.lookback.setValue(20)
        self.gap=QSpinBox();self.gap.setRange(1,31536000);self.gap.setValue(172800)
        settings.add(label('事件回看根数','muted'));settings.add(self.lookback);settings.add(label('相邻步骤超时（秒，严格小于）','muted'));settings.add(self.gap)
        self.timeframes=QLineEdit();self.timeframes.setPlaceholderText('留空同周期；例：5m,15m')
        self.timeframes.hide();self.timeframe_button=button('逐步骤选择 K 线周期',self.edit_timeframes);settings.add(self.timeframe_button)
        self.structure={}
        for key in ('left','right','min_separation'):
            control=QSpinBox();control.setRange(1,10000);control.setValue(3 if key=='min_separation' else 2);settings.add(label({'left':'左侧确认长度（根）','right':'右侧确认长度（根）','min_separation':'最小笔间隔（根）'}[key],'muted'));settings.add(control);self.structure[key]=control
        self.invalidators={}
        for source,name in NAMES.items():
            check=QCheckBox('取消：'+name);check.setChecked(source=='EVT.FAILED_BREAKOUT_HIGH');settings.add(check);self.invalidators[source]=check;check.toggled.connect(self.preview)
        settings.body.addStretch();panels.layout().addWidget(library);panels.layout().addWidget(center,1);panels.layout().addWidget(settings);box.addWidget(panels,2)
        self.status=label('','muted',True);box.addWidget(self.status)
        self.details=raw({});self.details.setMaximumHeight(190);box.addWidget(self.details)
        box.addWidget(row(button('编辑步骤与嵌套组',self.edit_steps_form),button('高级 JSON',self.edit_steps),button('校验序列',self.validate),button('保存草稿',self.save),button('载入草稿',self.load),button('新建序列实验',self.research,True)))
        box.addWidget(label('2–12 个展开步骤；首尾必选。通过步骤编辑器设置嵌套组、独立超时和失效事件；画布按展开步骤展示。','note',True))
        self.lookback.valueChanged.connect(self.preview);self.gap.valueChanged.connect(self.preview);self.set_steps(self.steps)
        self.timeframes.textChanged.connect(self.preview)
        self.family.currentIndexChanged.connect(self.change_family)
        for control in self.structure.values():control.valueChanged.connect(self.preview)
        self.change_family()
    def factor(self):return ChanOrderedSequence() if self.family.currentData()=='SEQ.CHAN_ORDERED' else CustomOrderedSequence()
    def change_family(self):
        from PyQt6.QtWidgets import QListWidgetItem
        factor=self.factor();params=factor.parameters({});self.library.clear()
        self.timeframes.clear();self.timeframes.setEnabled(isinstance(factor,CustomOrderedSequence));self.timeframe_button.setEnabled(isinstance(factor,CustomOrderedSequence))
        for source in factor.SOURCES:
            item=QListWidgetItem(NAMES[source]+'\n'+source);item.setData(Qt.ItemDataRole.UserRole,source);self.library.addItem(item)
        self.lookback.setEnabled(isinstance(factor,CustomOrderedSequence))
        for control in self.structure.values():control.setEnabled(isinstance(factor,ChanOrderedSequence))
        for source,check in self.invalidators.items():
            check.setVisible(source in factor.SOURCES);check.setChecked(source in params['invalidators'])
        self.gap.setValue(params['max_gap_seconds']);self.set_steps(params['steps'])
    def edit_timeframes(self):
        from PyQt6.QtWidgets import QDialog,QFormLayout,QDialogButtonBox
        try:steps,_=normalize_steps(self.steps,self.factor().SOURCES)
        except ValueError as error:self.status.setText(str(error));return
        dialog=QDialog(self);dialog.setWindowTitle('逐步骤选择周期');box=QVBoxLayout(dialog);form=QFormLayout();box.addLayout(form)
        supplied=self.parameters().get('step_timeframes',[]);controls=[]
        for i,event in enumerate(steps):
            control=QComboBox()
            for name,value in [('沿用研究周期',''),('1 分钟','1m'),('5 分钟','5m'),('15 分钟','15m'),('30 分钟','30m'),('60 分钟','60m'),('日线','1d')]:control.addItem(name,value)
            if i<len(supplied):control.setCurrentIndex(control.findData(supplied[i]))
            controls.append(control);form.addRow(str(i+1)+' · '+NAMES[event],control)
        status=label('全部沿用研究周期，或为每个步骤明确选择周期；禁止混合未指定周期。','note',True);box.addWidget(status)
        def save():
            values=[c.currentData() for c in controls]
            if any(values) and not all(values):status.setText('请为所有步骤选择周期，或全部选择沿用研究周期。');return
            self.timeframes.setText(','.join(values) if all(values) else '');dialog.accept()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(save);buttons.rejected.connect(dialog.reject);box.addWidget(buttons);dialog.exec()
        self.window.raise_();self.window.activateWindow()

    def edit_steps(self):
        from PyQt6.QtWidgets import QInputDialog
        text,ok=QInputDialog.getMultiLineText(self,'编辑顺序组','步骤数组；组使用 {"steps":[...]}，可选使用 {"event":"事件 ID","optional":true}',json.dumps(self.steps,ensure_ascii=False,indent=2))
        if not ok:return
        try:
            steps=json.loads(text);normalize_steps(steps,self.factor().SOURCES);self.set_steps(steps)
        except (ValueError,TypeError) as exc:self.status.setText('步骤错误：'+str(exc))
    def edit_steps_form(self):
        from .sequence_editor import SequenceEditor
        dialog=SequenceEditor(self,self.steps,self.factor().SOURCES,NAMES)
        if dialog.exec():self.set_steps(dialog.result_steps)
        self.window.raise_();self.window.activateWindow()
    def toggle_optional(self):
        if self.grouped():return
        i=self.selected()
        if i is None:return
        if i in (0,len(self.steps)-1):self.status.setText('首尾步骤必须为必选。');return
        steps=list(self.steps);source=steps[i]
        steps[i]={'event':source,'optional':True} if isinstance(source,str) else source['event']
        self.set_steps(steps)
    def set_steps(self,steps):
        original=list(steps)
        if any(isinstance(v,dict) and 'steps' in v for v in steps):
            flat,optional=normalize_steps(steps,self.factor().SOURCES)
            steps=[{'event':v,'optional':True} if i in optional else v for i,v in enumerate(flat)]
        if len(steps)>12:self.status.setText('最多 12 个步骤。');self.canvas.render(self.steps);return
        self.steps=original;self.canvas.render(steps)
        self.canvas.grouped=any(isinstance(v,dict) and 'steps' in v for v in original)
        if self.canvas.grouped:
            for node in self.canvas.nodes:node.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable,False)
        self.preview()
    def grouped(self):
        if any(isinstance(v,dict) and 'steps' in v for v in self.steps):
            self.status.setText('嵌套组请通过“编辑步骤与嵌套组”修改，以保留组边界、计时器和失效规则。');return True
        return False
    def add(self):
        if self.grouped():return
        item=self.library.currentItem()
        if item:self.set_steps(self.steps+[item.data(Qt.ItemDataRole.UserRole)])
    def selected(self):return next((i for i,n in enumerate(self.canvas.nodes) if n.isSelected()),None)
    def move(self,delta):
        if self.grouped():return
        i=self.selected()
        if i is not None and 0<=i+delta<len(self.steps):
            steps=list(self.steps);steps[i],steps[i+delta]=steps[i+delta],steps[i];self.set_steps(steps);self.canvas.nodes[i+delta].setSelected(True)
    def remove(self):
        if self.grouped():return
        i=self.selected()
        if i is not None:self.set_steps(self.steps[:i]+self.steps[i+1:])
    def parameters(self):
        structure={k:v.value() for k,v in self.structure.items()} if isinstance(self.factor(),ChanOrderedSequence) else {'lookback':self.lookback.value()}
        periods=[v.strip() for v in self.timeframes.text().split(',')]
        return {**structure,'steps':list(self.steps),'invalidators':[s for s,c in self.invalidators.items() if c.isChecked() and s in self.factor().SOURCES],'max_gap_seconds':self.gap.value(),**({'step_timeframes':periods} if isinstance(self.factor(),CustomOrderedSequence) and self.timeframes.text().strip() else {})}
    def preview(self):
        def describe(steps,depth=0):
            lines=[]
            for step in steps:
                if isinstance(step,dict) and 'steps' in step:
                    lines.append('  '*depth+('可选组' if step.get('optional') else '必选组')+'；超时：'+str(step.get('timeout_seconds','继承外层')))
                    lines.extend(describe(step['steps'],depth+1))
                    if step.get('invalidators'):lines.append('  '*depth+'组失效：'+'、'.join(NAMES.get(v,v) for v in step['invalidators']))
                else:
                    key=step if isinstance(step,str) else step['event'];lines.append('  '*depth+NAMES.get(key,key)+('（可选）' if isinstance(step,dict) and step.get('optional') else ''))
            return lines
        params=self.parameters();lines=describe(self.steps)
        lines+=['相邻步骤超时：'+str(params['max_gap_seconds'])+' 秒','全局失效：'+'、'.join(NAMES.get(v,v) for v in params['invalidators']),'步骤周期：'+(self.timeframes.text() or '沿用研究周期')]
        self.details.setPlainText('\n'.join(lines));self.status.setText('草稿已变更；提交前将重新校验。')
    def validate(self):
        try:result=self.factor().parameters(self.parameters());self.status.setText('序列校验通过：'+str(len(normalize_steps(result['steps'],self.factor().SOURCES)[0]))+' 步；按事件可用时间推进。');return result
        except ValueError as exc:self.status.setText('配置错误：'+str(exc));return None
    def save(self):
        params=self.validate()
        if params is None:return
        directory=self.window.output/'_sequence_drafts'
        if directory.is_symlink():self.status.setText('草稿目录不能是符号链接。');return
        try:
            directory.mkdir(exist_ok=True);path=directory/(str(uuid4())+'.json')
            path.write_text(json.dumps({'factor_id':self.family.currentData(),'version':'1.0.0','parameters':params},ensure_ascii=False,indent=2))
            self.status.setText('已保存：'+str(path))
        except OSError as exc:self.status.setText('保存失败：'+str(exc))
    def load(self):
        path,_=QFileDialog.getOpenFileName(self,'载入序列草稿',str(self.window.output/'_sequence_drafts'),'JSON (*.json)')
        if not path:return
        try:
            value=json.loads(Path(path).read_text())
            if value.get('factor_id') not in ('SEQ.CUSTOM_ORDERED','SEQ.CHAN_ORDERED') or value.get('version')!='1.0.0':raise ValueError('不是受支持的序列草稿版本')
            factor=ChanOrderedSequence() if value['factor_id']=='SEQ.CHAN_ORDERED' else CustomOrderedSequence()
            params=factor.parameters(value['parameters']);self.family.setCurrentIndex(self.family.findData(value['factor_id']))
            for key,control in self.structure.items():control.setValue(params.get(key,3 if key=='min_separation' else 2))
            self.lookback.setValue(params.get('lookback',20));self.gap.setValue(params['max_gap_seconds'])
            self.timeframes.setText(','.join(params.get('step_timeframes',[])))
            for s,c in self.invalidators.items():c.setChecked(s in params['invalidators'])
            self.set_steps(params['steps']);self.validate()
        except (ValueError,OSError,KeyError,TypeError) as exc:self.status.setText('载入失败：'+str(exc))
    def research(self):
        params=self.validate()
        if params is None:return
        from .experiment import ExperimentDialog
        definition=next(v for v in self.window.factors if v['definition']['factor_id']==self.family.currentData())
        dialog=ExperimentDialog(self.window,definition);dialog.parameters.setPlainText(json.dumps(params));dialog.audit.setChecked(True)
        dialog.question.setText('自定义有序事件序列研究');self.window.show_dialog(dialog)
