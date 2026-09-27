import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

from quantlab.app import default_registry
from quantlab.desktop.research_picker import ArchivePickerDialog, FactorPickerDialog
from quantlab.storage.codec import encode
from quantlab.trading import research_evidence


_APP = QApplication.instance() or QApplication([])


def reference(run_id, *, kind='factor', status='completed', sha='a' * 64):
    return {
        'kind': kind, 'status': status, 'question': '测试问题',
        'horizons': [5], 'adjustment': 'qfq',
        'rule_identity': {'factor_id': 'BASE.MOMENTUM', 'factor_version': '1.0.0'},
        'range': {'start': '2024-01-01', 'end': '2024-02-01'},
        'source': {'run_id': run_id, 'fingerprint': {'sha256': sha}},
    }


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.output = '/tmp/picker-isolated-output'
        self.data_root = '/tmp/picker-isolated-data'
        self.epoch = 1
        self.closing = False
        self.pending = []

    def async_call(self, function, callback, guarded=False):
        self.pending.append((function, callback))

    def complete(self, index=0):
        function, callback = self.pending.pop(index)
        try:
            callback(function(), None)
        except Exception as exc:
            callback(None, str(exc))


class ResearchPickerTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()

    def test_factor_picker_exact_identity_and_explicit_accept(self):
        dialog = FactorPickerDialog(self.window)
        self.assertIsNone(dialog.result_definition)
        self.assertGreater(dialog.versions.count(), 1)
        dialog.search.setText('BASE.MOMENTUM')
        self.assertGreater(dialog.versions.count(), 0)
        self.assertIsNone(dialog.result_definition)
        target = next(i for i, entry in enumerate(dialog.entries)
                      if entry['definition']['factor_id'] == 'BASE.MOMENTUM')
        # Duplicate versions remain separate ID@version rows.
        dialog.search.clear()
        dialog.versions.setCurrentRow(target)
        selected = dialog.versions.currentItem().data(Qt.ItemDataRole.UserRole)
        self.assertIn('formula', dialog.details.toPlainText())
        dialog.use_selected()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result_definition, selected)
        self.assertEqual(set(dialog.result_definition), {'definition', 'defaults', 'code_hash'})

    def test_factory_filter_reuses_exact_definition_contract(self):
        dialog = FactorPickerDialog(self.window, factory_only=True)
        self.assertTrue(dialog.entries)
        for entry in dialog.entries:
            definition = entry['definition']
            factor_type = definition['factor_type']
            if isinstance(factor_type, dict):
                factor_type = factor_type.get('value')
            self.assertIn(factor_type, ('scalar', 'boolean'))
            self.assertEqual(definition['available_at_rule'], 'bar close')
        self.assertIsNone(dialog.result_definition)

    def test_archive_search_is_explicit_kind_filtered_and_paginated_by_cursor(self):
        a, b = reference('run-a'), reference('run-b', kind='execution')
        pages = []

        def finder(output, **kwargs):
            pages.append(kwargs)
            return {'matches': [a, b], 'errors': [{'run_id': 'bad', 'error': 'bad archive'}],
                    'offset': kwargs['offset'], 'next_offset': 41 if kwargs['offset'] == 0 else None,
                    'has_more': kwargs['offset'] == 0, 'scanned': 20,
                    'inventory_digest': 'inventory', 'incomplete': True}

        dialog = ArchivePickerDialog(self.window, kind='factor')
        self.assertEqual(self.window.pending, [])
        with patch.object(research_evidence, 'find_research_archives', finder):
            dialog.search_button.click()
            self.assertEqual(len(self.window.pending), 1)
            self.window.complete()
            self.assertEqual(len(dialog.rows), 1)
            self.assertEqual(dialog.rows[0]['kind'], 'factor')
            self.assertIn('坏档/错误 1', dialog.status.text())
            self.assertTrue(dialog.status.text().find('不完整') >= 0)
            dialog.next_button.click()
            self.assertEqual(len(self.window.pending), 1)
            self.window.complete()
            self.assertEqual(pages[-1]['offset'], 41)

    def test_archive_use_rechecks_sha_kind_status_and_returns_fresh_reference(self):
        listed = reference('run-one')
        verified = reference('run-one')
        dialog = ArchivePickerDialog(self.window)
        with patch.object(research_evidence, 'find_research_archives',
                          lambda *a, **k: {'matches': [listed], 'errors': [], 'next_offset': None,
                                           'scanned': 1, 'incomplete': False, 'has_more': False}):
            dialog.search()
            self.window.complete()
        dialog.results.selectRow(0)
        self.assertTrue(dialog.use_button.isEnabled())
        with patch.object(research_evidence, 'archive_research_reference', lambda *a: verified):
            dialog.use_selected()
            self.window.complete()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result_reference, verified)

    def test_changed_source_is_rejected_without_substituting_another_archive(self):
        listed = reference('run-one')
        changed = reference('run-one', sha='c' * 64)
        dialog = ArchivePickerDialog(self.window)
        with patch.object(research_evidence, 'find_research_archives',
                          lambda *a, **k: {'matches': [listed], 'errors': [], 'next_offset': None,
                                           'scanned': 1, 'incomplete': False, 'has_more': False}):
            dialog.search()
            self.window.complete()
        dialog.results.selectRow(0)
        with patch.object(research_evidence, 'archive_research_reference', lambda *a: changed):
            dialog.use_selected()
            self.window.complete()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dialog.result_reference)
        self.assertIn('拒绝', dialog.status.text())

    def test_stale_search_callback_is_ignored_after_root_change_or_close(self):
        dialog = ArchivePickerDialog(self.window)
        dialog.search()
        self.window.output = '/tmp/other-output'
        self.window.complete()
        self.assertEqual(dialog.rows, [])
        self.assertIsNone(dialog.result_reference)

        second = ArchivePickerDialog(self.window)
        second.search()
        second.close()
        self.window.complete()
        self.assertEqual(second.rows, [])
        self.assertIsNone(second.result_reference)

    def test_delayed_selection_change_invalidates_old_verification(self):
        first, second = reference('run-one'), reference('run-two')
        dialog = ArchivePickerDialog(self.window)
        with patch.object(research_evidence, 'find_research_archives',
                          lambda *a, **k: {'matches': [first, second], 'errors': [], 'next_offset': None,
                                           'scanned': 2, 'incomplete': False, 'has_more': False}):
            dialog.search()
            self.window.complete()
        dialog.results.selectRow(0)
        dialog.use_selected()
        self.assertEqual(len(self.window.pending), 1)
        dialog.results.selectRow(1)
        # Finishing the first SHA check cannot accept or replace the now-selected run.
        with patch.object(research_evidence, 'archive_research_reference', lambda *a: first):
            self.window.complete()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dialog.result_reference)


if __name__ == '__main__':
    unittest.main()
