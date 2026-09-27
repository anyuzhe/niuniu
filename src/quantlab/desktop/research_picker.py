"""Reusable, read-only native Qt pickers for factor definitions and archives."""
from __future__ import annotations

import json

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
    QVBoxLayout,
)

from quantlab.app import default_registry
from quantlab.storage.codec import encode
from .widgets import button, label, row, table


class _PickerContext:
    def _capture_context(self, window):
        self.window = window
        self.output = window.output
        self.data_root = getattr(window, 'data_root', None)
        self.root_epoch = getattr(window, 'epoch', None)
        self.closed = False
        self.generation = 0

    def _valid_context(self):
        return (not self.closed and not sip.isdeleted(self) and not sip.isdeleted(self.window)
                and not getattr(self.window, 'closing', False)
                and self.output == getattr(self.window, 'output', None)
                and self.data_root == getattr(self.window, 'data_root', None)
                and self.root_epoch == getattr(self.window, 'epoch', None))

    def _invalidate(self, *_):
        self.generation += 1

    def _closed(self, *_):
        self.closed = True
        self.generation += 1

    def closeEvent(self, event):
        self._closed()
        super().closeEvent(event)


class FactorPickerDialog(_PickerContext, QDialog):
    """Choose a registered factor definition; no factor computation is performed."""
    def __init__(self, window, *, factory_only=False, factor_id=None, version=None):
        super().__init__(window)
        self._capture_context(window)
        self.factory_only = bool(factory_only)
        self.result_definition = None
        self.entries = []
        self.setWindowTitle('选择因子（定义目录）')
        self.resize(1000, 720)
        box = QVBoxLayout(self)
        note = ('Factory候选仅展示 scalar/boolean 且 available_at_rule 精确为 bar close 的定义；'
                '选择不代表有效Alpha。' if self.factory_only else
                '按注册定义检索；仅作为因子身份选择，不代表有效Alpha。')
        box.addWidget(label(note, 'note', True))
        self.search = QLineEdit()
        self.search.setPlaceholderText('按因子ID、中文名称、分类、pack 或 tags 搜索')
        box.addWidget(self.search)
        self.versions = QListWidget()
        self.versions.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        box.addWidget(self.versions, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('选择一个精确的因子ID@版本以查看定义。')
        box.addWidget(self.details, 2)
        self.status = label('未自动选择因子。', 'muted', True)
        box.addWidget(self.status)
        self.use_button = button('使用所选因子', self.use_selected, True)
        self.use_button.setEnabled(False)
        box.addWidget(row(self.use_button, button('取消', self.reject)))
        self.search.textChanged.connect(self._filter)
        self.versions.currentRowChanged.connect(self._show_selected)
        self.versions.itemSelectionChanged.connect(self._invalidate)
        self.finished.connect(self._closed)
        # describe() serializes only registered definitions/defaults/hashes; never computes values.
        registry=default_registry()
        self.entries = json.loads(encode(registry.describe()))
        self.pack_names={(f.definition.factor_id,f.definition.version):pack.pack_id
                         for pack in registry._packs.values() for f in pack.factors}
        if self.factory_only:
            self.entries = [entry for entry in self.entries if self._factory_eligible(entry)]
        self._filter()
        if factor_id is not None:
            matches = [i for i, entry in enumerate(self.entries)
                       if entry.get('definition', {}).get('factor_id') == factor_id
                       and (version is None or entry.get('definition', {}).get('version') == version)]
            if len(matches) == 1:
                self.versions.setCurrentRow(matches[0])

    @staticmethod
    def _factory_eligible(entry):
        definition = entry.get('definition') or {}
        factor_type = definition.get('factor_type')
        if isinstance(factor_type, dict):
            factor_type = factor_type.get('value')
        return factor_type in ('scalar', 'boolean') and definition.get('available_at_rule') == 'bar close'

    @staticmethod
    def _entry_label(entry):
        d = entry.get('definition') or {}
        return f"{d.get('factor_id', '?')}@{d.get('version', '?')} · {d.get('name_cn', '')} · {d.get('category', '')}"

    def _filter(self, *_):
        query = self.search.text().strip().casefold()
        self.versions.blockSignals(True)
        self.versions.clear()
        for entry in self.entries:
            d = entry.get('definition') or {}
            searchable = ' '.join(str(value) for value in (
                d.get('factor_id', ''), d.get('name_cn', ''), d.get('category', ''),
                self.pack_names.get((d.get('factor_id'),d.get('version')),''), *(d.get('tags') or ())))
            if query and query not in searchable.casefold():
                continue
            item = QListWidgetItem(self._entry_label(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.versions.addItem(item)
        self.versions.setCurrentRow(-1)
        self.versions.blockSignals(False)
        self.details.clear()
        self.use_button.setEnabled(False)
        self.generation += 1
        self.status.setText(f'匹配 {self.versions.count()} 个版本；同名条目按 ID@版本区分。')

    def _show_selected(self, row_index):
        if row_index < 0:
            self.details.clear()
            self.use_button.setEnabled(False)
            return
        item = self.versions.item(row_index)
        entry = item.data(Qt.ItemDataRole.UserRole)
        self.details.setPlainText(encode(entry))
        self.use_button.setEnabled(self._valid_context())

    def use_selected(self):
        if not self._valid_context():
            self.status.setText('工作空间或页面已变化；拒绝返回过期定义。')
            self.result_definition = None
            return
        item = self.versions.currentItem()
        if item is None:
            return
        entry = json.loads(encode(item.data(Qt.ItemDataRole.UserRole)))
        if self.factory_only and not self._factory_eligible(entry):
            self.status.setText('所选定义不符合 Factory 类型与收盘可用规则。')
            return
        self.result_definition = entry
        self.accept()

    def _closed(self, *_):
        _PickerContext._closed(self)
        if self.result() != QDialog.DialogCode.Accepted:
            self.result_definition = None


class ArchivePickerDialog(_PickerContext, QDialog):
    """Explicitly search and re-verify existing research archive references."""
    def __init__(self, window, *, kind='factor', title='选择已有研究归档'):
        super().__init__(window)
        self._capture_context(window)
        self.kind = kind
        self.result_reference = None
        self.rows = []
        self.offset = 0
        self.next_offset = None
        self.page_history = []
        self.selected_reference = None
        self.setWindowTitle(title)
        self.inventory=None
        self.resize(1080, 760)
        box = QVBoxLayout(self)
        box.addWidget(label('只读取已有归档。先点击查询；失败记录可查看但不能使用。未扫描完整时不会声称目录完整。', 'note', True))
        self.query = QLineEdit()
        self.query.setPlaceholderText('搜索问题/因子等归档文字')
        self.search_button = button('查询', lambda: self.search(reset=True), True)
        box.addWidget(row(self.query, self.search_button))
        self.status = label('尚未查询。', 'muted', True)
        box.addWidget(self.status)
        self.results = None
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('选择一条记录查看完整原始引用。')
        box.addWidget(self.details, 2)
        self.previous_button = button('上一页', self.previous)
        self.next_button = button('下一页', self.next)
        self.use_button = button('使用所选归档', self.use_selected, True)
        self.use_button.setEnabled(False)
        box.addWidget(row(self.previous_button, self.next_button, self.use_button,
                          button('取消', self.reject)))
        self.previous_button.setEnabled(False);self.next_button.setEnabled(False)
        self.page_evidence=QPlainTextEdit();self.page_evidence.setReadOnly(True);self.page_evidence.setMaximumHeight(120)
        box.addWidget(self.page_evidence)
        self.query.textChanged.connect(self._query_changed)
        self.finished.connect(self._closed)

    def _clear_rows(self):
        self.selected_reference=None;self.result_reference=None;self.rows=[];self.next_offset=None
        if self.results is not None:
            self.results.blockSignals(True);self.layout().removeWidget(self.results);self.results.deleteLater();self.results=None
        self.details.clear();self.page_evidence.clear();self.use_button.setEnabled(False)
        self.previous_button.setEnabled(False);self.next_button.setEnabled(False)

    def _query_changed(self,*_):
        self.generation+=1;self.offset=0;self.page_history=[];self.inventory=None;self._clear_rows()
        self.status.setText('检索条件已变化，点击查询读取；旧选择已清除。')

    @staticmethod
    def _row_text(reference):
        source = reference.get('source') or {}
        identity = reference.get('rule_identity') or {}
        span = reference.get('range') or {}
        rid = str(source.get('run_id') or '')
        question = reference.get('question') or (reference.get('parameters') or {}).get('question') or ''
        factor = identity.get('factor_id') or '—'
        version = identity.get('factor_version') or '—'
        interval = f"{span.get('start') or span.get('first_day') or '—'} → {span.get('end') or span.get('last_day') or '—'}"
        return [rid[:8], question, f'{factor}@{version}', interval, reference.get('status')]

    def search(self, *, reset=False):
        self.generation += 1
        request = self.generation
        if not self._valid_context():
            self.status.setText('工作空间或页面已变化；拒绝查询。')
            return
        if reset:
            self.offset = 0
            self.page_history = []
            self.inventory = None
        offset = self.offset
        output, query, kind = self.output, self.query.text().strip(), self.kind
        self._clear_rows()
        self.status.setText('正在只读扫描已有研究归档…')

        def work():
            from quantlab.trading import research_evidence
            return research_evidence.find_research_archives(
                output, query=query, kind=kind, offset=offset, limit=20, scan_budget=60)

        def done(value, error):
            if not self._valid_context() or request != self.generation:
                return
            if error:
                self.rows = []
                self.next_offset = None
                self.status.setText('查询失败：' + str(error))
                return
            inventory=value.get('inventory_digest')
            if self.inventory is not None and inventory!=self.inventory:
                self._clear_rows();self.status.setText('归档目录已变化，请点击查询从第一页重新读取。');return
            self.inventory=inventory
            self.page_evidence.setPlainText(encode({k:value.get(k) for k in ('errors','offset','next_offset','scanned','scan_budget','incomplete','inventory_digest')}))
            matches = [r for r in value.get('matches', []) if r.get('kind') == kind]
            self.rows = matches
            self.next_offset = value.get('next_offset')
            self._render_rows()
            errors = value.get('errors') or []
            partial = bool(value.get('incomplete') or value.get('has_more') or errors)
            self.status.setText(
                f"本页扫描 {value.get('scanned', 0)} 项，匹配 {len(matches)} 项；坏档/错误 {len(errors)} 项。"
                + ('目录或本页不完整，不能据此声称全部结果。' if partial else '本次有界扫描已完成。'))

        self.window.async_call(work, done, guarded=False)

    def _render_rows(self):
        if self.results is not None:
            self.layout().removeWidget(self.results)
            self.results.deleteLater()
        self.results = table(['run短ID', '问题', '因子@版本', '区间', '状态'],
                             [self._row_text(r) for r in self.rows])
        self.results.itemSelectionChanged.connect(self._selection_changed)
        self.layout().insertWidget(3, self.results, 2)
        self.previous_button.setEnabled(bool(self.page_history))
        self.next_button.setEnabled(self.next_offset is not None)

    def _selection_changed(self):
        self.generation += 1
        index = self.results.currentRow() if self.results is not None else -1
        self.selected_reference = self.rows[index] if 0 <= index < len(self.rows) else None
        self.details.setPlainText(encode(self.selected_reference) if self.selected_reference else '')
        self.use_button.setEnabled(bool(self.selected_reference
                                        and self.selected_reference.get('status') == 'completed'
                                        and self._valid_context()))

    def previous(self):
        if not self.page_history:
            return
        self.offset = self.page_history.pop()
        self.search()

    def next(self):
        if self.next_offset is None:
            return
        self.page_history.append(self.offset)
        self.offset = self.next_offset
        self.search()

    def use_selected(self):
        selected = self.selected_reference
        if not selected or selected.get('status') != 'completed' or not self._valid_context():
            return
        self.generation += 1
        request = self.generation
        source = selected.get('source') or {}
        rid = source.get('run_id')
        expected_fingerprint = source.get('fingerprint')
        expected_kind = selected.get('kind')
        expected_status = selected.get('status')
        output = self.output
        self.result_reference = None
        self.use_button.setEnabled(False)
        self.status.setText('正在重读归档并核对 SHA、kind 与 status…')

        def work():
            from quantlab.trading import research_evidence
            current = research_evidence.archive_research_reference(output, rid)
            current_source = current.get('source') or {}
            if (current_source.get('run_id') != rid
                    or current_source.get('fingerprint') != expected_fingerprint
                    or current.get('kind') != expected_kind
                    or current.get('status') != expected_status):
                raise ValueError('所选归档来源 SHA、kind 或 status 已变化，拒绝使用且不会自动替换。')
            return current

        def done(value, error):
            if not self._valid_context() or request != self.generation:
                return
            if error:
                self.result_reference = None
                self.status.setText('使用拒绝：' + str(error))
                self.use_button.setEnabled(bool(self.selected_reference
                                                and self.selected_reference.get('status') == 'completed'))
                return
            if self.selected_reference is None or self.selected_reference.get('source', {}).get('run_id') != rid:
                self.result_reference = None
                return
            self.result_reference = value
            self.accept()

        self.window.async_call(work, done, guarded=False)

    def _closed(self, *_):
        _PickerContext._closed(self)
        if self.result() != QDialog.DialogCode.Accepted:
            self.result_reference = None
            self.selected_reference = None
            self.rows = []


__all__ = ['FactorPickerDialog', 'ArchivePickerDialog']
