"""Human proposal review; approval is never a model-facing tool."""
import json
from pathlib import Path
from uuid import uuid4
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QPlainTextEdit,QListWidget,QListWidgetItem,QCheckBox,QPushButton,QFileDialog
from quantlab.agent.planning import parse_spec
from quantlab.agent.proposals import ProposalService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row


class ProposalDialog(QDialog):
    def __init__(self, window, selected_id=None):
        self.requested_selection=selected_id
        super().__init__(window);self.window=window;self.selected=None;self.busy=False
        self.service=ProposalService(window.output,window.data_root);self.request_id=str(uuid4())
        self.input_check=None;self._input_check_generation=0;self._input_closed=False
        self._result_generation=0;self._result_binding=None
        output_stat=self.service.output.stat()
        self._output_identity=(output_stat.st_dev,output_stat.st_ino)
        self.setWindowTitle('研究提案与人工批准');self.resize(1080,860)
        box=QVBoxLayout(self)
        box.addWidget(label('草稿 → 预检 → 保存固定提案 → 人工批准 → 原任务队列。聊天助手只能生成提案，批准在此进行。','note',True))
        box.addWidget(row(button('使用原业务表单填写提案草稿',self.edit_form),
            button('导入完整策略包（不执行）',self.import_strategy_package)))
        box.addWidget(button('策略工作台：可视化编辑 / 版本差异 / 结果对照', self.open_strategy_workspace))
        self.draft=QPlainTextEdit();self.draft.setPlaceholderText('可用上方业务表单，或粘贴现有研究配置 JSON。')
        self.draft.setMaximumHeight(150);self.draft.setAccessibleName('研究提案草稿');box.addWidget(self.draft)
        box.addWidget(row(button('仅预检配置与预算',self.preview),button('保存待批准提案',self.create,True),button('刷新已保存提案',self.refresh)))
        self.input_check_button=button('核对草稿与归档输入（只读）',self.check_inputs)
        box.addWidget(self.input_check_button)
        self.input_status=label('归档输入兼容性尚未核对；本检查不批准、不运行，也不修改草稿。','muted',True)
        box.addWidget(self.input_status)
        self.listing=QListWidget();self.listing.setMaximumHeight(130);box.addWidget(self.listing)
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.confirm=QCheckBox('我已核对选中的已保存提案、预算和数据口径；不是批准上方未保存草稿。');box.addWidget(self.confirm)
        self.approve_button=button('批准选中提案并提交',self.approve,True)
        box.addWidget(row(self.approve_button,button('拒绝选中待批准提案',self.reject_proposal),button('查看选中提案任务状态',self.job_status)))
        self.progress_button=button('跟踪选中提案任务与结果（只读）',self.open_progress)
        box.addWidget(self.progress_button)
        self.open_button=button('在原工作台打开实际结果',self.open_result);self.run_id=None;box.addWidget(self.open_button)
        self.status=label('策略包校验不是授权；正式提案还须核对数据资格，批准时冻结实际输入字节，再交给原任务队列。','muted',True);box.addWidget(self.status)
        self.listing.currentItemChanged.connect(self.select);self.confirm.toggled.connect(self.actions)
        self.draft.textChanged.connect(self.draft_changed);self.actions();self.refresh()

    def actions(self):
        self.approve_button.setEnabled(not self.busy and self.selected is not None and self.confirm.isChecked()
            and self.selected['status'] in ('pending','approved','submitted'))
        self.open_button.setEnabled(not self.busy and not self._input_closed and self.run_id is not None)
        self.progress_button.setEnabled(not self.busy and not self._input_closed and self.selected is not None)

    def draft_changed(self):
        self._clear_result_binding()
        self.request_id=str(uuid4());self.confirm.setChecked(False)
        self._input_check_generation+=1
        if self.input_check is not None:self.details.setPlainText('{}')
        self.input_check=None
        self.input_status.setText('草稿已变化；旧输入核对失效，请重新核对。')

    def select(self,current=None,previous=None):
        self._clear_result_binding()
        self._input_check_generation+=1;self.input_check=None
        self.input_status.setText('当前显示对象已变化；草稿的旧核对不适用于选中提案，请按明确草稿重新核对。')
        self.selected=current.data(Qt.ItemDataRole.UserRole) if current else None
        self.confirm.setChecked(False);self.run_id=None
        if self.selected:
            self.details.setPlainText(encode(self.selected))
            e=self.selected['plan']['estimate']
            self.status.setText(f"已保存提案 {self.selected['proposal_id'][:8]} · {self.selected['status']} · {e['symbols']} 证券 / {e['calendar_days']} 自然日 / {e['leaf_studies']} 叶子研究。完整配置与限制见明细。")
        self.actions()

    def perform(self,work,done=None,on_error=None):
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
            if error:
                self.status.setText('未完成：'+error)
                if on_error:on_error(error)
            elif done:done(value)
            self.actions()
        try:self.window.async_call(work,finished,guarded=False)
        except Exception as error:finished(None,str(error))

    def closeEvent(self,event):
        self._clear_result_binding()
        self._input_closed=True;self._input_check_generation+=1;self.input_check=None
        super().closeEvent(event)

    def reject(self):
        self._clear_result_binding()
        self._input_closed=True;self._input_check_generation+=1;self.input_check=None
        super().reject()

    def done(self,result):
        self._clear_result_binding()
        self._input_closed=True;self._input_check_generation+=1;self.input_check=None
        super().done(result)

    def check_inputs(self):
        if self.busy or self._input_closed:return
        self._clear_result_binding()
        from quantlab.data.archived_research_check import check_archived_daily_research
        text=self.draft.toPlainText();self.listing.setCurrentRow(-1)
        self.confirm.setChecked(False);self.input_check=None
        self._input_check_generation+=1;generation=self._input_check_generation
        output,root=self.window.output,self.window.data_root
        self.details.setPlainText('{}')
        if root is None or Path(output).resolve()!=self.service.output or Path(root).resolve()!=self.service.data_root:
            self.input_status.setText('原提案面板的数据根或工作空间已过期，请重新打开；未读取输入。');return
        self.input_status.setText('正在只读核对完整输入包与当前草稿；不计算因子、不保存或批准提案。')
        def current():
            return not self._input_closed and generation==self._input_check_generation and self.draft.toPlainText()==text and self.window.output==output and self.window.data_root==root
        def failed(error):
            self.input_check=None
            if not self._input_closed:self.input_status.setText('输入核对失败或已失效：'+str(error))
        def loaded(report):
            if not current():failed('草稿、工作空间或数据根已变化，忽略旧结果');return
            self.input_check=report;self.details.setPlainText(encode(report))
            if report['compatible']:
                message='当前行情输入匹配：'+report['dataset_id']+'；未检验因子预热和统计样本充分性，仍须原人工批准。'
            else:
                message='输入不匹配／未覆盖依赖：'+'；'.join(item['role']+': '+item['message'] for item in report['blockers'])
            self.input_status.setText(message);self.status.setText('输入核对完成；草稿未修改、未保存、未批准、未执行。')
        self.perform(lambda:check_archived_daily_research(root,parse_spec(text)),loaded,failed)

    def render(self,records,selected_id=None):
        self._clear_result_binding()
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
        if self.busy or self._input_closed:return
        self._clear_result_binding()
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

    def open_progress(self):
        if self.busy or self.selected is None:return
        from .proposal_progress import ProposalProgressDialog
        self.confirm.setChecked(False)
        if not self._result_context_valid():
            self.status.setText('原提案面板的工作空间已过期；请在正确工作空间重新打开。');return
        dialog=ProposalProgressDialog(self.window,self.selected['proposal_id'],
            expected_digest=self.selected['proposal_digest'])
        self.window.show_dialog(dialog)

    def _clear_result_binding(self):
        self._result_generation+=1;self._result_binding=None;self.run_id=None
        if hasattr(self,'open_button'):self.open_button.setEnabled(False)

    def _result_context_valid(self):
        if self._input_closed or getattr(self.window,'closing',False):return False
        try:
            if Path(self.window.output).resolve()!=self.service.output:return False
            info=self.service.output.stat()
            return (info.st_dev,info.st_ino)==self._output_identity
        except (OSError,RuntimeError):return False

    def _read_result_record(self, proposal_id, expected_digest, open_expected=None):
        if self.busy or self._input_closed:return
        from quantlab.agent.proposal_progress import read_proposal_progress
        from .proposal_progress import PHASES
        self._clear_result_binding();generation=self._result_generation
        self.details.setPlainText('{}')
        if not self._result_context_valid():
            self.status.setText('工作空间已变化，请重新打开提案面板；未读取或打开旧结果。');return
        self.status.setText('正在只读核对固定提案、任务、冻结清单与结果头部…')
        def failed(error):
            self._clear_result_binding()
            if not self._input_closed:
                self.details.setPlainText('{}');self.status.setText('结果回查失败：'+str(error))
        def loaded(report):
            if self._input_closed:return
            try:
                if generation!=self._result_generation:
                    raise ValueError('显示对象已变化，忽略旧结果回执')
                if not self._result_context_valid():
                    raise ValueError('工作空间已变化，忽略旧结果回执')
                if not isinstance(report,dict) or report.get('proposal_id')!=proposal_id:
                    raise ValueError('结果回执未绑定所选提案')
                proposal=report.get('proposal')
                if proposal is not None and proposal.get('proposal_digest')!=expected_digest:
                    raise ValueError('所选提案配置身份已变化，请重新核对')
                self.details.setPlainText(encode(report))
                message=PHASES.get(report.get('phase'),'结果尚不可读取')
                if report.get('incomplete'):
                    message+='；回查不完整：'+'；'.join(e['code']+': '+e['message'] for e in report['errors'])
                if report.get('can_open_result') and not report.get('incomplete') and proposal is not None:
                    run_id=report['result']['run_id']
                    if open_expected is not None and run_id!=open_expected:
                        raise ValueError('实际结果已变化，未打开原结果')
                    self.run_id=run_id
                    self._result_binding=(proposal_id,expected_digest,run_id)
                    message+='；结果头部身份已核对，尚未做完整归档验收。'
                    if open_expected is not None:
                        self.hide();self.window.open_run(run_id)
                self.status.setText(message)
            except Exception as error:failed(error)
        self.perform(lambda:read_proposal_progress(self.service.output,proposal_id),loaded,failed)

    def job_status(self):
        if self.busy or self._input_closed or not self.selected:return
        record=self.selected
        self.listing.setCurrentRow(-1)
        self._read_result_record(record['proposal_id'],record['proposal_digest'])

    def open_result(self):
        if self.busy or self._input_closed or self._result_binding is None:return
        proposal_id,expected_digest,run_id=self._result_binding
        self._read_result_record(proposal_id,expected_digest,open_expected=run_id)

    def apply_strategy_package(self, package, *, expected_compiled_hash=None):
        if self.busy:return
        from quantlab.trading.strategy_package import compile_strategy
        compiled=compile_strategy(package)
        if expected_compiled_hash is not None and compiled['compiled_spec_hash'] != expected_compiled_hash:
            raise ValueError('策略草稿或信号源码与工作台预览不同，请重新核对。')
        self.listing.setCurrentRow(-1);self.selected=None;self.run_id=None
        self.draft.setPlainText(encode(compiled['spec']))
        self.details.setPlainText(encode(compiled))
        self.confirm.setChecked(False);self.actions()
        self.status.setText('策略包已载入草稿：'+compiled['package_hash']+'；未保存、未批准、未执行。')

    def open_strategy_workspace(self):
        if self.busy or self._input_closed:return
        if not self._result_context_valid():
            self.status.setText('工作空间已变化，请重新打开提案面板；未载入旧草稿。');return
        from .strategy_workspace import StrategyWorkspaceDialog
        dialog=None
        try:
            package=None
            if self.draft.toPlainText().strip():
                spec=parse_spec(self.draft.toPlainText())
                if 'strategy_package' in spec:
                    from quantlab.workbench.jobs import prepare
                    package=prepare(spec).strategy_package['package']
            dialog=StrategyWorkspaceDialog(self,self.window,package)
            if dialog.exec():
                if not self._result_context_valid():
                    raise ValueError('工作空间已变化，未接收旧工作台草稿')
                self.apply_strategy_package(dialog.result_package,
                    expected_compiled_hash=dialog.result_compiled_hash)
        except (ValueError,TypeError,KeyError,OSError) as error:
            self.status.setText('策略工作台未应用，原草稿保留：'+str(error))
        finally:
            if dialog is not None and not sip.isdeleted(dialog):sip.delete(dialog)

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
