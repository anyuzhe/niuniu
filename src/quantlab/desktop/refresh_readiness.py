"""Explicit calendar-based due checks; never starts a scheduler."""
from datetime import datetime
from zoneinfo import ZoneInfo
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QFormLayout,QLineEdit
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.agent.watchlist import WatchService
from quantlab.storage.codec import encode
from .widgets import button,label,row
from .business_view import BusinessDetails


class RefreshReadinessDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.busy=False
        self.setWindowTitle('因子跟踪：交易日历与到期检查');self.resize(950,720)
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.watches=QComboBox();self.calendars=QComboBox()
        self.as_of=QLineEdit(datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'))
        for title,control in [('现有跟踪',self.watches),('已归档日历批次',self.calendars),('检查时点（含时区）',self.as_of)]:form.addRow(title,control)
        self.check_button=button('检查到期候选（不执行）',self.check,True)
        box.addWidget(row(self.check_button,button('打开原跟踪池',lambda:window.factor_watches(self.watches.currentData()))))
        box.addWidget(label('按完整供应商日历及名义入库时间加30分钟缓冲判断。不假定行情已下载，不自动批准或调度。','note',True))
        self.details=BusinessDetails({});box.addWidget(self.details,1);self.status=label('正在读取…','muted');box.addWidget(self.status)
        self.api=MarketDataResearchAPI(window.output,window.data_root)
        def load():
            return WatchService(window.output).store.list(),self.api.call('list_baostock_imports',{'offset':0,'limit':20})
        def done(value,error):
            if sip.isdeleted(self):return
            if error:self.status.setText(error);return
            watches,imports=value
            for r in watches['watches']:self.watches.addItem(r['name'],r['watch_id'])
            if imports['ok']:
                for r in imports['data']['imports']:
                    if (r.get('dataset') or {}).get('calendar_ready'):
                        self.calendars.addItem(r['import_id'][:8],r['import_id'])
            self.status.setText('请选择跟踪和覆盖检查日期的日历。')
        window.async_call(load,done,guarded=False)
    def check(self):
        if self.busy:return
        if not self.watches.currentData() or not self.calendars.currentData():
            self.status.setText('缺少跟踪或完整日历；不能用工作日猜测。');return
        args={'watch_id':self.watches.currentData(),'import_id':self.calendars.currentData(),'as_of':self.as_of.text().strip()}
        self.busy=True;controls=(self.check_button,self.watches,self.calendars,self.as_of)
        for c in controls:c.setEnabled(False)
        def done(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for c in controls:c.setEnabled(True)
            if error:self.status.setText(error);return
            self.details.setPlainText(encode(value))
            self.status.setText('检查完成；没有创建研究任务。' if value.get('ok') else '检查未完成：'+value['error']['message'])
        self.window.async_call(lambda:self.api.call('get_watch_refresh_readiness',args),done,guarded=False)
