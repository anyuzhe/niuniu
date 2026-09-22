"""F14 real result-view wiring with isolated archives and deferred Qt callbacks."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import json
import shutil
import unittest
from unittest.mock import patch
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QTextBrowser, QLineEdit, QTableWidget
from quantlab.desktop.app import MainWindow
from quantlab.workbench.server import ArtifactCatalog
from quantlab.workbench.jobs import execute, prepare
from quantlab.trading.strategy_package import compile_strategy
from test_strategy_package import package
import test_core


class Host(QMainWindow):
    open_run=MainWindow.open_run
    record_widget=MainWindow.record_widget
    observations_widget=MainWindow.observations_widget
    replay_widget=MainWindow.replay_widget
    def __init__(self, root):
        super().__init__();self.output=root;self.catalog=ArtifactCatalog(root)
        self.status=QLabel();self.factors=[];self.pending=[];self.dialogs=[]
        self.closing=False;self.broken=False
    def async_call(self, work, callback, guarded=True):
        if self.broken:raise RuntimeError('synthetic dispatch failure')
        self.pending.append((work,callback))
    def show_dialog(self, dialog):self.dialogs.append(dialog)  # Never show even offscreen.
    def deliver(self):
        work, callback=self.pending.pop(0)
        try:value=work()
        except Exception as error:callback(None,str(error))
        else:callback(value,'')
    def drain(self):
        for _ in range(100):
            if not self.pending:return
            self.deliver()
        raise AssertionError('unbounded callbacks')
    def switch(self, root):self.output=root;self.catalog=ArtifactCatalog(root)


class ResultViewLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        if cls.app.platformName()!='offscreen':raise RuntimeError('offscreen required')
    def setUp(self):
        self.fx=test_core.CoreTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.root=(self.fx.root/'results').resolve();self.root.mkdir()
        self.run=execute(prepare(compile_strategy(package())['spec']),self.fx.root,self.root)
        (self.run.artifact_path/'report.md').write_text('ORIGINAL_REPORT_A',encoding='utf-8')
        self.host=Host(self.root);self.addCleanup(self.clean)
    def clean(self):
        self.host.drain()
        for d in self.host.dialogs:
            if not sip.isdeleted(d):d.close();sip.delete(d)
        self.host.close();sip.delete(self.host);QApplication.processEvents()
    def opened(self):
        self.host.open_run(self.run.run_id);self.host.drain()
        self.assertTrue(self.host.dialogs,self.host.status.text());return self.host.dialogs[-1]
    def buttons(self,dialog):return {b.text():b for b in dialog.findChildren(QPushButton)}
    def other(self):
        target=self.root.with_name('different-workspace');shutil.copytree(self.root,target)
        (target/self.run.run_id/'report.md').write_text('OTHER_REPORT_B')
        return target
    def test_initial_read_does_not_follow_replaced_host_catalog(self):
        self.host.open_run(self.run.run_id);self.host.switch(self.other());self.host.drain()
        self.assertEqual(self.host.dialogs,[])
    def test_initial_reply_is_not_applied_after_workspace_switch(self):
        self.host.open_run(self.run.run_id);work,callback=self.host.pending.pop(0);value=work()
        self.host.switch(self.other());callback(value,'');self.host.drain()
        self.assertEqual(self.host.dialogs,[])
    def test_closed_view_drops_report_reply(self):
        self.host.open_run(self.run.run_id);self.host.deliver();dialog=self.host.dialogs[-1]
        reports=dialog.findChildren(QTextBrowser);self.assertTrue(reports)
        dialog.reject();self.host.drain()
        self.assertFalse(any('ORIGINAL_REPORT_A' in w.toPlainText() for w in reports))
    def test_export_after_workspace_switch_never_uses_the_new_root(self):
        d=self.opened();self.host.switch(self.other());target=self.fx.root/'wrong.zip'
        with patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(target),'')),patch('quantlab.storage.bundle.export_bundle') as export:
            self.buttons(d)['导出实验复现包'].click();self.host.drain()
        export.assert_not_called();self.assertFalse(target.exists())
    def test_reproduce_after_workspace_switch_never_runs(self):
        d=self.opened();self.host.switch(self.other())
        with patch('quantlab.storage.bundle.reproduce_artifact') as reproduce:
            self.buttons(d)['使用归档 K 线复算并核对'].click();self.host.drain()
        reproduce.assert_not_called()
    def test_export_after_same_path_directory_replacement_is_rejected(self):
        d=self.opened();old=self.root.with_name('old-results');self.root.rename(old);shutil.copytree(old,self.root)
        with patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(self.fx.root/'replaced.zip'),'')),patch('quantlab.storage.bundle.export_bundle') as export:
            self.buttons(d)['导出实验复现包'].click();self.host.drain()
        export.assert_not_called()
    def test_switch_inside_save_dialog_is_rechecked_before_writing(self):
        d=self.opened();other=self.other()
        def choose(*args,**kwargs):self.host.switch(other);return str(self.fx.root/'late.zip'),''
        with patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName',side_effect=choose),patch('quantlab.storage.bundle.export_bundle') as export:
            self.buttons(d)['导出实验复现包'].click();self.host.drain()
        export.assert_not_called()
    def test_export_and_reproduce_cannot_overlap_in_one_view(self):
        d=self.opened();buttons=self.buttons(d)
        with patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(self.fx.root/'one.zip'),'')):
            buttons['导出实验复现包'].click()
        self.assertFalse(buttons['使用归档 K 线复算并核对'].isEnabled())
        self.host.drain();self.assertTrue((self.fx.root/'one.zip').is_file())
    def test_unknown_reproduction_status_cannot_be_shown_as_verified(self):
        d=self.opened()
        with patch('quantlab.storage.bundle.reproduce_artifact',return_value={'status':'not_verified','run_id':self.run.run_id,'source_run_id':self.run.run_id}):
            self.buttons(d)['使用归档 K 线复算并核对'].click();self.host.drain()
        self.assertFalse(any('归档复算逐项核对一致' in w.text() for w in d.findChildren(QLabel)))
        self.assertTrue(any('失败' in w.text() or '未核对' in w.text() for w in d.findChildren(QLabel)))
    def test_dispatch_failure_is_reported_not_raised(self):
        self.host.broken=True
        self.host.open_run(self.run.run_id)
        self.assertIn('失败',self.host.status.text());self.assertEqual(self.host.dialogs,[])
    def test_real_report_export_and_frozen_reproduction_keep_original_bytes(self):
        from quantlab.storage.artifact_integrity import snapshot_tree
        from quantlab.storage.bundle import restore_bundle
        d=self.opened();before=snapshot_tree(self.root,self.run.run_id)
        self.assertTrue(any('ORIGINAL_REPORT_A' in w.toPlainText() for w in d.findChildren(QTextBrowser)))
        target=self.fx.root/'bundle.zip'
        with patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(target),'')):
            self.buttons(d)['导出实验复现包'].click();self.host.drain()
        self.assertTrue(target.is_file());restored=restore_bundle(target,self.fx.root/'restored')
        self.assertEqual((Path(restored['artifact_root'])/self.run.run_id/'experiment.json').read_bytes(),(self.run.artifact_path/'experiment.json').read_bytes())
        with patch('quantlab.data.provider.local_data_provider',side_effect=AssertionError('no live data')):
            self.buttons(d)['使用归档 K 线复算并核对'].click();self.host.drain()
        receipts=list(self.root.glob('*/reproduction.json'));self.assertEqual(len(receipts),1)
        self.assertEqual(json.loads(receipts[0].read_text())['status'],'numerically_matched')
        self.assertEqual(snapshot_tree(self.root,self.run.run_id),before)


    def test_close_during_export_waits_for_actual_completion(self):
        d=self.opened();target=self.fx.root/'closing.zip'
        with patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(target),'')):
            d.export()
        d.reject();self.assertFalse(d._closed);self.assertTrue(d._close_requested)
        self.host.drain();self.assertTrue(target.is_file());self.assertTrue(d._closed)
        self.assertTrue(d.last_operation['ok']);self.assertFalse(d._writing)
    def test_queued_export_rechecks_context_before_io(self):
        d=self.opened();target=self.fx.root/'queued.zip'
        with patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(target),'')):
            d.export()
        self.host.switch(self.other())
        with patch('quantlab.storage.bundle.export_bundle') as export:self.host.drain()
        export.assert_not_called();self.assertFalse(target.exists());self.assertFalse(d.last_operation['ok'])
    def test_write_dispatch_error_restores_buttons_without_fake_success(self):
        d=self.opened();self.host.broken=True;d.reproduce()
        self.assertFalse(d._writing);self.assertFalse(d.last_operation['ok'])
        self.assertTrue(d.reproduce_button.isEnabled());self.assertIn('dispatch',d.status.text())
    def test_reproduction_source_mismatch_reports_failure_without_altering_original(self):
        path=self.run.artifact_path/'experiment.json';record=json.loads(path.read_text())
        record['manifest']['runtime']['code_hash']='wrong-runtime';path.write_text(json.dumps(record));before=path.read_bytes()
        d=self.opened();d.reproduce();self.host.drain()
        self.assertFalse(d.last_operation['ok']);self.assertIn('fingerprint',d.status.text())
        self.assertEqual(path.read_bytes(),before)
    def test_replay_uses_pinned_catalog_and_closed_view_discards_read(self):
        from quantlab.desktop.replay import ReplayWidget
        d=self.opened();self.buttons(d)['载入 K 线回放'].click();self.host.drain()
        replay=d.findChild(ReplayWidget);self.assertIsNotNone(replay);self.assertIs(replay.window,d)
        self.assertIsNotNone(replay.bars);before=list(replay.chart.candles)
        replay.cursor.setValue(2);d.reject();self.host.drain()
        self.assertEqual(replay.chart.candles,before);self.assertFalse(replay.timer.isActive())
    def test_child_result_opens_and_stale_parent_cannot_open_another(self):
        d=self.opened();record=json.loads((self.run.artifact_path/'experiment.json').read_text());child=record['children'][0]['run_id']
        d.open_run(child);self.host.drain();self.assertEqual(len(self.host.dialogs),2)
        self.assertEqual(self.host.dialogs[-1].binding.run_id,child)
        self.host.switch(self.other());d.open_run(child);self.host.drain()
        self.assertEqual(len(self.host.dialogs),2)
    def test_observation_filter_failure_clears_old_rows_and_can_retry(self):
        d=self.opened();index=next(i for i in range(d.tabs.count()) if d.tabs.tabText(i)=='观测数据');page=d.tabs.widget(index)
        self.assertTrue(any(t.rowCount() for t in page.findChildren(QTableWidget)))
        page.findChild(QLineEdit).setText('sh.600000')
        self.buttons(page)['检索'].click();self.host.drain();QApplication.processEvents()
        self.assertFalse(any(t.rowCount() for t in page.findChildren(QTableWidget)))
        self.assertTrue(any('symbol' in w.text() for w in page.findChildren(QLabel)))
        page.findChild(QLineEdit).setText('');self.buttons(page)['检索'].click();self.host.drain();QApplication.processEvents()
        self.assertTrue(any(t.rowCount() for t in page.findChildren(QTableWidget)))
    def test_observation_pending_reply_does_not_overwrite_changed_filter(self):
        d=self.opened();index=next(i for i in range(d.tabs.count()) if d.tabs.tabText(i)=='观测数据');page=d.tabs.widget(index)
        self.buttons(page)['检索'].click();page.findChild(QLineEdit).setText('changed-before-return')
        self.host.drain();QApplication.processEvents()
        self.assertFalse(any(t.rowCount() for t in page.findChildren(QTableWidget)))


    def test_companion_report_change_during_read_invalidates_view(self):
        self.host.open_run(self.run.run_id);self.host.deliver();d=self.host.dialogs[-1]
        (self.run.artifact_path/'report.md').write_text('changed after view binding')
        self.host.drain()
        self.assertFalse(d.export_button.isEnabled());self.assertIn('失效',d.status.text())
        self.assertFalse(any('changed after view binding' in v.toPlainText() for v in d.findChildren(QTextBrowser)))
    def test_signal_child_bars_change_before_lazy_replay_is_rejected(self):
        d=self.opened();record=json.loads((self.run.artifact_path/'experiment.json').read_text())
        child=self.root/record['children'][0]['run_id'];(child/'bars.parquet').write_bytes(b'changed')
        self.buttons(d)['载入 K 线回放'].click();self.host.drain()
        self.assertFalse(d.export_button.isEnabled());self.assertIn('失效',d.status.text())


if __name__=='__main__':unittest.main()
