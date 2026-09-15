"""Host-only Research Session Grant dialog."""
from datetime import datetime,timedelta,timezone
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,
    QDateEdit,QCheckBox,QPlainTextEdit)

from quantlab.agent.research_session_grant import preview_grant,authorize_grant,revoke_grant,grant_status
from quantlab.storage.codec import digest,encode
from .widgets import label,button,row

class ResearchSessionGrantDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.output=window.output;self.data_root=window.data_root
        self.plan=None;self.plan_digest=None;self.setWindowTitle('Research Session Grant · 有限自主研究授权');self.resize(980,860)
        box=QVBoxLayout(self);box.addWidget(label('只授权有限本地研究；不开放 Shell、联网下载、代码写入、Campaign、Execution 或真实交易。','note',True))
        form=QFormLayout();self.symbols=QLineEdit();self.symbols.setPlaceholderText('sh.600000, sh.600519, sz.000001')
        self.start=QDateEdit(QDate.currentDate().addYears(-1));self.end=QDateEdit(QDate.currentDate());self.start.setCalendarPopup(True);self.end.setCalendarPopup(True)
        self.timeframe=QComboBox();self.timeframe.addItems(['1d','5m','15m','30m','60m'])
        self.adjustment=QComboBox();self.adjustment.addItems(['qfq','raw'])
        self.qualification=QComboBox();self.qualification.addItems(['research_only','retrospective_reference','strict_pit'])
        self.factors=QLineEdit('BASE.MOMENTUM@1.0.0');self.modes=QLineEdit('single,holdout,walkforward,sweep')
        for title,widget in [('证券范围',self.symbols),('开始日期',self.start),('结束日期',self.end),('K线周期',self.timeframe),('复权口径',self.adjustment),('数据资格',self.qualification),('允许因子（逗号分隔）',self.factors),('允许模式（逗号分隔）',self.modes)]:form.addRow(title,widget)
        self.hours=QDoubleSpinBox();self.hours.setRange(.25,24);self.hours.setValue(4);self.hours.setSuffix(' 小时')
        self.max_jobs=QSpinBox();self.max_jobs.setRange(1,20);self.max_jobs.setValue(5)
        self.max_active=QSpinBox();self.max_active.setRange(1,4);self.max_active.setValue(2)
        self.leaf=QSpinBox();self.leaf.setRange(1,64);self.leaf.setValue(16)
        self.total_leaf=QSpinBox();self.total_leaf.setRange(1,256);self.total_leaf.setValue(40)
        self.total_bars=QSpinBox();self.total_bars.setRange(1,100_000_000);self.total_bars.setValue(20_000_000)
        self.total_draws=QSpinBox();self.total_draws.setRange(1,500_000_000);self.total_draws.setValue(100_000_000)
        self.seconds=QSpinBox();self.seconds.setRange(30,3600);self.seconds.setValue(300);self.seconds.setSuffix(' 秒')
        for title,widget in [('有效期',self.hours),('最多研究任务',self.max_jobs),('同时活动任务上限',self.max_active),('单任务叶子研究上限',self.leaf),('总叶子研究上限',self.total_leaf),('总K线评价量',self.total_bars),('总重采样日期抽样量',self.total_draws),('单任务合作式时限',self.seconds)]:form.addRow(title,widget)
        box.addLayout(form)
        self.confirm=QCheckBox('我确认：这是有限自主研究授权；失败/取消也消耗额度，授权不会扩大到真实交易。');box.addWidget(self.confirm)
        self.preview_button=button('预览完整授权',self.preview,True);self.authorize_button=button('确认启用授权',self.authorize);self.revoke_button=button('撤销当前授权',self.revoke)
        box.addWidget(row(self.preview_button,self.authorize_button,self.revoke_button,button('刷新状态',self.refresh)))
        self.status=label('尚未读取授权状态。','muted',True);box.addWidget(self.status)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);box.addWidget(self.details,1)
        self.authorize_button.setEnabled(False);self.refresh()
    def scope(self):
        symbols=[v.strip() for v in self.symbols.text().split(',') if v.strip()]
        factors=[v.strip() for v in self.factors.text().split(',') if v.strip()]
        modes=[v.strip() for v in self.modes.text().split(',') if v.strip()]
        return {'symbols':symbols,'timeframe':self.timeframe.currentText(),'start':self.start.date().toString('yyyy-MM-dd'),
            'end':self.end.date().toString('yyyy-MM-dd'),'adjustment':self.adjustment.currentText(),
            'qualification':self.qualification.currentText(),'allowed_modes':modes,'allowed_factors':factors}
    def preview(self):
        if self.data_root is None:self.status.setText('请先配置行情目录。');return
        try:
            expiry=(datetime.now(timezone.utc)+timedelta(hours=self.hours.value())).isoformat()
            self.plan=preview_grant(self.output,self.data_root,self.scope(),expires_at=expiry,max_jobs=self.max_jobs.value(),
                max_active_jobs=self.max_active.value(),max_leaf_studies=self.leaf.value(),max_total_leaf_studies=self.total_leaf.value(),
                max_total_bar_evaluations=self.total_bars.value(),max_total_resample_date_draws=self.total_draws.value(),cooperative_seconds=self.seconds.value())
            self.plan_digest=digest(self.plan);self.details.setPlainText(encode({'plan_digest':self.plan_digest,'plan':self.plan}))
            self.confirm.setChecked(False);self.authorize_button.setEnabled(True);self.status.setText('预览完成；核对后勾选确认才能启用。')
        except Exception as exc:self.plan=None;self.authorize_button.setEnabled(False);self.status.setText('预览失败：'+str(exc))
    def authorize(self):
        if self.plan is None or not self.confirm.isChecked():self.status.setText('请先预览并勾选完整授权确认。');return
        try:
            state=authorize_grant(self.output,self.data_root,self.plan,self.plan_digest,confirmed=True)
            self.details.setPlainText(encode(state));self.authorize_button.setEnabled(False);self.confirm.setChecked(False)
            self.status.setText('Research Session Grant 已启用：'+state['grant_id'])
        except Exception as exc:self.status.setText('启用失败：'+str(exc))
    def revoke(self):
        try:
            value=grant_status(self.output,self.data_root)
            if not value.get('grant'):self.status.setText('当前没有可撤销的 Research Session Grant。');return
            if not self.confirm.isChecked():self.status.setText('撤销也需要勾选上方确认框。');return
            state=revoke_grant(self.output,value['grant']['grant_id'],confirmed=True)
            self.details.setPlainText(encode(state));self.confirm.setChecked(False);self.status.setText('Research Session Grant 已撤销；新任务立即禁止，运行任务会在检查点停止。')
        except Exception as exc:self.status.setText('撤销失败：'+str(exc))
    def refresh(self):
        try:
            value=grant_status(self.output,self.data_root);self.details.setPlainText(encode(value))
            grant=value.get('grant') or {};self.status.setText('当前状态：'+value['status']+((' · '+grant.get('grant_id','')) if grant else ''))
        except Exception as exc:self.status.setText('状态读取失败：'+str(exc))
