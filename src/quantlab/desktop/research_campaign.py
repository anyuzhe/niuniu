"""Native builder for a fixed research pack; approval stays in ProposalDialog."""
from copy import deepcopy
from uuid import uuid4
import json
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QDoubleSpinBox,QListWidget,QPlainTextEdit,QPushButton
from quantlab.agent.proposals import ProposalService
from quantlab.agent.planning import parse_spec
from quantlab.storage.codec import encode
from .widgets import label,button,row
from .business_view import BusinessDetails


class CampaignDialog(QDialog):
    def __init__(self,window):
        super().__init__(window); self.window=window; self.nodes=[]; self.busy=False; self.request_id=str(uuid4())
        self.service=ProposalService(window.output,window.data_root)
        self.setWindowTitle('固定研究包 · 一次批准'); self.resize(1050,860)
        box=QVBoxLayout(self); form=QFormLayout(); box.addLayout(form)
        self.name=QLineEdit('固定研究包'); self.alpha=QDoubleSpinBox(); self.alpha.setRange(.001,.49); self.alpha.setDecimals(3); self.alpha.setValue(.05)
        self.policy=QComboBox(); self.policy.addItem('继续不受影响的独立节点','continue_independent'); self.policy.addItem('遇失败停止后续节点','stop')
        self.node_id=QLineEdit('node_1'); self.dependencies=QLineEdit(); self.dependencies.setPlaceholderText('留空无依赖；多个节点编号用空格分隔')
        for title,control in [('研究包名称',self.name),('固定族显著性水平',self.alpha),('失败策略',self.policy),('待添加节点编号',self.node_id),('成功前置节点',self.dependencies)]: form.addRow(title,control)
        box.addWidget(label('最多12节点。统计节点需在原表单设置 permutation，全部节点保存回放。依赖只表示运行成功，不按收益或显著性选优。','note',True))
        self.listing=QListWidget(); self.listing.setMaximumHeight(160); box.addWidget(self.listing)
        box.addWidget(row(button('用原业务表单添加节点',self.add_form),button('移除选中节点',self.remove)))
        self.raw=QPlainTextEdit(); self.raw.setMaximumHeight(130); self.raw.setPlaceholderText('可粘贴完整研究包 JSON 后载入'); box.addWidget(self.raw)
        box.addWidget(row(button('载入JSON草稿',self.import_json),button('显示当前完整计划',lambda:self.raw.setPlainText(encode(self.collect())))))
        self.details=BusinessDetails({}); box.addWidget(self.details,1)
        self.status=label('未提交研究。保存提案后仍需人工核对批准。','muted',True); box.addWidget(self.status)
        self.preview_button=button('预检整包与总预算',self.preview)
        self.save_button=button('保存并打开人工审批',self.save,True)
        box.addWidget(row(self.preview_button,self.save_button))
        self.listing.currentRowChanged.connect(self.inspect)
        self.name.textChanged.connect(self.changed); self.alpha.valueChanged.connect(self.changed); self.policy.currentIndexChanged.connect(self.changed)
    def changed(self,*_): self.request_id=str(uuid4())
    def collect(self):
        return {'mode':'campaign','question':self.name.text().strip(),'alpha':self.alpha.value(),
            'failure_policy':self.policy.currentData(),'nodes':deepcopy(self.nodes)}
    def refresh(self):
        self.listing.clear()
        for node in self.nodes:
            self.listing.addItem(node['node_id']+' ← '+(','.join(node['depends_on']) or '无依赖')+' · '+node['spec'].get('question','研究'))
        self.changed(); self.node_id.setText('node_'+str(len(self.nodes)+1))
    def inspect(self,index):
        if 0<=index<len(self.nodes): self.details.setPlainText(encode(self.nodes[index]))
    def remove(self):
        index=self.listing.currentRow()
        if index>=0: self.nodes.pop(index); self.refresh()
    def import_json(self):
        try:
            spec=parse_spec(self.raw.toPlainText()); self.service.preview(spec)
            if spec.get('mode')!='campaign': raise ValueError('请提供研究包配置')
            self.nodes=deepcopy(spec['nodes']); self.name.setText(spec['question']); self.alpha.setValue(spec['alpha'])
            self.policy.setCurrentIndex(self.policy.findData(spec['failure_policy'])); self.refresh()
        except (ValueError,KeyError,TypeError) as error: self.status.setText('草稿未载入：'+str(error))
    def add_form(self):
        from .experiment import ExperimentDialog
        from quantlab.agent.planning import preview_experiment
        key=self.node_id.text().strip(); deps=self.dependencies.text().replace(',',' ').split()
        if not key or any(n['node_id']==key for n in self.nodes): self.status.setText('请填写不同的节点编号。'); return
        if len(self.nodes)>=12: self.status.setText('最多12个节点。'); return
        dialog=ExperimentDialog(self.window); dialog.setWindowTitle('添加研究包节点（不执行）')
        dialog.submit_button.clicked.disconnect(); dialog.submit_button.setText('加入研究包'); dialog.submit_button.setEnabled(True)
        def add():
            if sip.isdeleted(self): dialog.reject(); return
            try:
                spec=dialog.collect(); preview_experiment(spec)
                if spec.get('replay') is not True: raise ValueError('研究包节点必须保存回放')
                if any(n['node_id']==key for n in self.nodes): raise ValueError('节点编号已被使用')
            except (ValueError,TypeError,KeyError) as error: dialog.status.setText(str(error)); return
            self.nodes.append({'node_id':key,'depends_on':deps,'spec':spec}); self.refresh(); dialog.accept()
        dialog.submit_button.clicked.connect(add); self.window.show_dialog(dialog)
    def perform(self,work,done):
        if self.busy:return
        self.busy=True; controls=[(c,c.isEnabled()) for c in [*self.findChildren(QPushButton),self.name,self.alpha,self.policy,self.node_id,self.dependencies,self.raw,self.listing]]
        for c,_ in controls:c.setEnabled(False)
        self.status.setText('正在核对固定研究计划…')
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for c,enabled in controls:
                if not sip.isdeleted(c):c.setEnabled(enabled)
            if error:self.status.setText('未完成：'+error)
            else:done(value)
        self.window.async_call(work,finished,guarded=False)
    def preview(self):
        spec=self.collect()
        def done(value):
            self.details.setPlainText(encode(value)); e=value['estimate']
            self.status.setText(f"预检通过：{e['nodes']}节点，{e['leaf_studies']}叶子研究，{e['planned_tests']}个固定族检验；尚未执行。")
        self.perform(lambda:self.service.preview(spec),done)
    def save(self):
        spec=self.collect(); request=self.request_id
        def done(value):
            from .agent_proposals import ProposalDialog
            self.details.setPlainText(encode(value)); self.status.setText('已保存待批准研究包；未启动任务。')
            self.window.show_dialog(ProposalDialog(self.window,selected_id=value['proposal_id']))
        self.perform(lambda:self.service.propose(request,spec),done)
