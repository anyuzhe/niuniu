"""Native access to provenance-preserving historical reference downloads."""
from pathlib import Path
from uuid import uuid4
from PyQt6 import sip
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QDateEdit,QFileDialog
from .widgets import label,button,table


class ReferenceDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setWindowTitle('Baostock 历史资料');self.resize(820,600)
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.symbols=QLineEdit();self.start=QDateEdit(QDate.currentDate().addYears(-1));self.end=QDateEdit(QDate.currentDate())
        for c in (self.start,self.end):c.setDisplayFormat('yyyy-MM-dd');c.setCalendarPopup(True)
        self.dates=QLineEdit();self.dates.setPlaceholderText('留空查询起止日期；多个日期用空格分隔，如 2021-08-12')
        for title,control in [('股票代码（空格分隔）',self.symbols),('历史开始',self.start),('历史结束',self.end),('行业查询日期',self.dates)]:form.addRow(title,control)
        box.addWidget(label('抓取基本资料、指定日期行业、季度披露股本及日线ST/交易状态。保存原始字段、抓取时间和校验值，不覆盖行情；不自动生成官方涨跌停价格或声称严格PIT。','note',True))
        self.fetch=button('抓取并归档历史资料',self.run,True);box.addWidget(self.fetch)
        self.status=label('尚未抓取。','muted',True);box.addWidget(self.status)
        self.results=table(['文件','记录数','接收状态'],[]);box.addWidget(self.results,1)
        box.addWidget(button('核对已归档资料的研究覆盖',self.inspect_archive))
        box.addWidget(button('查看当前 Strict PIT Coverage',self.inspect_strict_pit))

    def inspect_strict_pit(self):
        if not self.window.data_root:
            self.status.setText('请先配置行情数据目录。');return
        self.status.setText('正在读取严格回执与回顾性候选数据 inventory…')
        def done(result,error):
            if sip.isdeleted(self):return
            if error:self.status.setText('Strict PIT Coverage 读取失败：'+error);return
            self.results.setColumnCount(5);self.results.setHorizontalHeaderLabels(['证据类型','Strict回执','证券数','effective范围','说明'])
            self.results.setRowCount(0)
            from PyQt6.QtWidgets import QTableWidgetItem
            labels={'universe_eligibility':'历史资格','security_status':'ST/停复牌状态','industry_membership':'历史行业','daily_market_cap':'每日市值'}
            for kind,item in result['strict_evidence']['by_kind'].items():
                i=self.results.rowCount();self.results.insertRow(i);span=item['effective_date_range']
                values=(labels[kind],item['verified_statements'],item['unique_symbols'],str(span['min'])+' ~ '+str(span['max']),'严格证据 presence，不代表完整历史链')
                for j,value in enumerate(values):self.results.setItem(i,j,QTableWidgetItem(str(value)))
            bars=result['retrospective_inventory']['bars'];industry=result['retrospective_inventory']['industry']
            self.status.setText(f"{result['status']}；历史bars={bars['files']}只/{bars['rows']}行；行业快照={industry.get('snapshot_dates',[])}；gap={len(result['gaps'])}。具体研究仍须单独 qualification。")
        from quantlab.data.pit_coverage import strict_pit_coverage
        self.window.async_call(lambda:strict_pit_coverage(self.window.data_root,detail_limit=50),done,guarded=False)

    def inspect_archive(self):
        path,_=QFileDialog.getOpenFileName(self,'选择 Baostock 资料 manifest.json',str(self.window.output),'JSON (*.json)')
        if not path:return
        from quantlab.data.reference_archive import reference_coverage
        self.status.setText('正在核对来源与逐证券覆盖…')
        def done(result,error):
            if sip.isdeleted(self):return
            if error:self.status.setText('归档核对失败：'+error);return
            self.results.setColumnCount(6);self.results.setHorizontalHeaderLabels(['证券','上市资料','行业查询日','状态记录日','未查询行业的状态日','历史发布时间'])
            self.results.setRowCount(len(result['symbols']))
            from PyQt6.QtWidgets import QTableWidgetItem
            for i,item in enumerate(result['symbols']):
                values=(item['symbol'],'有' if item['basic'] else '缺少',len(item['industry_dates']),len(item['status_dates']),item['industry_unqueried_status_dates'],'已提供' if item['historical_publication_known'] else '缺少')
                for j,value in enumerate(values):self.results.setItem(i,j,QTableWidgetItem(str(value)))
            self.status.setText('来源校验通过。上市资料可在新建实验→股票资格中选用；每日市值及官方涨跌停价仍未提供，季度股本不作每日市值。')
        self.window.async_call(lambda:reference_coverage(path),done,guarded=False)
    def run(self):
        from datetime import date
        from quantlab.data.baostock_reference import fetch_reference
        import re
        symbols=[s for s in re.split(r'[\s,，]+',self.symbols.text().strip()) if s]
        try:
            dates=[date.fromisoformat(v) for v in self.dates.text().split()]
            start=self.start.date().toPyDate();end=self.end.date().toPyDate()
            if not symbols or start>end or len(set(symbols))!=len(symbols) or any(not re.fullmatch(r'(sh|sz)\.\d{6}',s) for s in symbols):raise ValueError('请填写不同的完整证券代码及有效日期区间。')
            if any(not start<=d<=end for d in dates):raise ValueError('行业查询日期必须在历史区间内。')
        except ValueError as error:self.status.setText(str(error));return
        path=Path(self.window.output)/'_reference'/str(uuid4());self.fetch.setEnabled(False);self.status.setText('正在抓取，原始资料逐项保存到：'+str(path))
        def done(result,error):
            if sip.isdeleted(self):return
            self.fetch.setEnabled(True)
            if error:self.status.setText('抓取未完成：'+error+'；已接收记录保留在 '+str(path));return
            self.results.setRowCount(0)
            self.results.setColumnCount(3);self.results.setHorizontalHeaderLabels(['文件','记录数','接收状态'])
            from PyQt6.QtWidgets import QTableWidgetItem
            for i,item in enumerate(result['files']):
                self.results.insertRow(i)
                for j,value in enumerate((item['path'],item['rows'],item['status'])):self.results.setItem(i,j,QTableWidgetItem(str(value)))
            self.status.setText('已归档 '+str(len(result['files']))+' 份响应：'+str(path)+'。空响应标记 no_data；历史发布时间与每日价格上下限仍须其他证据。')
        self.window.async_call(lambda:fetch_reference(symbols,start,end,path,dates),done,guarded=False)
