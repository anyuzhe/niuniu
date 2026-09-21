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
from PyQt6.QtWidgets import QApplication
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

if __name__=='__main__':unittest.main()
