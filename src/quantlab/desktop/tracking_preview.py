"""Read-only UI for maturity-aware monitoring; no background schedule."""
import re
from PyQt6 import sip
from PyQt6.QtCore import QDate,QDateTime,QTime
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QComboBox,QLineEdit,QSpinBox,QDateTimeEdit
from quantlab.agent.tracking_preview import tracking_preview
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import label,button,row


class TrackingPreviewDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.busy=False;self.records={}
        self.setWindowTitle('因子追踪 · 标签成熟预览');self.resize(1050,800)
        box=QVBoxLayout(self)
        box.addWidget(label('读取已完成单因子归档，按截止时间重算窗口指标。未成熟收益保留为空；此处不创建跟踪池、定时任务或新研究。','note',True))
        form=QFormLayout();box.addLayout(form);self.source=QComboBox();form.addRow('实际研究来源',self.source)
        self.cutoff=QDateTimeEdit(QDateTime(QDate.currentDate(),QTime(15,0)))
        self.cutoff.setDisplayFormat('yyyy-MM-dd HH:mm:ss');self.cutoff.setCalendarPopup(True)
        form.addRow('评价截止（北京时间）',self.cutoff)
        self.windows=QLineEdit('20 60 120');form.addRow('观察窗口（已观察交易日期数）',self.windows)
        self.minimum=QSpinBox();self.minimum.setRange(1,1000);self.minimum.setValue(20)
        form.addRow('最少有效 IC 日期数',self.minimum)
        self.run_button=button('计算只读预览',self.calculate,True);self.reload_button=button('刷新来源列表',self.reload)
        box.addWidget(row(self.run_button,self.reload_button));self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('正在读取研究目录…','muted',True);box.addWidget(self.status)
        self.source.currentIndexChanged.connect(self.select);self.reload()
    def work(self,fn,done):
        if self.busy:return
        self.busy=True
        for c in (self.source,self.cutoff,self.windows,self.minimum,self.run_button,self.reload_button):c.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for c in (self.source,self.cutoff,self.windows,self.minimum,self.run_button,self.reload_button):c.setEnabled(True)
            if error:self.status.setText('预览未完成：'+error)
            else:done(value)
        self.window.async_call(fn,finished,guarded=False)
    def reload(self):
        def show(data):
            self.records={r['run_id']:r for r in data['runs']};self.source.clear()
            for r in data['runs']:self.source.addItem(r['run_id'][:8]+' · '+r['question'],r['run_id'])
            self.status.setText('仅列出当前工作空间的已完成单因子归档；需已保存K线和观测表。')
        self.work(lambda:self.window.catalog.list(status='completed',kind='factor',limit=10000),show)
    def select(self):
        record=self.records.get(self.source.currentData())
        if record:
            day=QDate.fromString(record['end'],'yyyy-MM-dd')
            if day.isValid():self.cutoff.setDateTime(QDateTime(day,QTime(15,0)))
    def calculate(self):
        identifier=self.source.currentData()
        if not identifier:self.status.setText('请先选择真实研究归档。');return
        try:windows=[int(v) for v in re.split(r'[\s,，]+',self.windows.text().strip()) if v]
        except ValueError:self.status.setText('窗口请填写整数。');return
        cutoff=self.cutoff.dateTime().toString('yyyy-MM-ddTHH:mm:ss')+'+08:00'
        minimum=self.minimum.value();output=self.window.output
        self.status.setText('正在核对归档、重算成熟标签…')
        def show(value):
            self.details.setPlainText(encode(value))
            self.status.setText('只读预览完成；未创建新实验、跟踪池或定时任务。')
        self.work(lambda:tracking_preview(output,identifier,cutoff,windows,minimum),show)
