"""Explicit read-only input preflight over the existing local-data inspector.

No qualification, normalization, row filtering, research execution or writes.
The result belongs to one captured scope, not a permanent readiness certificate.
"""
from copy import deepcopy
from pathlib import Path
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidgetItem
from quantlab.agent.local_data_tools import LocalMarketDataTools
from quantlab.storage.codec import encode
from .widgets import label, button, row, table
from .business_view import BusinessDetails


class LocalDataReadinessDialog(QDialog):
    def __init__(self, window, scope, *, scope_current=None):
        super().__init__(window)
        self.window=window;self.scope=deepcopy(scope);self.scope_current=scope_current
        self.output=Path(window.output).resolve()
        self.root=Path(window.data_root).resolve() if window.data_root else None
        self.epoch=getattr(window,'epoch',None)
        self.output_identity=self.identity(self.output);self.root_identity=self.identity(self.root)
        self.closed=False;self.busy=False;self.report=None;self.generation=0
        self.setWindowTitle('研究输入可加载性 · 只读检查');self.resize(1080,760)
        box=QVBoxLayout(self)
        box.addWidget(label('只读取明确范围并复用原生产加载器。检查不填零、不删行、不转换数据、不计算因子、不保存提案或启动研究。','note',True))
        box.addWidget(label('当前入口支持已有MQC格式的日线/5分钟、raw/qfq，每次1–20只证券。受管理数据包须用对应核验入口；不自动回退或只检查前20只。','muted',True))
        self.scope_label=label(encode(self.scope),'muted',True);box.addWidget(self.scope_label)
        self.refresh_button=button('重新读取同一范围',self.reload)
        box.addWidget(row(self.refresh_button,button('关闭',self.close)))
        self.listing=table(['证券','可加载性','原始行数','空值字段与条数','原加载器错误'],[])
        box.addWidget(self.listing,1)
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.status=label('尚未检查。','muted',True);box.addWidget(self.status)
        self.finished.connect(self._finished)
        self.reload()

    @staticmethod
    def identity(path):
        if path is None:return None
        try:
            info=path.stat();return info.st_dev,info.st_ino
        except OSError:return None

    def valid_context(self):
        if self.closed or sip.isdeleted(self) or sip.isdeleted(self.window) or getattr(self.window,'closing',False):return False
        try:
            root=Path(self.window.data_root).resolve() if self.window.data_root else None
            return (self.output==Path(self.window.output).resolve() and self.root==root
                and self.epoch==getattr(self.window,'epoch',None)
                and self.output_identity is not None and self.output_identity==self.identity(self.output)
                and self.root_identity==self.identity(self.root)
                and (self.scope_current is None or self.scope_current()))
        except (OSError,RuntimeError,TypeError,ValueError):return False

    def clear_result(self):
        self.report=None;self.listing.setRowCount(0);self.details.setPlainText('{}')

    def _finished(self,*_):
        self.closed=True;self.generation+=1;self.report=None

    def closeEvent(self,event):
        self._finished();super().closeEvent(event)

    def reload(self,*_):
        if self.busy:return
        self.clear_result()
        if not self.valid_context():
            self.refresh_button.setEnabled(False)
            self.status.setText('表单、工作空间、数据根或窗口已变化，请从当前研究表单重新检查；旧结果不再适用。');return
        self.busy=True;self.generation+=1;generation=self.generation
        self.refresh_button.setEnabled(False);self.status.setText('正在只读检查指定行情范围…')
        scope=deepcopy(self.scope);root=self.root;root_identity=self.root_identity
        def work():
            # No QWidget access from the worker; the captured root is checked on
            # both sides of I/O, and the existing inspector enforces path bounds.
            if root_identity!=LocalDataReadinessDialog.identity(root):raise ValueError('数据目录身份在读取前已变化')
            return LocalMarketDataTools(root).call('inspect_local_market_data',scope)
        def done(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            if self.closed:return
            if generation!=self.generation or not self.valid_context():
                self.clear_result();self.refresh_button.setEnabled(False)
                self.status.setText('输入范围或工作空间已变化，已丢弃过期检查结果。');return
            self.refresh_button.setEnabled(True)
            try:
                if error:raise ValueError(str(error))
                if not isinstance(value,dict) or value.get('tool')!='inspect_local_market_data':raise ValueError('数据检查回执格式错误')
                if value.get('ok') is not True:
                    issue=value.get('error') or {}
                    self.details.setPlainText(encode(value))
                    self.status.setText('本范围未完成检查：'+str(issue.get('code',''))+' · '+str(issue.get('message','未知错误')));return
                data=value['data'];records=data['records'];symbols=scope['symbols'].replace(',',' ').split()
                if (not isinstance(records,list) or [r['symbol'] for r in records]!=symbols
                    or any(type(r.get('loadable')) is not bool for r in records)
                    or any(data.get(k)!=scope[k] for k in ('timeframe','adjustment','start','end'))
                    or type(data.get('request_loadable')) is not bool
                    or data['request_loadable']!=all(r['loadable'] for r in records)):
                    raise ValueError('检查回执与所选证券/范围/状态不一致')
                self.report=deepcopy(value);self.listing.setRowCount(len(records))
                for i,record in enumerate(records):
                    nulls='；'.join(f'{k}: {v}' for k,v in record.get('null_counts',{}).items() if v)
                    values=[record['symbol'],'可加载' if record['loadable'] else '阻塞',
                        record.get('rows','未读取'),nulls or '未发现 / 未读取',record.get('error','')]
                    for j,cell in enumerate(values):self.listing.setItem(i,j,QTableWidgetItem(str(cell)))
                self.details.setPlainText(encode(value))
                count=sum(r['loadable'] for r in records)
                self.status.setText(f'本次检查 {len(records)} 只：可加载 {count}，阻塞 {len(records)-count}。'
                    '这不是数据完整性、Strict PIT、公司行动或Alpha认证；因子预热、标签成熟和统计样本仍待研究核验。未修改数据或提交任务。')
            except (ValueError,TypeError,KeyError,AttributeError) as exc:
                self.clear_result();self.status.setText('检查未完成：'+str(exc)+'；原数据未修改。')
        try:self.window.async_call(work,done,guarded=False)
        except Exception as exc:done(None,str(exc))
