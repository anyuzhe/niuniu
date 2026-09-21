"""Offscreen discovery/selection and stale asynchronous reply checks."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QMessageBox
from quantlab.desktop.strategy_workspace import StrategyWorkspaceDialog
from quantlab.storage.codec import encode
from quantlab.trading.strategy_package import compile_strategy
from quantlab.workbench.jobs import execute,prepare
from test_strategy_package import package
from test_strategy_package_desktop import _Host
import test_core

class StrategyRunPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        if cls.app.platformName()!='offscreen':raise RuntimeError('offscreen required')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.host=_Host(self.root);self.dialog=StrategyWorkspaceDialog(self.host,self.host)
        self.addCleanup(self.close)
    def close(self):
        if not sip.isdeleted(self.dialog):self.dialog.close();sip.delete(self.dialog)
        self.host.close();sip.delete(self.host);QApplication.processEvents()
    def make_run(self):
        fixture=test_core.CoreTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        return execute(prepare(compile_strategy(package())['spec']),fixture.root,self.root)

    def test_no_automatic_scan_and_empty_directory_is_explicit(self):
        self.assertEqual(list(self.root.iterdir()),[]);self.assertEqual(self.dialog.archive_list.count(),0)
        self.assertFalse(self.dialog.archive_left_button.isEnabled())
        self.dialog.load_archives();self.assertIn('0',self.dialog.archive_note.text())
        self.assertFalse(self.dialog.archive_next_button.isEnabled());self.assertFalse(self.dialog.isVisible())
        self.assertEqual(list(self.root.iterdir()),[])

    def test_real_discovery_pick_and_verify_preserve_draft(self):
        run=self.make_run(); self.dialog.identity['name'].setText('unsaved draft')
        before=sorted(str(p) for p in self.root.rglob('*'));self.dialog.load_archives()
        self.assertEqual(self.dialog.archive_list.count(),1);self.dialog.archive_list.setCurrentRow(0)
        self.dialog.choose_archive('left');self.dialog.choose_archive('right')
        self.assertEqual(self.dialog.left_run.text(),run.run_id);self.assertEqual(self.dialog.right_run.text(),run.run_id)
        self.dialog.inspect_archive();value=json.loads(self.dialog.result_details.toPlainText())
        self.assertEqual(value['verification'],'archive_internal_consistency')
        self.assertEqual(self.dialog.identity['name'].text(),'unsaved draft');self.assertIsNone(self.dialog.compiled)
        self.dialog.compare_results();self.assertTrue(json.loads(self.dialog.result_details.toPlainText())['comparable'])
        self.assertEqual(before,sorted(str(p) for p in self.root.rglob('*')))

    def test_failed_records_visible_but_unselectable_and_bad_records_warn(self):
        run=self.make_run();p=run.artifact_path/'experiment.json';record=json.loads(p.read_text());record['status']='failed';p.write_text(encode(record))
        bad=self.root/str(uuid4());bad.mkdir();(bad/'experiment.json').write_text('{bad')
        self.dialog.load_archives();self.assertEqual(self.dialog.archive_list.count(),1)
        self.assertIn('不完整',self.dialog.archive_note.text());self.dialog.archive_list.setCurrentRow(0)
        self.assertIn('unreadable_experiment_json',self.dialog.archive_note.text())
        self.assertFalse(self.dialog.archive_left_button.isEnabled());self.dialog.choose_archive('left')
        self.assertEqual(self.dialog.left_run.text(),'')

    def test_query_change_discards_delayed_reply_and_unlocks_controls(self):
        captured=[]
        self.host.async_call=lambda work,done,guarded=False:captured.append((work,done))
        self.dialog.load_archives();self.assertTrue(self.dialog.busy)
        self.dialog.archive_query.setText('new query')
        work,done=captured.pop();done({'runs':[],'has_more':False,'incomplete':False},'')
        self.assertEqual(self.dialog.archive_list.count(),0);self.assertIsNone(self.dialog._archive_page)
        self.assertFalse(self.dialog.busy);self.assertTrue(self.dialog.tabs.isEnabled())
        self.assertIn('忽略',self.dialog.status.text())

    def test_pagination_uses_returned_scan_offset_not_match_count(self):
        first={'runs':[],'has_more':True,'next_offset':100,'incomplete':False,'errors':[]}
        second={'runs':[],'has_more':False,'next_offset':None,'incomplete':False,'errors':[]}
        with patch('quantlab.trading.strategy_run_catalog.list_strategy_runs',side_effect=[first,second]) as listing:
            self.dialog.load_archives();self.assertTrue(self.dialog.archive_next_button.isEnabled())
            self.dialog.next_archive_page();self.assertEqual(listing.call_args.kwargs['offset'],100)
        self.assertFalse(self.dialog.archive_next_button.isEnabled())

    def test_discovered_archive_changed_before_inspection_fails_closed(self):
        run=self.make_run();self.dialog.load_archives();self.dialog.archive_list.setCurrentRow(0)
        (run.artifact_path/'bars.parquet').write_bytes(b'broken')
        self.dialog.inspect_archive();self.assertEqual(self.dialog.result_details.toPlainText(),'{}')
        self.assertIn('失败',self.dialog.status.text());self.assertFalse(self.dialog.busy)

    def select_revision_source(self):
        run = self.make_run()
        self.dialog.load_archives(); self.dialog.archive_list.setCurrentRow(0)
        self.assertTrue(self.dialog.archive_edit_button.isEnabled())
        return run

    def load_revision(self):
        with patch('quantlab.desktop.strategy_workspace.QMessageBox.question',
                   return_value=QMessageBox.StandardButton.Yes):
            self.dialog.edit_archived_strategy()

    def test_cancel_revision_preserves_unsaved_draft_without_reading_archive(self):
        self.select_revision_source(); self.dialog.apply_package(package())
        self.assertTrue(self.dialog.validate_preview()); before = self.dialog.compiled
        with patch('quantlab.desktop.strategy_workspace.QMessageBox.question',
                   return_value=QMessageBox.StandardButton.No), \
             patch('quantlab.trading.strategy_run_catalog.prepare_strategy_revision') as read:
            self.dialog.edit_archived_strategy()
        read.assert_not_called(); self.assertEqual(self.dialog.compiled, before)
        self.assertIsNone(self.dialog.revision_origin)

    def test_revision_edit_requires_new_version_preserves_source_and_explicit_handoff(self):
        from quantlab.storage.artifact_integrity import snapshot_tree
        run = self.select_revision_source(); before = snapshot_tree(self.root, run.run_id)
        self.load_revision()
        self.assertEqual(self.dialog.revision_origin['source']['run_id'], run.run_id)
        self.assertIsNone(self.dialog.compiled); self.assertFalse(self.dialog.use_button.isEnabled())
        self.assertEqual(self.dialog.tabs.currentIndex(), 0)
        self.assertTrue(self.dialog.validate_preview(), self.dialog.status.text())
        self.dialog.portfolio['max_position'].setText('0.5')
        self.assertFalse(self.dialog.validate_preview()); self.assertIn('新', self.dialog.status.text())
        self.dialog.finish(); self.assertIsNone(self.dialog.result_package)
        with self.assertRaises(ValueError): self.dialog.save_package(self.root / 'rejected.json')
        self.dialog.identity['version'].setText('draft-2')
        self.assertTrue(self.dialog.validate_preview(), self.dialog.status.text())
        self.dialog.save_package(self.root / 'draft-2.json'); self.dialog.finish()
        self.assertEqual(self.dialog.result_package['version'], 'draft-2')
        self.assertEqual(self.dialog.revision_origin['historical_package']['version'], '1.0.0')
        self.assertEqual(before, snapshot_tree(self.root, run.run_id))
        self.assertFalse((self.root / '_jobs').exists()); self.assertFalse((self.root / 'rejected.json').exists())

    def test_current_signal_drift_is_visible_and_needs_explicit_new_version(self):
        from quantlab.app import default_registry
        self.select_revision_source()
        with patch.object(type(default_registry()), 'code_hash', return_value='f' * 64):
            self.load_revision()
            self.assertFalse(self.dialog.revision_origin['current_matches_history'])
            self.assertIn('指纹不同', self.dialog.revision_note.text())
            source = json.loads(self.dialog.origin_details.toPlainText())
            self.assertFalse(source['current_matches_history_on_load'])
            self.assertFalse(self.dialog.validate_preview())
            self.dialog.identity['version'].setText('source-upgrade-1')
            self.assertTrue(self.dialog.validate_preview(), self.dialog.status.text())
        self.assertFalse((self.root / '_jobs').exists())

    def test_bad_revision_source_keeps_existing_draft_and_unlocks(self):
        run = self.select_revision_source(); self.dialog.apply_package(package())
        self.assertTrue(self.dialog.validate_preview()); before = self.dialog.compiled
        (run.artifact_path / 'bars.parquet').write_bytes(b'broken')
        self.load_revision()
        self.assertEqual(self.dialog.compiled, before)
        self.assertIsNone(self.dialog.revision_origin); self.assertFalse(self.dialog.busy)
        self.assertTrue(self.dialog.tabs.isEnabled()); self.assertIn('失败', self.dialog.status.text())

    def test_revision_reply_cannot_replace_draft_after_query_change(self):
        self.select_revision_source(); self.dialog.identity['name'].setText('keep this draft')
        captured = []; self.host.async_call = lambda work,done,guarded=False: captured.append((work,done))
        self.load_revision(); self.assertTrue(self.dialog.busy)
        self.dialog.archive_query.setText('different query')
        work, done = captured.pop(); done(work(), '')
        self.assertEqual(self.dialog.identity['name'].text(), 'keep this draft')
        self.assertIsNone(self.dialog.revision_origin); self.assertFalse(self.dialog.busy)

    def test_closing_workspace_rejects_pending_revision_reply(self):
        self.select_revision_source(); self.dialog.identity['name'].setText('cancelled draft')
        captured = []; self.host.async_call = lambda work,done,guarded=False: captured.append((work,done))
        self.load_revision(); self.assertTrue(self.dialog.busy)
        self.dialog.reject()
        work, done = captured.pop(); done(work(), '')
        self.assertEqual(self.dialog.identity['name'].text(), 'cancelled draft')
        self.assertIsNone(self.dialog.revision_origin)
        self.assertIsNone(self.dialog.result_package)

    def test_revision_checks_current_compilation_again_before_applying(self):
        from copy import deepcopy
        from quantlab.trading.strategy_run_catalog import prepare_strategy_revision
        run = self.select_revision_source()
        value = prepare_strategy_revision(self.root, run.run_id,
            expected_package_hash=compile_strategy(package())['package_hash'])
        self.dialog.apply_package(package()); self.assertTrue(self.dialog.validate_preview())
        before = self.dialog.compiled
        stale = deepcopy(value); stale['compiled']['compiled_spec_hash'] = '0' * 64
        with patch('quantlab.trading.strategy_run_catalog.prepare_strategy_revision', return_value=stale):
            self.load_revision()
        self.assertEqual(self.dialog.compiled, before); self.assertIsNone(self.dialog.revision_origin)
        self.assertIn('未载入', self.dialog.status.text())

    def test_independent_import_clears_revision_origin_but_tree_edit_preserves_it(self):
        self.select_revision_source(); self.load_revision()
        changed = self.dialog.collect_package(); changed['spec']['portfolio']['max_position'] = 0.5
        with self.assertRaisesRegex(ValueError, '版本'):
            self.dialog.apply_package(changed, baseline=False)
        self.assertIsNotNone(self.dialog.revision_origin)
        changed['version'] = 'tree-revision-2'
        self.dialog.apply_package(changed, baseline=False)
        self.assertIsNotNone(self.dialog.revision_origin); self.assertTrue(self.dialog.validate_preview())
        self.dialog.apply_package(package())
        self.assertIsNone(self.dialog.revision_origin)
        self.assertEqual(self.dialog.origin_details.toPlainText(), '{}')
        self.assertTrue(self.dialog.validate_preview())

    def test_revision_returns_to_original_pending_gate_without_inheriting_approval(self):
        from quantlab.desktop.agent_proposals import ProposalDialog
        from unittest.mock import patch
        run = self.select_revision_source(); parent = ProposalDialog(self.host)
        try:
            parent.apply_strategy_package(package()); parent.create(); parent.confirm.setChecked(True)
            old_id = parent.selected['proposal_id']
            self.assertTrue(parent.approve_button.isEnabled())
            def edit_and_accept(editor):
                editor.load_archives(); editor.archive_list.setCurrentRow(0)
                with patch('quantlab.desktop.strategy_workspace.QMessageBox.question',
                           return_value=QMessageBox.StandardButton.Yes): editor.edit_archived_strategy()
                self.assertEqual(editor.revision_origin['source']['run_id'], run.run_id)
                editor.identity['version'].setText('draft-2')
                self.assertTrue(editor.validate_preview(), editor.status.text()); editor.finish()
                return editor.result()
            with patch.object(StrategyWorkspaceDialog, 'exec', edit_and_accept): parent.open_strategy_workspace()
            self.assertIsNone(parent.selected); self.assertFalse(parent.confirm.isChecked())
            self.assertFalse(parent.approve_button.isEnabled()); parent.create()
            self.assertEqual(parent.selected['status'], 'pending')
            self.assertNotEqual(parent.selected['proposal_id'], old_id)
            self.assertFalse(parent.confirm.isChecked()); self.assertFalse((self.root / '_jobs').exists())
        finally: parent.close(); sip.delete(parent)

    def test_saved_revision_reopens_with_source_and_without_automatic_verification(self):
        run = self.select_revision_source(); self.load_revision()
        self.dialog.identity['version'].setText('saved-revision-2')
        self.dialog.portfolio['max_position'].setText('0.5')
        self.assertTrue(self.dialog.validate_preview(), self.dialog.status.text())
        target = self.root / 'saved-revision.json'; self.dialog.save_package(target)
        saved = json.loads(target.read_text()); source = saved['revision_source']
        self.assertEqual(source['parent_run_id'], run.run_id)
        self.dialog.close(); sip.delete(self.dialog)
        self.dialog = StrategyWorkspaceDialog(self.host, self.host)
        with patch('quantlab.trading.strategy_run_catalog.get_strategy_run', side_effect=AssertionError('no implicit source reads')):
            self.dialog.apply_package(saved)
            self.assertTrue(self.dialog.validate_preview(), self.dialog.status.text())
        self.assertIsNone(self.dialog.revision_origin)
        self.assertEqual(self.dialog.compiled['package']['revision_source'], source)
        self.assertIn('尚未核验', self.dialog.revision_note.text())
        self.assertTrue(self.dialog.revision_verify_button.isEnabled())
        self.dialog.verify_revision_source()
        self.assertEqual(json.loads(self.dialog.origin_details.toPlainText())['status'], 'verified')
        self.assertFalse((self.root / '_jobs').exists())

    def test_recheck_broken_parent_clears_prior_verified_display_and_preserves_draft(self):
        run = self.select_revision_source(); self.load_revision()
        self.dialog.verify_revision_source()
        self.assertEqual(json.loads(self.dialog.origin_details.toPlainText())['status'], 'verified')
        before = self.dialog.collect_package()
        (run.artifact_path / 'bars.parquet').write_bytes(b'broken')
        self.dialog.verify_revision_source()
        self.assertEqual(self.dialog.collect_package(), before)
        self.assertNotIn('verified', json.loads(self.dialog.origin_details.toPlainText()).values())
        self.assertIn('失败', self.dialog.status.text()); self.assertFalse(self.dialog.busy)
        self.assertFalse((self.root / '_jobs').exists())

    def test_reopened_revision_cannot_reuse_parent_version_after_parameter_change(self):
        self.select_revision_source(); self.load_revision()
        self.assertTrue(self.dialog.validate_preview())
        target = self.root / 'unchanged-copy.json'; self.dialog.save_package(target)
        self.dialog.apply_package(json.loads(target.read_text()))
        self.assertIsNone(self.dialog.revision_origin)
        self.dialog.portfolio['max_position'].setText('0.5')
        self.assertFalse(self.dialog.validate_preview())
        self.assertIn('版本', self.dialog.status.text())
        self.assertFalse(self.dialog.use_button.isEnabled())
        self.dialog.identity['version'].setText('explicit-new-version')
        self.assertTrue(self.dialog.validate_preview(), self.dialog.status.text())

if __name__=='__main__':unittest.main()
