"""Native read-only Factory report, explicit export, and evidence-only AI handoff."""
from pathlib import Path
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QTabWidget,QPlainTextEdit,QFileDialog
from quantlab.agent.factory_report import build_factory_report,render_factory_report_markdown
from quantlab.agent.evidence_review import factory_review_prompt
from quantlab.storage.codec import encode
from .widgets import label,button,row


def export_factory_report(output,proposal_id,expected_digest,destination,*,format='markdown'):
    """Write an explicitly chosen new report, never overwrite prior evidence/files."""
    if format not in ('markdown','json'):raise ValueError('仅支持Markdown或JSON报告')
    if not isinstance(expected_digest,str) or not expected_digest:raise ValueError('请先读取报告再导出')
    report=build_factory_report(output,proposal_id,limit=12,expected_digest=expected_digest)
    if report.get('has_more'):raise ValueError('报告未完整读取，不导出为完整报告')
    text=render_factory_report_markdown(report) if format=='markdown' else encode(report)
    payload=text.encode('utf-8')
    if len(payload)>2_000_000:raise ValueError('报告超过导出大小限制')
    path=Path(destination)
    if not path.is_absolute():raise ValueError('导出目标须为完整文件路径')
    with path.open('xb') as stream:stream.write(payload)
    return {'path':str(path),'bytes':len(payload),'report_digest':report['report_digest'],
            'format':format,'snapshot_only':True,'reproduction_bundle':False}


class FactoryReportDialog(QDialog):
    def __init__(self,window,proposal_id):
        super().__init__(window);self.window=window;self.output=window.output
        self.data_root=window.data_root;self.epoch=getattr(window,'epoch',None)
        self.proposal_id=proposal_id;self.report=None;self.closed=False;self.busy=False;self.generation=0
        self.setWindowTitle('Factory研究报告 · 证据与限制');self.resize(1120,850)
        box=QVBoxLayout(self)
        box.addWidget(label('报告从保存状态及完成父归档读取，不运行统计、不自动同步或晋级。AI解释与原始证据分开保存。','note',True))
        self.status=label('正在读取报告…','muted',True);box.addWidget(self.status)
        self.refresh_button=button('重新读取报告',self.refresh)
        self.ai_button=button('让AI只读解读',self.ask_ai,True)
        self.export_button=button('导出Markdown / JSON',self.choose_export)
        box.addWidget(row(self.refresh_button,self.ai_button,self.export_button))
        tabs=QTabWidget();self.text=QPlainTextEdit();self.text.setReadOnly(True)
        self.raw=QPlainTextEdit();self.raw.setReadOnly(True)
        tabs.addTab(self.text,'研究报告');tabs.addTab(self.raw,'结构化证据');box.addWidget(tabs,1)
        self.finished.connect(self._closed);self.refresh()

    def _closed(self,*_):self.closed=True;self.generation+=1
    def closeEvent(self,event):self._closed();super().closeEvent(event)
    def valid(self):
        return (not self.closed and not sip.isdeleted(self) and not sip.isdeleted(self.window)
                and not getattr(self.window,'closing',False) and self.output==self.window.output
                and self.data_root==self.window.data_root and self.epoch==getattr(self.window,'epoch',None))
    def buttons(self):
        enabled=self.valid() and not self.busy
        self.refresh_button.setEnabled(enabled)
        for control in (self.ai_button,self.export_button):control.setEnabled(enabled and self.report is not None)
    def work(self,fn,done):
        if self.busy or not self.valid():return
        self.generation+=1;generation=self.generation;self.busy=True;self.buttons()
        def finished(value,error):
            if not self.valid() or generation!=self.generation:return
            self.busy=False
            if error:
                self.report=None;self.text.clear();self.raw.clear()
                self.status.setText('报告操作未完成：'+error+'。请重新读取，不使用旧结论。')
            else:
                try:done(value)
                except Exception as exc:
                    self.report=None;self.text.clear();self.raw.clear()
                    self.status.setText('报告不可展示：'+str(exc))
            self.buttons()
        self.window.async_call(fn,finished,guarded=False)
    def refresh(self):
        if self.busy or not self.valid():return
        self.report=None;self.text.clear();self.raw.clear();self.status.setText('只读核对Factory状态和来源…')
        def show(value):
            text=render_factory_report_markdown(value)
            self.report=value;self.text.setPlainText(text);self.raw.setPlainText(encode(value))
            self.status.setText('保存状态：'+str(value.get('status'))+'；报告指纹 '+value['report_digest']+
                                '。这是报告快照，不是完整数值复算或Alpha认证。')
        self.work(lambda:build_factory_report(self.output,self.proposal_id,limit=12),show)
    def ask_ai(self):
        if self.busy or not self.valid() or self.report is None:return
        expected=self.report['report_digest']
        def open_chat(report):
            draft=factory_review_prompt(self.proposal_id,report['report_digest'])
            opened=self.window.review_research_evidence(draft)
            self.status.setText('已准备只读解读草稿，仍需确认模型服务并点击发送；未启动新研究。' if opened
                                else '助手正在处理其他问题或无法打开；未覆盖原会话，请稍后手动重试。')
        self.work(lambda:build_factory_report(self.output,self.proposal_id,limit=12,expected_digest=expected),open_chat)
    def choose_export(self):
        if self.busy or not self.valid() or self.report is None:return
        expected=self.report['report_digest']
        path,selected=QFileDialog.getSaveFileName(self,'导出只读报告',str(Path(self.output)/('factory-report-'+self.proposal_id[:8]+'.md')),
                                               'Markdown (*.md);;JSON (*.json)')
        if not path or not self.valid():return
        format='json' if selected.startswith('JSON') else 'markdown'
        self.work(lambda:export_factory_report(self.output,self.proposal_id,expected,path,format=format),
                  lambda result:self.status.setText('已导出新报告：'+result['path']+'；未覆盖旧文件，非完整复现包。'))
