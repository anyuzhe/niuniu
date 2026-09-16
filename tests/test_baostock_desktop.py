import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QDate
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
import test_baostock_data as fixture
from quantlab.desktop.data_workbench import DataConnectedWorkbench,DataResearchChatDialog
from quantlab.desktop.baostock_data import BaostockDataDialog
from quantlab.desktop.refresh_readiness import RefreshReadinessDialog
from quantlab.desktop.reference_tools import ReferenceDialog


class BaostockDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait(self,condition):
        end=time.monotonic()+10
        while time.monotonic()<end:
            QApplication.processEvents()
            if condition():return
            QTest.qWait(10)
        self.fail('Qt callbacks did not settle')
    def setUp(self):
        self.fixture=fixture.BaostockDataTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.fixture.imported()
        self.window=DataConnectedWorkbench(self.fixture.root,self.fixture.root)
        self.addCleanup(self.cleanup_window);self.wait(lambda:not self.window.callbacks)
    def cleanup_window(self):
        for d in self.window.dialogs:d.close()
        self.wait(lambda:not self.window.callbacks)
        self.window.close();QApplication.processEvents()
    def dialog(self):
        dialog=BaostockDataDialog(self.window);self.window.show_dialog(dialog)
        self.wait(lambda:not dialog.busy and not self.window.callbacks)
        return dialog
    def test_import_inspection_selection_and_data_tools(self):
        dialog=self.dialog();self.assertEqual(dialog.imports.count(),1)
        self.assertIn('profit',[dialog.tables.itemText(i) for i in range(dialog.tables.count())])
        dialog.tables.setCurrentText('profit');dialog.read_page()
        self.wait(lambda:not dialog.busy);self.assertIn('2024-12-31',dialog.details.toPlainText())
        dialog.inspect();self.wait(lambda:not dialog.busy)
        self.assertIn('verified_dataset_files',dialog.details.toPlainText())
        dialog.use_dataset()
        self.assertEqual(self.window.data_root,self.fixture.directory/'dataset')
        self.window.research_chat();chat=self.window._research_chat_dialog
        self.assertIsInstance(chat,DataResearchChatDialog)
        names=[t['name'] for t in chat.runtime.api.schemas()]
        self.assertIn('read_baostock_table',names)
        self.assertIn('list_research_skills',names)
        self.assertIn('preview_peer_review',names)
        self.assertIn('get_research_session_grant',names)
        self.assertEqual(len(names),len(set(names)))
        self.assertFalse(chat.consent.isChecked())
        self.assertFalse(list(self.fixture.root.glob('_jobs/*.json')))
    def test_no_implicit_download_and_consent_invalidates(self):
        dialog=self.dialog()
        with patch('quantlab.desktop.baostock_data.run_import') as download:
            dialog.fetch();download.assert_not_called()
        dialog.consent.setChecked(True);dialog.symbols.setText('sh.600000')
        self.assertFalse(dialog.consent.isChecked())
        dialog.consent.setChecked(True);dialog.end.setDate(QDate(2025,1,10))
        self.assertFalse(dialog.consent.isChecked())
        dialog.consent.setChecked(True);dialog.datasets['financials'].setChecked(True)
        self.assertFalse(dialog.consent.isChecked())
    def test_switch_refuses_corrupt_data_or_active_callbacks(self):
        self.window.async_call(lambda:1,lambda *_:None,guarded=False)
        with self.assertRaises(ValueError):self.window.select_baostock_dataset(self.fixture.identifier)
        self.wait(lambda:not self.window.callbacks)
        original=self.window.data_root
        source=self.fixture.directory/'dataset/research/profit.parquet';source.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.window.select_baostock_dataset(self.fixture.identifier)
        self.assertEqual(self.window.data_root,original)
    def test_strict_pit_coverage_is_read_only_and_visible(self):
        before={p.relative_to(self.fixture.root) for p in self.fixture.root.rglob('*')}
        dialog=ReferenceDialog(self.window);self.window.show_dialog(dialog)
        dialog.inspect_strict_pit();self.wait(lambda:not self.window.callbacks)
        self.assertIn('NO_STRICT_EVIDENCE',dialog.status.text())
        self.assertEqual(dialog.results.rowCount(),4)
        self.assertEqual({p.relative_to(self.fixture.root) for p in self.fixture.root.rglob('*')},before)

    def test_missing_watch_does_not_schedule(self):
        dialog=RefreshReadinessDialog(self.window);self.window.show_dialog(dialog)
        self.wait(lambda:not self.window.callbacks)
        self.assertEqual(dialog.watches.count(),0);self.assertEqual(dialog.calendars.count(),1)
        dialog.check();self.assertIn('缺少',dialog.status.text())
        self.assertFalse(list(self.fixture.root.glob('_jobs/*.json')))
