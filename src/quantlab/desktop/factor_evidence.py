"""Read-only factor evidence discovery over existing research artifacts."""
import json

from PyQt6 import sip
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QPlainTextEdit

from quantlab.trading.research_evidence import find_factor_evidence, archive_research_reference
from quantlab.storage.codec import encode
from .widgets import button, label, row, table
from .business_view import BusinessDetails


class FactorEvidenceDialog(QDialog):
    def __init__(self, window):
        super().__init__(window); self.window = window; self.request_generation = 0; self.offset = 0
        self.output = window.output; self.root_epoch = getattr(window, 'epoch', None)
        self.data_root = getattr(window,'data_root',None); self.closed = False; self.page_history = []
        self.setWindowTitle('因子证据发现（只读）'); self.resize(1080, 760)
        self.factor = QLineEdit(); self.factor.setPlaceholderText('精确 factor_id，例如 BASE.MOMENTUM')
        self.version = QLineEdit(); self.version.setPlaceholderText('可选 factor_version；留空不限制')
        self.params = QPlainTextEdit(); self.params.setMaximumHeight(70); self.params.setPlaceholderText('可选 parameters JSON；留空=不按参数过滤；{}=只匹配空参数')
        self.status = label('仅按 factor_id/version/params 身份查找已有归档；名称相同不算同一规则。', 'note', True)
        self.results = None; self.page = None; self.rows = []; self.next_offset = None
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(row(self.factor, self.version, button('查询', lambda: self.reload(reset=True), True)))
        layout.addWidget(self.params)
        layout.addWidget(row(button('上一页', self.previous), button('下一页', self.next),
                             button('查看所选实验的研究关联',self.open_links)))
        self.body = layout
        self.finished.connect(self._finished)
        for control in (self.factor,self.version):control.textChanged.connect(self._input_changed)
        self.params.textChanged.connect(self._input_changed)

    def _valid_context(self):
        return (not self.closed and not sip.isdeleted(self) and not sip.isdeleted(self.window)
                and not getattr(self.window,'closing',False)
                and self.output == getattr(self.window,'output',None)
                and self.data_root == getattr(self.window,'data_root',None)
                and self.root_epoch == getattr(self.window,'epoch',None))

    def _input_changed(self, *_):
        self.request_generation += 1; self.offset = 0; self.page_history = []
        self._clear_results()

    def _finished(self, *_):
        self.closed = True; self.request_generation += 1; self.rows = []

    def closeEvent(self, event):
        self._finished();super().closeEvent(event)

    def _parse_params(self):
        text = self.params.toPlainText().strip()
        if not text:
            return None
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError('可选参数过滤必须是JSON对象；留空表示不过滤。')
        return value

    def _clear_results(self):
        if self.results is not None:
            self.body.removeWidget(self.results); self.results.deleteLater(); self.results = None
        if self.page is not None:
            self.body.removeWidget(self.page); self.page.deleteLater(); self.page = None
        self.rows = []; self.next_offset = None

    def reload(self, reset=False):
        self.request_generation += 1; self._clear_results()
        if not self._valid_context():
            self.status.setText('工作空间或页面已变化，请重新打开证据查询。');return
        factor_id = self.factor.text().strip()
        version = self.version.text().strip() or None
        try: params = self._parse_params()
        except Exception as exc:
            self._clear_results(); self.status.setText('查询失败：' + str(exc)); return
        if reset:self.offset = 0; self.page_history = []
        request = self.request_generation; output = self.output; epoch = self.root_epoch; offset = self.offset
        self._clear_results(); self.status.setText('正在只读扫描研究结果目录…')
        def work():
            return find_factor_evidence(output, factor_id=factor_id, factor_version=version, parameters=params,
                                        offset=offset, limit=20, scan_budget=60)
        def done(result, error):
            if not self._valid_context() or request != self.request_generation:return
            if error:
                self._clear_results(); self.status.setText('查询失败：' + error); return
            self.rows = result['matches']; self.next_offset = result['next_offset']
            self.status.setText(f"扫描 {result['scanned']} 条；返回 {len(self.rows)}；错配 {len(result['mismatches'])}；损坏/不可读 {len(result['errors'])}；has_more={result['has_more']}。metadata discovery 不等于深验。")
            self.results = table(['run_id', '状态', '版本', '范围', '限制'],
                [[r['source']['run_id'][:8], r.get('status'), r['rule_identity'].get('factor_version'),
                  f"{r['range'].get('start')} → {r['range'].get('end')}", '；'.join(r.get('limitations') or [])[:80]] for r in self.rows],
                lambda i: self.open_row(i))
            self.body.addWidget(self.results, 1)
            self.page = BusinessDetails({'pagination': {k: result[k] for k in ('offset','next_offset','has_more','scanned','scan_budget','incomplete')},
                                         'mismatches': result['mismatches'], 'errors': result['errors'],
                                         'parameter_filter_note': result['parameter_filter_note']})
            self.body.addWidget(self.page, 1)
        self.window.async_call(work, done, guarded=False)

    def previous(self):
        if self.page_history:
            self.offset = self.page_history.pop();self.reload()

    def next(self):
        if self.next_offset is not None:
            self.page_history.append(self.offset)
            self.offset = self.next_offset; self.reload()

    def open_links(self):
        if not self._valid_context() or self.results is None:return
        index=self.results.currentRow()
        if not 0<=index<len(self.rows):
            self.status.setText('请先选择一条实验记录。');return
        dialog=RunResearchLinksDialog(self.window,self.rows[index]['source'])
        self.window.show_dialog(dialog)

    def open_row(self, index):
        if not self._valid_context():self._clear_results();return
        if not (0 <= index < len(self.rows)): return
        expected = dict(self.rows[index]['source']['fingerprint'])
        rid = self.rows[index]['source']['run_id']; output = self.output; epoch = self.root_epoch; request = self.request_generation
        def work():
            ref = archive_research_reference(output, rid)
            if ref['source']['run_id'] != rid or ref['source']['fingerprint'] != expected:
                raise ValueError('归档来源在查询后变化，拒绝打开旧引用')
            return ref
        def done(result, error):
            if not self._valid_context() or request != self.request_generation:return
            if error:
                self._clear_results();self.status.setText('打开拒绝：' + error); return
            self.window.open_run(result['source']['run_id'])
        self.window.async_call(work, done, guarded=False)


