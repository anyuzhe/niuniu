"""Form-based plans for the existing paired research engines."""
from PyQt6.QtCore import QDate,Qt
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QDateEdit,QSpinBox,QDoubleSpinBox,QTableWidget,QTableWidgetItem
from .widgets import button,row,label


class ComparisonEditor(QWidget):
    def __init__(self,window,kind,submit):
        super().__init__();self.window=window;self.kind=kind;self.entries=[]
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.name=QLineEdit('参数差异研究' if kind=='stability' else '净收益比较研究')
        self.candidate=QComboBox();self.baseline=QComboBox()
        self.records={}
        for r in window.catalog.list(kind='factor' if kind=='stability' else 'execution',limit=10000)['runs']:
            if r['status']=='completed':
                self.records[r['run_id']]=r
                text=r['run_id'][:8]+' · '+r.get('factor_id','')+' · '+r['question']
                for control in (self.candidate,self.baseline):control.addItem(text,r['run_id'])
        self.start=QDateEdit(QDate.currentDate().addYears(-5));self.end=QDateEdit(QDate.currentDate())
        for control in (self.start,self.end):control.setCalendarPopup(True);control.setDisplayFormat('yyyy-MM-dd')
        self.horizon=QSpinBox();self.horizon.setRange(1,10000)
        self.alpha=QDoubleSpinBox();self.alpha.setRange(.001,.5);self.alpha.setDecimals(3);self.alpha.setValue(.05)
        self.block=QSpinBox();self.block.setRange(1,10000);self.block.setValue(5)
        self.resamples=QSpinBox();self.resamples.setRange(20,100000);self.resamples.setValue(999)
        for name,control in [('研究名称',self.name),('候选归档',self.candidate),('基准归档',self.baseline),('比较开始日期',self.start)]:form.addRow(name,control)
        if kind=='stability':
            self.comparison_kind=QComboBox()
            for title,value in [('参数差异','parameter_change'),('股票子样本等效性','subsample_equivalence'),('沪深跨市场等效性','cross_market_equivalence')]:self.comparison_kind.addItem(title,value)
            form.addRow('检验目的',self.comparison_kind)
            self.candidate_symbols=QLineEdit();self.baseline_symbols=QLineEdit()
            for control in (self.candidate_symbols,self.baseline_symbols):control.setPlaceholderText('填写预先选定的证券代码，空格或逗号分隔')
            self.margin=QDoubleSpinBox();self.margin.setRange(.000001,2);self.margin.setDecimals(6);self.margin.setValue(.05)
            for title,control in [('候选子样本证券',self.candidate_symbols),('基准子样本证券',self.baseline_symbols),('容许 Rank IC 差异（±）',self.margin)]:form.addRow(title,control);control.setEnabled(False)
            self.comparison_kind.currentIndexChanged.connect(lambda:[c.setEnabled(self.comparison_kind.currentData()!='parameter_change') for c in (self.candidate_symbols,self.baseline_symbols,self.margin)])
            for name,control in [('比较结束日期',self.end),('持有期',self.horizon),('日期分块长度',self.block),('重采样次数',self.resamples)]:form.addRow(name,control)
        form.addRow('显著性水平',self.alpha)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['候选','基准','开始','结束 / 持有期']);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True);box.addWidget(self.table)
        self.status=label('先添加全部比较，再运行；归档兼容性由研究引擎校验。','muted',True);box.addWidget(self.status)
        box.addWidget(row(button('添加比较',self.add),button('删除选中比较',self.remove),button('运行完整比较清单',lambda:self.run(submit),True)))
        self.candidate.currentIndexChanged.connect(self.default_dates);self.default_dates()
        for control in self.findChildren(QComboBox):control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def default_dates(self):
        if not self.candidate.currentData():return
        try:
            data=self.records[self.candidate.currentData()]
            self.start.setDate(QDate.fromString(data['start'],'yyyy-MM-dd'));self.end.setDate(QDate.fromString(data['end'],'yyyy-MM-dd'))
        except (OSError,ValueError,KeyError,TypeError):pass

    def add(self):
        a=self.candidate.currentData();b=self.baseline.currentData()
        cohorts=self.kind=='stability' and self.comparison_kind.currentData()!='parameter_change'
        if not a or not b or (a==b and not cohorts):self.status.setText('请选择两个不同的已完成归档；不同证券子样本可以使用同一归档。');return
        start=self.start.date().toString('yyyy-MM-dd');end=self.end.date().toString('yyyy-MM-dd')
        if self.kind=='stability' and start>end:self.status.setText('开始日期不能晚于结束日期。');return
        item={'candidate':str(self.window.output/a),'baseline':str(self.window.output/b),'start':start}
        if self.kind=='stability':item.update(end=end,horizon=self.horizon.value())
        if cohorts:
            import re
            selections=[[s for s in re.split(r'[\s,，]+',c.text().strip()) if s] for c in (self.candidate_symbols,self.baseline_symbols)]
            if any(len(v)<3 or len(v)!=len(set(v)) for v in selections) or set(selections[0])&set(selections[1]):self.status.setText('每组至少三只不同证券，两组不能重叠。');return
            item.update(candidate_symbols=selections[0],baseline_symbols=selections[1],equivalence_margin=self.margin.value())
        if any({k:v for k,v in old.items() if k not in ('name','id')}==item or
               (old['candidate']==item['baseline'] and old['baseline']==item['candidate'] and old['start']==start and old.get('end')==item.get('end') and old.get('horizon')==item.get('horizon') and old.get('candidate_symbols')==item.get('baseline_symbols') and old.get('baseline_symbols')==item.get('candidate_symbols')) for old in self.entries):
            self.status.setText('清单已有此比较或反向比较。');return
        self.entries.append(item);i=self.table.rowCount();self.table.insertRow(i)
        for j,value in enumerate([self.candidate.currentText(),self.baseline.currentText(),start,end+' / '+str(self.horizon.value()) if self.kind=='stability' else '归档共同区间']):self.table.setItem(i,j,QTableWidgetItem(value))
        self.status.setText(f'已添加 {len(self.entries)} 项；尚未运行。')
        if self.kind=='stability':self.comparison_kind.setEnabled(False)

    def remove(self):
        i=self.table.currentRow()
        if i>=0:self.entries.pop(i);self.table.removeRow(i)
        if self.kind=='stability' and not self.entries:self.comparison_kind.setEnabled(True)

    def plan(self):
        if not self.entries or not self.name.text().strip():raise ValueError('请填写研究名称并添加至少一项比较。')
        key='name' if self.kind=='stability' else 'id'
        plan={'name':self.name.text().strip(),'comparisons':[{**entry,key:f'comparison_{i+1}'} for i,entry in enumerate(self.entries)]}
        if self.kind=='stability':
            plan.update(permutation={'alpha':self.alpha.value(),'block_days':self.block.value(),'resamples':self.resamples.value()},bootstrap={'confidence':1-self.alpha.value(),'block_days':self.block.value(),'resamples':self.resamples.value()})
            if self.comparison_kind.currentData()!='parameter_change':plan['comparison_kind']=self.comparison_kind.currentData()
        else:plan['alpha']=self.alpha.value()
        return plan

    def run(self,submit):
        try:plan=self.plan()
        except ValueError as error:self.status.setText(str(error));return
        submit(plan)
