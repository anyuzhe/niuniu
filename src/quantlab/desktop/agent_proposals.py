"""Human proposal review; approval is never a model-facing tool."""
import json
from uuid import uuid4
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QPlainTextEdit,QListWidget,QListWidgetItem,QCheckBox,QPushButton,QFileDialog
from quantlab.agent.planning import parse_spec
from quantlab.agent.proposals import ProposalService
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row


class ProposalDialog(QDialog):
    def __init__(self, window, selected_id=None):
        self.requested_selection=selected_id
        super().__init__(window);self.window=window;self.selected=None;self.busy=False
        self.service=ProposalService(window.output,window.data_root);self.request_id=str(uuid4())
        self.setWindowTitle('研究提案与人工批准');self.resize(1080,860)
        box=QVBoxLayout(self)
        box.addWidget(label('草稿 → 预检 → 保存固定提案 → 人工批准 → 原任务队列。聊天助手只能生成提案，批准在此进行。','note',True))
        box.addWidget(row(button('使用原业务表单填写提案草稿',self.edit_form),
            button('导入完整策略包（不执行）',self.import_strategy_package)))
        self.draft=QPlainTextEdit();self.draft.setPlaceholderText('可用上方业务表单，或粘贴现有研究配置 JSON。')
        self.draft.setMaximumHeight(150);self.draft.setAccessibleName('研究提案草稿');box.addWidget(self.draft)
        box.addWidget(row(button('仅预检配置与预算',self.preview),button('保存待批准提案',self.create,True),button('刷新已保存提案',self.refresh)))
        self.listing=QListWidget();self.listing.setMaximumHeight(130);box.addWidget(self.listing)
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.confirm=QCheckBox('我已核对选中的已保存提案、预算和数据口径；不是批准上方未保存草稿。');box.addWidget(self.confirm)
        self.approve_button=button('批准选中提案并提交',self.approve,True)
        box.addWidget(row(self.approve_button,button('拒绝选中待批准提案',self.reject_proposal),button('查看选中提案任务状态',self.job_status)))
        self.open_button=button('在原工作台打开实际结果',self.open_result);self.run_id=None;box.addWidget(self.open_button)
        self.status=label('策略包校验不是授权；正式提案还须核对数据资格，批准时冻结实际输入字节，再交给原任务队列。','muted',True);box.addWidget(self.status)
        self.listing.currentItemChanged.connect(self.select);self.confirm.toggled.connect(self.actions)
        self.draft.textChanged.connect(self.draft_changed);self.actions();self.refresh()

    def actions(self):
        self.approve_button.setEnabled(not self.busy and self.selected is not None and self.confirm.isChecked()
            and self.selected['status'] in ('pending','approved','submitted'))
        self.open_button.setEnabled(not self.busy and self.run_id is not None)

    def draft_changed(self):
        self.request_id=str(uuid4());self.confirm.setChecked(False)

    def select(self,current=None,previous=None):
        self.selected=current.data(Qt.ItemDataRole.UserRole) if current else None
        self.confirm.setChecked(False);self.run_id=None
        if self.selected:
            self.details.setPlainText(encode(self.selected))
            e=self.selected['plan']['estimate']
            self.status.setText(f"已保存提案 {self.selected['proposal_id'][:8]} · {self.selected['status']} · {e['symbols']} 证券 / {e['calendar_days']} 自然日 / {e['leaf_studies']} 叶子研究。完整配置与限制见明细。")
        self.actions()

    def perform(self,work,done=None):
        if self.busy:return
        self.busy=True;self.confirm.setChecked(False)
        self.controls=[(b,b.isEnabled()) for b in self.findChildren(QPushButton)]
        for b,_ in self.controls:b.setEnabled(False)
        self.draft.setEnabled(False);self.listing.setEnabled(False);self.confirm.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for b,enabled in self.controls:
                if not sip.isdeleted(b):b.setEnabled(enabled)
            self.draft.setEnabled(True);self.listing.setEnabled(True);self.confirm.setEnabled(True)
            if error:self.status.setText('未完成：'+error)
            elif done:done(value)
            self.actions()
        self.window.async_call(work,finished,guarded=False)

    def render(self,records,selected_id=None):
        self.listing.clear();self.selected=None;self.run_id=None;self.confirm.setChecked(False)
        for record in records:
            item=QListWidgetItem(record['status']+' · '+record['plan']['spec'].get('question','未命名研究')+' · '+record['proposal_id'][:8])
            item.setData(Qt.ItemDataRole.UserRole,record);self.listing.addItem(item)
            if record['proposal_id']==selected_id:self.listing.setCurrentItem(item)
        self.actions()

    def refresh(self):
        selected=self.selected['proposal_id'] if self.selected else self.requested_selection
        self.perform(lambda:self.service.store.list(),lambda rows:self.render(rows,selected))

    def preview(self):
        self.listing.setCurrentRow(-1)
        text=self.draft.toPlainText()
        self.perform(lambda:self.service.preview(parse_spec(text)),lambda result:self.details.setPlainText(encode(result)))

    def create(self):
        text=self.draft.toPlainText();request_id=self.request_id
        def work():
            result=self.service.propose(request_id,parse_spec(text))
            return result,self.service.store.list()
        self.perform(work,lambda value:self.render(value[1],value[0]['proposal_id']))

    def approve(self):
        if not self.selected or not self.confirm.isChecked() or self.busy:return
        record=self.selected
        def work():
            result=self.service.approve_and_submit(record['proposal_id'],record['proposal_digest'],self.window.get_research_queue)
            return result,self.service.store.list()
        def done(value):
            result,records=value;self.render(records,record['proposal_id'])
            self.status.setText('原任务队列：'+result['job']['job_id']+' · '+result['job']['status']+'；可在原“运行任务”中取消或恢复。')
        self.perform(work,done)

    def reject_proposal(self):
        if not self.selected:return
        record=self.selected
        def work():
            self.service.store.reject(record['proposal_id'],record['proposal_digest'])
            return self.service.store.list()
        self.perform(work,lambda records:self.render(records,record['proposal_id']))

    def job_status(self):
        if not self.selected:return
        record=self.selected
        self.listing.setCurrentRow(-1)
        def done(value):
            self.details.setPlainText(encode(value));self.run_id=value['data'].get('run_id') if value['ok'] else None
            self.status.setText('任务状态：'+value['data']['status'] if value['ok'] else '尚无可读取的任务日志；提案保存不等于已运行。')
        self.perform(lambda:ReadOnlyResearchAPI(self.window.output).call('get_job',{'job_id':record['job_id']}),done)

    def open_result(self):
        if self.run_id:self.hide();self.window.open_run(self.run_id)

    def apply_strategy_package(self, package):
        if self.busy:return
        from quantlab.trading.strategy_package import compile_strategy
        compiled=compile_strategy(package)
        self.listing.setCurrentRow(-1);self.selected=None;self.run_id=None
        self.draft.setPlainText(encode(compiled['spec']))
        self.details.setPlainText(encode(compiled))
        self.confirm.setChecked(False);self.actions()
        self.status.setText('策略包已载入草稿：'+compiled['package_hash']+'；未保存、未批准、未执行。')

    def import_strategy_package(self):
        if self.busy:return
        path,_=QFileDialog.getOpenFileName(self,'导入完整策略包','','JSON (*.json)')
        if not path:return
        try:
            from pathlib import Path
            from quantlab.agent.strategy_package_cli import _read_package
            self.apply_strategy_package(_read_package(Path(path)))
        except (ValueError,TypeError,KeyError,OSError) as error:
            self.status.setText('策略包未导入：'+str(error))

    def edit_form(self):
        from .experiment import ExperimentDialog
        dialog=ExperimentDialog(self.window);dialog.setWindowTitle('填写研究提案草稿（不运行）')
        dialog.submit_button.clicked.disconnect();dialog.submit_button.setEnabled(True)
        dialog.submit_button.setText('填入提案草稿（不提交任务）')
        def collect():
            try:
                spec=dialog.collect();self.service.preview(spec)
                self.draft.setPlainText(encode(spec));dialog.accept()
            except Exception as error:dialog.status.setText('提案预检未通过：'+str(error))
        dialog.submit_button.clicked.connect(collect)
        dialog.exec();self.raise_();self.activateWindow()