class RunResearchLinksDialog(QDialog):
    """Paged view of the same read-only service exposed to native Chat/MCP."""
    def __init__(self,window,source):
        super().__init__(window);self.window=window;self.output=window.output
        self.epoch=getattr(window,'epoch',None);self.data_root=getattr(window,'data_root',None)
        self.source=dict(source);self.offset=0;self.next_offset=None;self.history=[]
        self.inventory=None;self.generation=0;self.closed=False
        self.setWindowTitle('实验 → 检验族 / 假设 / 结论（只读）');self.resize(1050,760)
        box=QVBoxLayout(self);self.status=label('只读取本工作空间的精确身份关联，不自动登记或执行。','note',True)
        box.addWidget(self.status)
        box.addWidget(row(button('刷新',self.refresh),button('上一页',self.previous),button('下一页',self.next)))
        self.details=BusinessDetails({});box.addWidget(self.details,1)
        self.finished.connect(self.finished_view);self.load()
    def finished_view(self,*_):self.closed=True;self.generation+=1
    def closeEvent(self,event):self.finished_view();super().closeEvent(event)
    def valid(self):
        return (not self.closed and not sip.isdeleted(self) and not sip.isdeleted(self.window)
                and not getattr(self.window,'closing',False) and self.output==self.window.output
                and self.data_root==getattr(self.window,'data_root',None)
                and self.epoch==getattr(self.window,'epoch',None))
    def refresh(self):self.offset=0;self.history=[];self.inventory=None;self.load()
    def next(self):
        if self.next_offset is not None:
            self.history.append(self.offset);self.offset=self.next_offset;self.load()
    def previous(self):
        if self.history:self.offset=self.history.pop();self.load()
    def load(self):
        if not self.valid():return
        self.generation+=1;generation=self.generation;offset=self.offset
        self.next_offset=None;self.details.setPlainText('{}')
        self.status.setText('正在只读核对来源与关联…')
        output=self.output;source=dict(self.source)
        def work():
            from quantlab.agent.research_links import get_run_research_links
            current=archive_research_reference(output,source['run_id'])
            if current['source']['fingerprint']!=source['fingerprint']:
                raise ValueError('目标归档已变化，需重新查询因子证据')
            return get_run_research_links(output,source['run_id'],offset=offset,limit=10)
        def done(value,error):
            if not self.valid() or generation!=self.generation:return
            if error:self.status.setText('关联读取失败：'+error);return
            inventory=value.get('inventory_digest')
            if self.inventory is not None and inventory!=self.inventory:
                self.status.setText('关联目录已变化，点击刷新重新分页。');return
            self.inventory=inventory;self.next_offset=value.get('next_offset')
            self.details.setPlainText(encode(value))
            self.status.setText('本页状态：'+value['status']+'；扫描 '+str(value.get('scanned',0))+
                ' 项；错误 '+str(len(value.get('errors',[])))+'。本地关联不是全局检验或Alpha认证。')
        self.window.async_call(work,done,guarded=False)


__all__ = ['FactorEvidenceDialog','RunResearchLinksDialog']
