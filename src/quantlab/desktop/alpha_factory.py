"""Host approval, synchronization and watchlist promotion for Alpha Factory."""
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QCheckBox,QLineEdit,QPushButton,QTabWidget,QWidget,QTableWidgetItem
from quantlab.agent.alpha_factory import AlphaFactoryService
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row,table,fmt


TEST_NAMES={'residual_ic':'样本外残差 IC','net_return_increment':'成本后净收益增量'}
CHECK_NAMES={'common_finite_ratio':'共同样本比例','signal_correlation':'信号相关',
             'paired_ic_direction':'配对IC方向','residual_increment':'残差信息增量','net_return_increment':'净收益增量'}


def factory_test_rows(state):
    """Project stored frozen slots without recomputation, winner selection or writes."""
    prepared=state.get('prepared') or {}
    names={r['candidate_id']:r.get('name',r['candidate_id']) for r in prepared.get('candidates',[])}
    grouped={}
    for result in state.get('tests',[]):grouped.setdefault((result.get('candidate_id'),result.get('id')),[]).append(result)
    decisions={r.get('candidate_id'):r for r in state.get('decisions',[])}
    rows=[]
    for slot in prepared.get('planned_tests',[]):
        cid=slot['candidate_id'];test_id=slot['id'];results=grouped.get((cid,test_id),[])
        result=results[0] if len(results)==1 else {}
        checks=decisions.get(cid,{}).get('checks',{})
        blockers=[CHECK_NAMES.get(k,k) for k,v in checks.items() if v is False]
        if len(results)>1:status='结果重复，需复核'
        else:status=result.get('status') or '尚无同步结果'
        decision=decisions.get(cid,{})
        recommendation=('仅建议人工观察' if decision.get('recommended_for_watchlist') is True
                        else '不建议晋级' if decision.get('recommended_for_watchlist') is False else '未评估')
        rows.append({'candidate_id':cid,'candidate_name':names.get(cid,cid),'test_id':test_id,
                     'test_name':TEST_NAMES.get(test_id,test_id),'status':status,
                     'estimate':result.get('estimate'),'p_value':result.get('p_value'),'p_holm':result.get('p_holm'),
                     'recommendation':recommendation,'blockers':blockers,'error':result.get('error'),
                     'run_id':result.get('run_id')})
    return rows


