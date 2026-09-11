"""Host-controlled public-data imports and read-only data inspection."""
from threading import Event
import re
from PyQt6 import sip
from PyQt6.QtCore import QDate,Qt
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QDateEdit,
    QCheckBox,QGridLayout,QComboBox,QSpinBox,QPushButton)
from quantlab.data.baostock_catalog import DATASETS,import_plan
from quantlab.data.baostock_ingest import run_import
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.storage.codec import encode
from .widgets import label,button,row
from .business_view import BusinessDetails


class BaostockDataDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.busy=False;self.closing=False;self.stop=Event()
        self.api=MarketDataResearchAPI(window.output,window.data_root)
        self.setWindowTitle('Baostock 数据接入与覆盖检查');self.resize(1100,950)
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.symbols=QLineEdit();self.symbols.setPlaceholderText('sh.600000 sh.600519 sz.000001')
        self.start=QDateEdit(QDate.currentDate().addMonths(-3));self.end=QDateEdit(QDate.currentDate().addDays(-1))
        for control in (self.start,self.end):control.setDisplayFormat('yyyy-MM-dd');control.setCalendarPopup(True)
        self.dates=QLineEdit(self.end.date().toString('yyyy-MM-dd'));self.quarters=QLineEdit()
        self.quarters.setPlaceholderText('财务报告季度，例如 2023Q4 2024Q1；选择财务时必填')
        for title,control in [('指定证券',self.symbols),('开始日期',self.start),('结束日期',self.end),
                ('行业/成分/全市场快照日',self.dates),('财务季度',self.quarters)]:form.addRow(title,control)
        grid=QGridLayout();box.addLayout(grid);self.datasets={}
        for i,(key,title) in enumerate(DATASETS.items()):
            check=QCheckBox(title);check.setChecked(key in ('daily_raw','daily_qfq','calendar','basic','industry'))
            grid.addWidget(check,i//2,i%2);self.datasets[key]=check
        self.consent=QCheckBox('允许本次联网查询所选证券/日期；只写入新的管理数据快照，不覆盖原行情。');box.addWidget(self.consent)
        self.preview_button=button('预检查询数量',self.preview)
        self.fetch_button=button('抓取新快照',self.fetch,True)
        self.cancel_button=button('取消本次抓取',lambda:self.stop.set());self.cancel_button.setEnabled(False)
        box.addWidget(row(self.preview_button,self.fetch_button,self.cancel_button))
        self.imports=QComboBox();self.tables=QComboBox();self.symbol_filter=QLineEdit();self.symbol_filter.setPlaceholderText('表格证券筛选（可留空）')
        self.offset=QSpinBox();self.offset.setRange(0,100000)
        box.addWidget(row(self.imports,button('刷新已导入批次',self.reload)))
        box.addWidget(row(self.tables,self.symbol_filter,label('起始行'),self.offset,button('读取20行',self.read_page)))
        box.addWidget(row(button('核对完整响应与覆盖',self.inspect),button('人工选择为本次研究行情目录',self.use_dataset)))
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('选择数据类别并预检。ETF历史覆盖有限；空响应不补造。财报与行业不自动转为严格PIT。','note',True);box.addWidget(self.status)
        self.imports.currentIndexChanged.connect(self.selected);self.records={}
        for control in (self.symbols,self.dates,self.quarters):
            control.textChanged.connect(lambda *_:self.consent.setChecked(False))
        for control in (self.start,self.end):
            control.dateChanged.connect(lambda *_:self.consent.setChecked(False))
        for control in self.datasets.values():
            control.toggled.connect(lambda *_:self.consent.setChecked(False))
        self.reload()
    def spec(self):
        split=lambda text:[v for v in re.split(r'[\s,，]+',text.strip()) if v]
        return {'symbols':split(self.symbols.text()),'start':self.start.date().toString('yyyy-MM-dd'),
            'end':self.end.date().toString('yyyy-MM-dd'),'datasets':[k for k,v in self.datasets.items() if v.isChecked()],
            'snapshot_dates':split(self.dates.text()),'quarters':split(self.quarters.text())}
    def work(self,function,done):
        if self.busy:return
        self.busy=True;self.controls=[(c,c.isEnabled()) for c in self.findChildren(QPushButton)]
        for c,_ in self.controls:c.setEnabled(False)
        self.cancel_button.setEnabled(True)
        inputs=[self.symbols,self.start,self.end,self.dates,self.quarters,self.consent,
            self.imports,self.tables,self.symbol_filter,self.offset,*self.datasets.values()]
        for c in inputs:c.setEnabled(False)
        def finished(result,error):
            if sip.isdeleted(self):return
            self.busy=False
            for c,enabled in self.controls:
                if not sip.isdeleted(c):c.setEnabled(enabled)
            for c in inputs:c.setEnabled(True)
            self.cancel_button.setEnabled(False)
            if error:self.status.setText('未完成：'+error)
            else:done(result)
            if self.closing:self.close()
        self.window.async_call(function,finished,guarded=False)
    def preview(self):
        try:
            plan,calls=import_plan(self.spec());self.details.setPlainText(encode({'plan':plan,'queries':len(calls)}))
            self.status.setText(f'配置有效：{len(calls)}项有限查询；尚未联网、没有读取行情。')
        except (ValueError,TypeError,KeyError) as error:self.status.setText(str(error))
    def fetch(self):
        if not self.consent.isChecked():self.status.setText('请确认本次联网抓取范围。');return
        try:plan,_=import_plan(self.spec())
        except (ValueError,TypeError,KeyError) as error:self.status.setText(str(error));return
        self.stop=Event();stop=self.stop;self.status.setText('正在独立进程抓取；原行情目录不变…')
        def done(result):
            self.details.setPlainText(encode(result));self.status.setText('导入状态：'+result['status']+'；数据集可用：'+str(result['dataset_ready']))
        self.work(lambda:run_import(self.window.output,plan,stop=stop),done)
    def reload(self):
        def done(result):
            if not result['ok']:self.status.setText(result['error']['message']);return
            values=result['data']['imports'];self.records={r['import_id']:r for r in values}
            self.imports.clear()
            for r in values:self.imports.addItem(r['import_id'][:8]+' · '+r['status'],r['import_id'])
            self.selected()
        self.work(lambda:self.api.call('list_baostock_imports',{'offset':0,'limit':20}),done)
    def selected(self):
        current=self.records.get(self.imports.currentData(),{});self.tables.clear()
        for table in (current.get('dataset') or {}).get('tables',{}):self.tables.addItem(table)
    def inspect(self):
        identifier=self.imports.currentData()
        if not identifier:return
        self.work(lambda:self.api.call('get_baostock_import',{'import_id':identifier}),
            lambda result:self.details.setPlainText(encode(result)))
    def read_page(self):
        if not self.imports.currentData() or not self.tables.currentText():return
        args={'import_id':self.imports.currentData(),'table':self.tables.currentText(),
            'symbol':self.symbol_filter.text().strip(),'offset':self.offset.value(),'limit':20}
        self.work(lambda:self.api.call('read_baostock_table',args),lambda result:self.details.setPlainText(encode(result)))
    def use_dataset(self):
        if self.busy or not self.imports.currentData():return
        try:self.window.select_baostock_dataset(self.imports.currentData());self.status.setText('本次工作台行情目录已切换；没有移动或覆盖文件。')
        except (ValueError,OSError) as error:self.status.setText(str(error))
    def closeEvent(self,event):
        if self.busy:self.closing=True;self.stop.set();event.ignore();return
        self.closing=False;event.accept()
