"""Offscreen tests of the real strategy editor; no data root, model or execution."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QDialog
from quantlab.desktop.agent_proposals import ProposalDialog
from quantlab.desktop.strategy_workspace import StrategyWorkspaceDialog
from quantlab.storage.codec import encode
from quantlab.trading.strategy_package import compile_strategy
from quantlab.theory.templates import templates
from test_strategy_package_cli import package_fixture
from test_strategy_package_desktop import _Host

class StrategyWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if cls.app.platformName() != 'offscreen': raise RuntimeError('offscreen required')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.host = _Host(self.root)
        self.editor = StrategyWorkspaceDialog(self.host, self.host)
        self.addCleanup(self.close)

    def close(self):
        if not sip.isdeleted(self.editor): self.editor.close(); sip.delete(self.editor)
        self.host.close(); sip.delete(self.host); QApplication.processEvents()

    def test_blank_editor_does_not_invent_scope_cash_or_run(self):
        self.assertEqual(self.editor.scope['symbols'].text(), '')
        self.assertEqual(self.editor.scope['start'].text(), '')
        self.assertEqual(self.editor.execution['initial_cash'].text(), '')
        self.assertFalse(self.editor.validate_preview())
        self.assertFalse(self.editor.use_button.isEnabled())
        self.assertFalse(self.editor.isVisible())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_import_roundtrip_preserves_exact_hash_and_advanced_fields(self):
        package = package_fixture()
        package['spec']['execution'].update(entry_window_minutes=9, single_entry_attempt=True)
        package['spec']['portfolio']['volatility_lookback'] = 37
        expected = compile_strategy(package)
        self.editor.apply_package(package)
        self.assertTrue(self.editor.validate_preview(), self.editor.status.text())
        self.assertEqual(self.editor.compiled, expected)
        self.assertEqual(compile_strategy(self.editor.baseline), expected)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_template_rules_cannot_be_overwritten_by_parameter_widget(self):
        package = package_fixture(); spec = package['spec']; template = templates()[0]
        for key in ('factor','version','parameters'): spec.pop(key, None)
        spec.update(theory=template['template_id'], theory_version=template['version'])
        self.editor.apply_package(package)
        self.assertFalse(self.editor.parameters.isEnabled())
        self.editor.parameters.setPlainText('{"invalid_override":1}')
        self.assertTrue(self.editor.validate_preview(), self.editor.status.text())
        self.assertEqual(self.editor.compiled, compile_strategy(package))

    def test_edit_invalidates_preview_and_only_explicit_accept_returns_draft(self):
        self.editor.apply_package(package_fixture()); self.assertTrue(self.editor.validate_preview())
        before = deepcopy(self.editor.baseline)
        self.editor.portfolio['max_position'].setText('0.2')
        self.assertIsNone(self.editor.compiled); self.assertFalse(self.editor.use_button.isEnabled())
        self.editor.finish(); self.assertIsNone(self.editor.result_package)
        self.assertTrue(self.editor.validate_preview()); self.editor.finish()
        self.assertEqual(self.editor.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.editor.result_package['spec']['portfolio']['max_position'], 0.2)
        self.assertEqual(self.editor.baseline, before)
        self.assertFalse((self.root/'_jobs').exists())

    def test_invalid_import_preserves_draft_and_export_never_overwrites(self):
        self.editor.apply_package(package_fixture()); self.assertTrue(self.editor.validate_preview())
        before = self.editor.compiled; invalid = package_fixture(); invalid['lifecycle']['stop_loss'] = 0.1
        with self.assertRaises(ValueError): self.editor.apply_package(invalid)
        self.assertEqual(self.editor.compiled, before)
        target = self.root/'new.json'; self.editor.save_package(target)
        content = target.read_bytes()
        with self.assertRaises(FileExistsError): self.editor.save_package(target)
        self.assertEqual(target.read_bytes(), content)
        self.editor.identity['version'].setText('draft-2')
        with self.assertRaises(ValueError): self.editor.save_package(self.root/'not-written.json')
        self.assertFalse((self.root/'not-written.json').exists())

    def test_nonfinite_and_invalid_number_fail_without_replacing_preview(self):
        self.editor.apply_package(package_fixture()); self.assertTrue(self.editor.validate_preview())
        for key, bad in [('initial_cash','NaN'),('top_n','1.5'),('exposure','inf')]:
            with self.subTest(key=key):
                self.editor.apply_package(package_fixture()); self.editor.execution[key].setText(bad)
                self.assertFalse(self.editor.validate_preview()); self.assertIsNone(self.editor.compiled)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_parent_handoff_clears_old_approval_and_checks_compiled_hash(self):
        dialog = ProposalDialog(self.host)
        try:
            dialog.apply_strategy_package(package_fixture()); dialog.create(); dialog.confirm.setChecked(True)
            self.assertTrue(dialog.approve_button.isEnabled())
            def edit_and_accept(editor):
                editor.identity['version'].setText('draft-2'); editor.portfolio['max_position'].setText('0.4')
                self.assertTrue(editor.validate_preview(), editor.status.text()); editor.finish(); return editor.result()
            with patch.object(StrategyWorkspaceDialog, 'exec', edit_and_accept): dialog.open_strategy_workspace()
            value = json.loads(dialog.draft.toPlainText())
            self.assertEqual(value['strategy_package']['package']['version'],'draft-2')
            self.assertEqual(value['portfolio']['max_position'],0.4)
            self.assertIsNone(dialog.selected); self.assertFalse(dialog.confirm.isChecked())
            self.assertFalse(dialog.approve_button.isEnabled()); self.assertFalse((self.root/'_jobs').exists())
            before = dialog.draft.toPlainText()
            with self.assertRaises(ValueError): dialog.apply_strategy_package(package_fixture(), expected_compiled_hash='0'*64)
            self.assertEqual(dialog.draft.toPlainText(),before)
        finally: dialog.close(); sip.delete(dialog)

    def test_version_tab_shows_real_diff_and_does_not_mutate_baseline(self):
        self.editor.apply_package(package_fixture()); baseline=deepcopy(self.editor.baseline)
        self.editor.portfolio['max_position'].setText('0.2'); self.editor.compare_versions()
        result=json.loads(self.editor.version_details.toPlainText())
        self.assertTrue(result['same_version']); self.assertTrue(result['warnings'])
        self.assertTrue(any('max_position' in row['path'] for row in result['changes']))
        self.assertEqual(self.editor.baseline,baseline); self.assertEqual(list(self.root.iterdir()),[])

    def test_results_tab_uses_real_archives_and_clears_stale_result_on_error(self):
        import test_core
        from test_strategy_package import package
        from quantlab.workbench.jobs import execute,prepare
        fixture=test_core.CoreTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        a=execute(prepare(compile_strategy(package())['spec']),fixture.root,self.root)
        b=execute(prepare(compile_strategy(package())['spec']),fixture.root,self.root)
        before=sorted(str(p) for p in self.root.rglob('*'))
        self.editor.left_run.setText(a.run_id);self.editor.right_run.setText(b.run_id)
        self.editor.compare_results()
        result=json.loads(self.editor.result_details.toPlainText())
        self.assertTrue(result['comparable'],result);self.assertFalse(self.editor.busy)
        self.assertEqual(before,sorted(str(p) for p in self.root.rglob('*')))
        self.editor.right_run.setText('bad-id');self.assertEqual(self.editor.result_details.toPlainText(),'{}')
        self.editor.compare_results();self.assertEqual(self.editor.result_details.toPlainText(),'{}')
        self.assertIn('失败',self.editor.status.text());self.assertFalse(self.editor.busy)
        self.assertTrue(self.editor.tabs.isEnabled())

if __name__ == '__main__': unittest.main()