class AlphaFactoryDialog(QDialog):
    def __init__(self,window,selected_id=None):
        super().__init__(window);self.window=window;self.busy=False;self.current=None
        self.output=window.output;self.data_root=window.data_root;self.epoch=getattr(window,'epoch',None);self.closed=False
        self.finished.connect(lambda *_:setattr(self,'closed',True))
        self.service=AlphaFactoryService(window.output,window.data_root);self.selected_id=selected_id
        self.setWindowTitle('安全 Alpha Factory · 固定候选与全族检验');self.resize(1120,860)
        box=QVBoxLayout(self)
        box.addWidget(label('模型只能冻结Factory提案。这里人工一次批准后才提交原研究队列；运行中不能增删候选。进入Watchlist需要第二次人工确认。','note',True))
        self.proposals=QComboBox();self.reload_button=button('刷新Factory',self.reload)
        self.new_button=button('新建可视化计划',self.new_plan)
        box.addWidget(row(self.proposals,self.reload_button,self.new_button))
        self.confirm=QCheckBox('我已核对候选集合、基准/控制因子、样本区间、全Factory Holm检验族和筛选规则，确认提交。')
        box.addWidget(self.confirm)
        self.submit_button=button('批准并提交固定Factory',self.submit,True)
        self.sync_button=button('同步Factory结果',self.sync)
        self.open_button=button('打开Factory结果',self.open_result)
        self.report_button=button('研究报告 / AI解读',self.open_report)
        box.addWidget(row(self.submit_button,self.sync_button,self.open_button,self.report_button))
        self.candidates=QComboBox();self.watch_name=QLineEdit();self.watch_name.setPlaceholderText('观察池名称')
        self.promote_confirm=QCheckBox('我已复核完整Factory证据，确认只把当前推荐候选加入观察池；不创建自动刷新授权。')
        self.promote_button=button('人工加入Watchlist',self.promote)
        box.addWidget(row(self.candidates,self.watch_name));box.addWidget(self.promote_confirm);box.addWidget(self.promote_button)
        self.promoted_watches=QComboBox();self.watch_button=button('打开已加入的观察池',self.open_promoted_watch)
        box.addWidget(row(self.promoted_watches,self.watch_button))
        self.promoted_watches.currentIndexChanged.connect(self.buttons)
        tabs=QTabWidget();summary=QWidget();summary_box=QVBoxLayout(summary)
        self.summary_text=label('尚未读取固定计划。','muted',True);summary_box.addWidget(self.summary_text)
        self.test_table=table(['候选','固定检验','归档状态','估计值','原始 p','Holm p','观察建议','未过条件 / 错误'],[])
        summary_box.addWidget(self.test_table,1)
        self.evidence_button=button('打开所选检验证据',self.open_test_result);summary_box.addWidget(self.evidence_button)
        summary_box.addWidget(label('显示最后保存/同步的结果，不自动更新任务。空值表示未获得，不按零处理；失败槽位保留。观察建议不等于Alpha或交易许可。','note',True))
        self.details=BusinessDetails({});tabs.addTab(summary,'候选与检验摘要');tabs.addTab(self.details,'完整冻结计划与状态');box.addWidget(tabs,1)
        self.test_rows=[];self.test_table.itemSelectionChanged.connect(self.buttons)
        self.status=label('未选择Factory。','muted',True);box.addWidget(self.status)
        self.proposals.currentIndexChanged.connect(self.select);self.confirm.toggled.connect(self.buttons)
        self.promote_confirm.toggled.connect(self.buttons);self.candidates.currentIndexChanged.connect(self.buttons)
        self.buttons();self.reload()
    def render_summary(self,state):
        state=state or {};prepared=state.get('prepared') or {};self.test_rows=factory_test_rows(state)
        self.test_table.blockSignals(True);self.test_table.setRowCount(len(self.test_rows))
        for i,result in enumerate(self.test_rows):
            values=[result['candidate_name'],result['test_name'],result['status'],result['estimate'],result['p_value'],result['p_holm'],
                    result['recommendation'],'；'.join([*result['blockers'],*([str(result['error'])] if result['error'] else [])]) or '—']
            for j,value in enumerate(values):
                item=QTableWidgetItem(fmt(value));item.setToolTip(encode(result));self.test_table.setItem(i,j,item)
        self.test_table.clearSelection();self.test_table.setCurrentCell(-1,-1);self.test_table.blockSignals(False)
        available=sum(r['p_value'] is not None for r in self.test_rows)
        self.summary_text.setText('保存状态：'+str(state.get('status','未选择'))+'；冻结候选 '+str(len(prepared.get('candidates',[])))+
            ' 项；预设检验 '+str(prepared.get('planned_test_count',0))+' 槽；已获得 p 值 '+str(available)+' 项。缺失与失败不从测试族移除。')

    def open_test_result(self):
        if not self.valid_context() or self.busy:return
        index=self.test_table.currentRow()
        if not 0<=index<len(self.test_rows) or not self.test_rows[index]['run_id']:return
        run_id=self.test_rows[index]['run_id']
        try:self.window.catalog.file(run_id,'experiment.json');self.window.open_run(run_id)
        except (OSError,ValueError,KeyError,TypeError) as exc:self.status.setText('检验证据不可打开：'+str(exc))

    def open_report(self):
        if not self.valid_context() or self.busy or not self.current:return
        from .factory_report import FactoryReportDialog
        self.window.show_dialog(FactoryReportDialog(self.window,self.current['proposal_id']))

    def open_promoted_watch(self):
        if not self.valid_context() or self.busy or not self.current:return
        watch_id=self.promoted_watches.currentData();proposal_id=self.current['proposal_id']
        if not watch_id:return
        def show(state):
            if not any(r.get('watch_id')==watch_id for r in state.get('promotions',[])):
                self.status.setText('观察池关联已变化，请刷新Factory后重选。');return
            self.window.factor_watches(watch_id)
        self.work(lambda:self.service.get(proposal_id),show)

    def valid_context(self):
        return (not self.closed and not sip.isdeleted(self) and not sip.isdeleted(self.window)
                and not getattr(self.window,'closing',False) and self.output==self.window.output
                and self.data_root==self.window.data_root and self.epoch==getattr(self.window,'epoch',None))
    def closeEvent(self,event):self.closed=True;super().closeEvent(event)
    def new_plan(self):
        if not self.valid_context() or self.busy:return
        from .factory_builder import FactoryPlanDialog
        self.window.show_dialog(FactoryPlanDialog(self.window))
    def buttons(self):
        if not self.valid_context():
            for c in self.findChildren(QPushButton):c.setEnabled(False)
            return
        self.new_button.setEnabled(not self.busy)
        self.report_button.setEnabled(not self.busy and self.current is not None)
        self.watch_button.setEnabled(not self.busy and bool(self.promoted_watches.currentData()))
        selected=self.test_table.currentRow()
        self.evidence_button.setEnabled(not self.busy and 0<=selected<len(self.test_rows) and bool(self.test_rows[selected]['run_id']))
        status=self.current.get('status') if self.current else None
        self.submit_button.setEnabled(not self.busy and status in ('pending','admitting') and self.confirm.isChecked())
        self.sync_button.setEnabled(not self.busy and status in ('submitted','running'))
        self.open_button.setEnabled(not self.busy and bool(self.current and self.current.get('result_run_id')))
        self.promote_button.setEnabled(not self.busy and status=='completed' and bool(self.candidates.currentData()) and self.promote_confirm.isChecked())
    def work(self,fn,done):
        if self.busy:return
        if not self.valid_context():self.status.setText('工作空间或窗口已变化，请重新打开Factory。');self.buttons();return
        self.busy=True
        for c in self.findChildren(QPushButton):c.setEnabled(False)
        for c in (self.proposals,self.candidates,self.watch_name,self.confirm,self.promote_confirm,self.promoted_watches):c.setEnabled(False)
        def finished(value,error):
            if not self.valid_context():return
            self.busy=False
            for c in (self.proposals,self.candidates,self.watch_name,self.confirm,self.promote_confirm,self.promoted_watches):c.setEnabled(True)
            self.reload_button.setEnabled(True)
            if error:self.status.setText('未完成：'+error)
            else:done(value)
            self.buttons()
        self.window.async_call(fn,finished,guarded=False)
    def reload(self):
        selected=self.proposals.currentData() or self.selected_id
        def show(value):
            self.proposals.blockSignals(True);self.proposals.clear()
            for item in value['factories']:
                self.proposals.addItem(item['status']+' · '+item['prepared']['plan']['name']+' · '+item['proposal_id'][:8],item['proposal_id'])
            if selected:self.proposals.setCurrentIndex(self.proposals.findData(selected))
            self.proposals.blockSignals(False);self.select()
            self.status.setText('已读取 '+str(len(value['factories']))+' 个Factory；异常 '+str(len(value['errors']))+' 项。')
        self.work(self.service.list,show)
    def select(self):
        proposal_id=self.proposals.currentData();self.current=None
        self.render_summary(None)
        self.confirm.setChecked(False);self.promote_confirm.setChecked(False);self.candidates.clear();self.promoted_watches.clear()
        if not proposal_id:self.details.setPlainText('{}');self.buttons();return
        def show(value):
            if self.proposals.currentData()!=proposal_id:return
            self.current=value;self.details.setPlainText(encode(value));self.candidates.clear()
            self.render_summary(value)
            names={c['candidate_id']:c.get('name',c['candidate_id'][:8]) for c in value.get('prepared',{}).get('candidates',[])}
            promoted={r['candidate_id'] for r in value.get('promotions',[])}
            self.promoted_watches.blockSignals(True);self.promoted_watches.clear()
            for entry in value.get('promotions',[]):
                self.promoted_watches.addItem(names.get(entry['candidate_id'],entry['candidate_id'][:8])+' · '+entry['watch_id'][:8],entry['watch_id'])
            self.promoted_watches.blockSignals(False)
            for cid in value.get('recommended_candidate_ids',[]):
                if cid in promoted:continue
                self.candidates.addItem(names.get(cid,cid[:8]),cid)
            self.buttons()
        self.work(lambda:self.service.get(proposal_id),show)
    def submit(self):
        if not self.current or not self.confirm.isChecked():return
        proposal_id=self.current['proposal_id'];expected=self.current['prepared_digest']
        def show(value):
            self.current=value;self.confirm.setChecked(False);self.details.setPlainText(encode(value))
            self.render_summary(value)
            self.status.setText('Factory任务已提交原研究队列；完成后点击同步结果。')
        self.work(lambda:self.service.submit(proposal_id,expected,self.window.get_research_queue,confirmed=True),show)
    def sync(self):
        if not self.current:return
        proposal_id=self.current['proposal_id']
        def show(value):
            self.current=value;self.details.setPlainText(encode(value))
            self.render_summary(value)
            if value['status']=='completed':
                self.status.setText('Factory已完成；推荐候选仍需第二次人工确认才能进入Watchlist。')
            else:self.status.setText('Factory尚未全部终态：'+value['status'])
            self.select()
        self.work(lambda:self.service.sync(proposal_id),show)
    def open_result(self):
        if not self.valid_context() or not self.current or not self.current.get('result_run_id'):return
        run_id=self.current['result_run_id'];self.window.catalog.file(run_id,'experiment.json');self.window.open_run(run_id)
    def promote(self):
        if not self.current or not self.promote_confirm.isChecked() or not self.candidates.currentData():return
        cid=self.candidates.currentData();name=self.watch_name.text().strip()
        if not name:
            names={c['candidate_id']:c.get('name',c['candidate_id'][:8]) for c in self.current.get('prepared',{}).get('candidates',[])}
            name=names.get(cid,'Factory候选 '+cid[:8])+' · Factory观察'
        proposal_id=self.current['proposal_id']
        def show(value):
            self.promote_confirm.setChecked(False);self.details.setPlainText(encode(value))
            self.status.setText('已加入Watchlist；未创建自动跟踪授权。')
            self.select()
        self.work(lambda:self.service.promote(proposal_id,cid,name,confirmed=True),show)
