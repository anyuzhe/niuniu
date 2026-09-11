"""Explicit finite authorization and local inbox; no model can enable this UI."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from PyQt6 import sip
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QComboBox,QDateEdit,
    QSpinBox,QCheckBox,QPushButton)
from quantlab.agent.tracking_authorization import preview_control,authorize_control
from quantlab.agent.tracking_control_store import ControlStore
from quantlab.agent.watchlist import WatchService
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.storage.codec import digest,encode
from .business_view import BusinessDetails
from .widgets import label,button,row


class TrackingControlDialog(QDialog):
    def __init__(self,window,selected_id=None):
        super().__init__(window);self.window=window;self.plan=None;self.busy=False
        self.output=window.output;self.data_root=window.data_root
        self.setWindowTitle('受控自动跟踪与应用内提醒');self.resize(1050,830)
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.watches=QComboBox();self.calendars=QComboBox()
        self.end=QDateEdit(QDate.currentDate().addDays(7));self.end.setCalendarPopup(True)
        self.end.setDisplayFormat('yyyy-MM-dd')
        self.jobs=QSpinBox();self.jobs.setRange(1,10);self.jobs.setValue(3)
        self.days=QSpinBox();self.days.setRange(1,30);self.days.setValue(7)
        self.interval=QSpinBox();self.interval.setRange(60,1440);self.interval.setValue(60)
        self.auto_download=QCheckBox('允许在固定更新通道内自动下载并接入无历史修订的新批次')
        self.downloads=QSpinBox();self.downloads.setRange(1,10);self.downloads.setValue(3)
        for title,control in [('固定跟踪',self.watches),('已导入完整日历',self.calendars),
            ('允许延长到',self.end),('本次最多任务',self.jobs),('授权有效天数',self.days),
            ('检查间隔（分钟）',self.interval),('本次最多自动下载',self.downloads)]:form.addRow(title,control)
        box.addWidget(self.auto_download)
        box.addWidget(label('默认只使用本地数据。仅当当前数据源是固定更新通道并显式勾选时，才允许有限联网下载；历史修订不会自动发布。','note',True))
        self.preview_button=button('预览固定授权计划',self.preview)
        self.enable_button=button('按选中计划授权并启用',self.enable,True)
        self.revoke_button=button('撤销新任务授权',self.revoke)
        self.confirm=QCheckBox('我已核对完整计划，允许在上述范围内自动提交研究并同步结果。')
        box.addWidget(self.confirm);box.addWidget(row(self.preview_button,self.enable_button,self.revoke_button))
        box.addWidget(label('撤销/到期停止新入队；已经入队的任务需在运行任务页单独取消。失败或中断不自动重试。','muted',True))
        box.addWidget(row(button('刷新跟踪及日历',self.reload),button('查看授权与提醒',self.inspect),
            button('提醒标为已读',self.acknowledge),button('检查已授权计划',window.tracking_controller.check)))
        box.addWidget(button('同步人工恢复成功的原任务',self.reconcile))
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('默认没有授权；先选择新版本基准和完整日历。','muted',True);box.addWidget(self.status)
        self.confirm.toggled.connect(self.buttons)
        for control in (self.watches,self.calendars):control.currentIndexChanged.connect(self.dirty)
        self.end.dateChanged.connect(self.dirty)
        for control in (self.jobs,self.days,self.interval,self.downloads):control.valueChanged.connect(self.dirty)
        self.auto_download.toggled.connect(self.dirty)
        self.selected_id=selected_id;self.buttons();self.reload()
    def buttons(self):
        self.enable_button.setEnabled(not self.busy and self.plan is not None and self.confirm.isChecked())
    def dirty(self,*_):
        self.plan=None;self.confirm.setChecked(False);self.buttons()
    def work(self,fn,done):
        if self.busy:return
        self.busy=True
        controls=[*self.findChildren(QPushButton),self.watches,self.calendars,self.end,
            self.jobs,self.days,self.interval,self.downloads,self.auto_download,self.confirm]
        for control in controls:control.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for control in controls:control.setEnabled(True)
            if error:self.status.setText('未完成：'+error)
            else:done(value)
            self.buttons()
        self.window.async_call(fn,finished,guarded=False)
    def reload(self):
        selected=self.watches.currentData() or self.selected_id
        def load():
            watches=WatchService(self.output).store.list()['watches']
            imports=MarketDataResearchAPI(self.output).call('list_baostock_imports',{'offset':0,'limit':20})
            if not imports['ok']:raise ValueError(imports['error']['message'])
            current_import=None
            marker=Path(self.data_root)/'baostock-series.json' if self.data_root else None
            if marker and (marker.exists() or marker.is_symlink()):
                from quantlab.data.baostock_series import read_series
                current_import=read_series(Path(self.data_root))['history'][-1]['delivery']['import_id']
            return watches,imports['data']['imports'],current_import
        def show(value):
            watches,imports,current_import=value;self.watches.clear();self.calendars.clear()
            for item in watches:self.watches.addItem(item['name'],item['watch_id'])
            for item in imports:
                if (item.get('dataset') or {}).get('calendar_ready'):
                    self.calendars.addItem(item['import_id'][:8],item['import_id'])
            if selected:self.watches.setCurrentIndex(self.watches.findData(selected))
            self.auto_download.setEnabled(current_import is not None)
            if current_import:
                index=self.calendars.findData(current_import)
                if index>=0:self.calendars.setCurrentIndex(index)
            else:self.auto_download.setChecked(False)
            self.status.setText('已读取列表；自动下载仅对固定更新通道可用。')
        self.work(load,show)
    def preview(self):
        watch=self.watches.currentData();calendar=self.calendars.currentData()
        if not watch or not calendar:self.status.setText('请选择跟踪与完整日历。');return
        end=self.end.date().toString('yyyy-MM-dd');jobs=self.jobs.value();interval=self.interval.value()
        auto_download=self.auto_download.isChecked();downloads=self.downloads.value()
        expiry=(datetime.now(timezone.utc)+timedelta(days=self.days.value())).isoformat()
        def show(value):
            self.plan=value;self.confirm.setChecked(False);self.details.setPlainText(encode(value))
            self.status.setText('预览已固定。核对后勾选并授权；当前尚未启用。')
        self.work(lambda:preview_control(self.output,self.data_root,watch,calendar,end,expiry,jobs,interval,auto_download,downloads),show)
    def enable(self):
        if self.plan is None or not self.confirm.isChecked():return
        plan=self.plan
        def done(value):
            self.dirty();self.details.setPlainText(encode(value))
            self.status.setText('授权已保存；下一次检查只在此范围内执行。')
            self.window.tracking_controller.check()
        self.work(lambda:authorize_control(self.output,self.data_root,plan,digest(plan),confirmed=True),done)
    def inspect(self):
        watch=self.watches.currentData()
        if not watch:return
        self.work(lambda:ControlStore(self.output).get(watch),
            lambda value:self.details.setPlainText(encode(value or {'enabled':False,'status':'not_authorized'})))
    def revoke(self):
        watch=self.watches.currentData()
        if watch:self.work(lambda:ControlStore(self.output).revoke(watch),
            lambda _:self.status.setText('已撤销新任务授权；已入队任务请到任务页取消。'))
    def acknowledge(self):
        watch=self.watches.currentData()
        if watch:self.work(lambda:ControlStore(self.output).acknowledge(watch),lambda _:self.status.setText('提醒已标为已读。'))

    def reconcile(self):
        watch=self.watches.currentData()
        if not watch:self.status.setText('请先选择已有跟踪。');return
        from quantlab.agent.tracking_scheduler import TrackingScheduler
        engine=TrackingScheduler(self.output,self.data_root,self.window.get_research_queue)
        def done(value):
            self.details.setPlainText(encode(value))
            self.status.setText('已同步 '+str(value['synchronized'])+' 个原任务结果；未提交或恢复任务，也未重新开启授权。')
        self.work(lambda:engine.reconcile_completed(watch),done)
