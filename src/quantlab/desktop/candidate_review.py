"""Native paired-factor evidence review; no research submission actions."""
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QComboBox,QSpinBox
from quantlab.agent.candidate_review import compare_candidate
from quantlab.storage.codec import encode
from .widgets import label,button,row
from .business_view import BusinessDetails


class CandidateReviewDialog(QDialog):
    def __init__(self, window):
        super().__init__(window);self.window=window;self.busy=False;self.last_result=None
        self.setWindowTitle('候选因子对照 · 共同样本与证据');self.resize(1050,780)
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.candidate=QComboBox();self.baseline=QComboBox();self.horizon=QSpinBox()
        self.horizon.setRange(1,1000);self.horizon.setValue(1)
        for title,control in [('候选因子研究',self.candidate),('基准因子研究',self.baseline),('持有期（K线根数）',self.horizon)]:
            form.addRow(title,control)
        box.addWidget(label('只比较已完成归档。日期、数据、股票池和处理条件必须一致；共同样本IC差值不是增量Alpha或显著性结论。','note',True))
        self.compare_button=button('核对并比较（不运行研究）',self.compare,True)
        self.reload_button=button('刷新来源目录',self.reload)
        self.open_candidate=button('打开候选实验',lambda:self.open_source(self.candidate))
        self.open_baseline=button('打开基准实验',lambda:self.open_source(self.baseline))
        box.addWidget(row(self.compare_button,self.reload_button,self.open_candidate,self.open_baseline))
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('正在读取来源目录…','muted',True);box.addWidget(self.status)
        self.controls=[self.candidate,self.baseline,self.horizon,self.compare_button,self.reload_button,self.open_candidate,self.open_baseline]
        for c in (self.candidate,self.baseline):c.currentIndexChanged.connect(self.dirty)
        self.horizon.valueChanged.connect(self.dirty);self.reload()
    def dirty(self,*_):
        self.last_result=None;self.details.setPlainText('{}')
        self.status.setText('选择已变化，请重新核对；尚未运行任何新研究。')
    def work(self,fn,done):
        if self.busy:return
        self.busy=True
        for c in self.controls:c.setEnabled(False)
        def finished(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            for c in self.controls:c.setEnabled(True)
            if error:self.status.setText('对照未完成：'+error)
            else:done(value)
        self.window.async_call(fn,finished,guarded=False)
    def reload(self):
        old=[c.currentData() for c in (self.candidate,self.baseline)]
        def show(value):
            for c,selected in zip((self.candidate,self.baseline),old):
                c.clear()
                for r in value['runs']:c.addItem(r['run_id'][:8]+' · '+r['question'],r['run_id'])
                if selected:c.setCurrentIndex(c.findData(selected))
            if old==[None,None] and self.baseline.count()>1:self.baseline.setCurrentIndex(1)
            self.status.setText('已载入来源；请选择两个研究及它们共同保存的持有期。')
        self.work(lambda:self.window.catalog.list(status='completed',kind='factor',limit=10000),show)
    def compare(self):
        if self.busy:return
        args=(self.candidate.currentData(),self.baseline.currentData(),self.horizon.value())
        if not all(args[:2]):self.status.setText('请选择两个实际研究。');return
        self.last_result=None;self.details.setPlainText('{}')
        self.status.setText('正在核对来源与共同样本…')
        def show(value):
            if args!=(self.candidate.currentData(),self.baseline.currentData(),self.horizon.value()):return
            self.last_result=value;self.details.setPlainText(encode(value))
            c=value['coverage']
            self.status.setText(f"共同成熟观测 {c['mature_common_rows']}；有效配对IC时点 {c['paired_ic_timestamps']}。只读诊断，不认证Alpha。")
        self.work(lambda:compare_candidate(self.window.output,*args),show)
    def open_source(self,control):
        run_id=control.currentData()
        if run_id:self.window.open_run(run_id)
