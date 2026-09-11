"""Browse durable research notes and re-check their actual source archives."""
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QLineEdit,QComboBox,QCheckBox,QListWidget,QListWidgetItem
from quantlab.agent.research_memory import ResearchMemory
from quantlab.storage.codec import encode
from .business_view import BusinessDetails, LABELS
from .widgets import button,label,row

LABELS.update({'memory_id':'研究记忆编号','candidate_id':'候选身份','hypothesis_id':'关联假设',
    'statement':'研究陈述','mechanism':'机制假设','falsification':'可证伪条件','assessment':'作者暂定分类',
    'review_state':'复核状态','claim_verified':'文字结论已验证','source_integrity':'当前来源完整性',
    'evidence_checks':'来源校验','supersedes':'被本记录修订的旧记录','superseded_by':'后续修订',
    'next_action':'下一步','pointer':'归档字段路径','source_sha256':'归档内容校验值','value_hash':'字段值校验值',
    'factor_definition_current':'当前因子定义仍匹配','origin':'记录来源','relation':'作者标注的证据关系'})


class ResearchMemoryDialog(QDialog):
    def __init__(self, window, selected_id=None):
        super().__init__(window)
        self.window=window; self.service=ResearchMemory(window.output)
        self.offset=0; self.total=0; self.generation=0; self.current=None
        self.setWindowTitle('结构化研究记忆 · 假设、结论与证据'); self.resize(1060,820)
        box=QVBoxLayout(self)
        box.addWidget(label('这里保存研究笔记，不是聊天摘要。支持/反对均为待复核解释；来源校验不代表Alpha成立。通过聊天保存新记录，修订不会覆盖旧记录。','note',True))
        self.query=QLineEdit(); self.query.setPlaceholderText('搜索标题、陈述、机制、局限或下一步')
        self.factor=QLineEdit(); self.factor.setPlaceholderText('精确因子编号，留空不限')
        self.kind=QComboBox()
        for title,value in [('全部记录',''),('研究假设','hypothesis'),('结论草稿','finding')]: self.kind.addItem(title,value)
        self.history=QCheckBox('包含已被修订的旧记录')
        box.addWidget(row(self.query,self.factor,self.kind,self.history,button('检索',self.search,True)))
        self.listing=QListWidget(); self.listing.setMaximumHeight(170); box.addWidget(self.listing)
        self.previous=button('上一页',lambda:self.move(-20)); self.following=button('下一页',lambda:self.move(20))
        box.addWidget(row(self.previous,self.following,button('重新核对当前来源',self.recheck)))
        self.details=BusinessDetails({}); box.addWidget(self.details,1)
        self.sources=QListWidget(); self.sources.setMaximumHeight(110); box.addWidget(self.sources)
        box.addWidget(row(button('打开选中实验',self.open_source),
                         button('查看关联假设',lambda:self.related('hypothesis_id')),
                         button('查看旧记录',lambda:self.related('supersedes')),
                         button('查看后续修订',lambda:self.related('superseded_by'))))
        self.status=label('尚未读取。','muted',True); box.addWidget(self.status)
        self.listing.currentItemChanged.connect(lambda item,_:self.load(item.data(Qt.ItemDataRole.UserRole)) if item else None)
        self.query.returnPressed.connect(self.search)
        if selected_id: self.load(selected_id)
        else: self.search()

    def search(self):
        self.offset=0; self.refresh()

    def move(self, delta):
        self.offset=max(0,self.offset+delta); self.refresh()

    def refresh(self):
        self.generation+=1; generation=self.generation
        args=dict(query=self.query.text().strip(),factor_id=self.factor.text().strip(),kind=self.kind.currentData(),include_superseded=self.history.isChecked(),offset=self.offset,limit=20)
        self.current=None; self.sources.clear(); self.details.setPlainText('{}')
        self.previous.setEnabled(False); self.following.setEnabled(False)
        self.status.setText('正在检索结构化记录…')
        def done(result,error):
            if sip.isdeleted(self) or generation!=self.generation: return
            if error: self.status.setText('检索未完成：'+error); return
            self.listing.clear(); self.total=result['total']
            for record in result['records']:
                item=QListWidgetItem(('假设' if record['kind']=='hypothesis' else '结论草稿')+' · '+record['title']+' · '+record['factor_id'])
                item.setData(Qt.ItemDataRole.UserRole,record['memory_id']); self.listing.addItem(item)
            self.previous.setEnabled(self.offset>0); self.following.setEnabled(result['next_offset'] is not None)
            self.status.setText(f'共 {self.total} 条记录，本页 {len(result["records"])} 条。选择记录时重新核对来源。')
        self.window.async_call(lambda:self.service.store.search(**args),done,guarded=False)

    def load(self, memory_id):
        self.generation+=1; generation=self.generation
        self.current=None; self.sources.clear(); self.status.setText('正在读取记录并核对归档…')
        def done(result,error):
            if sip.isdeleted(self) or generation!=self.generation: return
            if error: self.details.setPlainText('{}'); self.status.setText('记忆不可读取：'+error); return
            self.current=result['record']; self.details.setPlainText(encode(result))
            states={'verified':'引用与当前归档一致','no_evidence':'尚无实验证据的假设','source_changed':'来源已变化，不可当作当前事实','unavailable':'来源缺失或无法核验'}
            self.status.setText(states[result['source_integrity']]+'；文字解释仍是待复核草稿。')
            for evidence,check in zip(self.current['evidence'],result['evidence_checks']):
                item=QListWidgetItem(check['status']+' · '+evidence['run_id'][:8]+' · '+evidence['pointer'])
                item.setData(Qt.ItemDataRole.UserRole,evidence['run_id']); self.sources.addItem(item)
        self.window.async_call(lambda:self.service.get(memory_id),done,guarded=False)

    def recheck(self):
        if self.current: self.load(self.current['memory_id'])

    def related(self, key):
        value=(self.current or {}).get(key)
        if value: self.load(value)
        else: self.status.setText('当前记录没有该关联。')

    def open_source(self):
        item=self.sources.currentItem()
        if item is None: self.status.setText('请先选择实际实验引用。'); return
        run_id=item.data(Qt.ItemDataRole.UserRole)
        try:
            self.window.catalog.file(run_id,'experiment.json')
            self.hide(); self.window.open_run(run_id)
        except (ValueError,OSError): self.status.setText('来源已不可读取，记忆原记录仍保留。')
