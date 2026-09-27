import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,time,unittest
from copy import deepcopy
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_watchlist as fixtures
from quantlab.desktop.app import MainWindow
from quantlab.desktop.factor_watches import FactorWatchDialog
from quantlab.desktop.research_picker import ArchivePickerDialog
from quantlab.desktop.watch_snapshot_view import maturity_rows,sequential_rows,sequential_status_label
from quantlab.trading.research_evidence import archive_research_reference


class WatchWorkflowReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=fixtures.WatchlistTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.window=MainWindow(self.fx.output);self.window.data_root=self.fx.root
        self.dialog=FactorWatchDialog(self.window);self.window.show_dialog(self.dialog)
        self.wait(lambda:not self.dialog.busy)
    def wait(self,predicate):
        end=time.monotonic()+12
        while time.monotonic()<end:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def tearDown(self):
        for dialog in self.window.dialogs:dialog.close()
        self.wait(lambda:not self.window.callbacks)
        if self.window.queue:self.window.queue.close()
        self.window.close();QApplication.processEvents()
    def select(self):
        d=self.dialog;d.select_source(archive_research_reference(self.fx.output,self.fx.source.run_id))
        d.windows.setText('5');d.minimum.setValue(1)
        return d
    def create(self):
        d=self.select();d.create_watch()
        self.wait(lambda:not d.busy and d.snapshot_result is not None)
        return d
    def test_real_nonmodal_picker_returns_only_explicit_verified_source(self):
        d=self.dialog;d.pick_button.click();picker=self.window.dialogs[-1]
        self.assertIsInstance(picker,ArchivePickerDialog);self.assertEqual(d.source.count(),0)
        self.assertEqual(picker.rows,[])
        picker.query.setText(self.fx.source.run_id);picker.search_button.click()
        self.wait(lambda:len(picker.rows)==1)
        picker.results.selectRow(0);picker.use_button.click()
        self.wait(lambda:d.source.currentData()==self.fx.source.run_id)
        self.assertIsNone(self.window.queue);self.assertEqual(self.fx.service.store.list()['watches'],[])
        self.assertEqual(d._selected_reference()['source']['run_id'],self.fx.source.run_id)
    def test_changed_selected_header_never_creates_watch_or_silently_reselects(self):
        d=self.select();path=self.fx.source.artifact_path/'experiment.json';raw=path.read_bytes()
        path.write_bytes(raw+b' ')
        d.create_watch();self.wait(lambda:not d.busy)
        self.assertEqual(self.fx.service.store.list()['watches'],[])
        self.assertIn('变化',d.status.text());self.assertIsNone(self.window.queue)
    def test_historical_source_changes_disable_open_without_using_latest(self):
        d=self.create();sid=d.snapshot_result['snapshot_id']
        later=self.fx.later();self.fx.service.observe(d.watches.currentData(),later.run_id)
        d.reload();self.wait(lambda:not d.busy and d.snapshot_result is not None)
        (self.fx.source.artifact_path/'observations.parquet').write_bytes(b'old source changed')
        d.history.setCurrentIndex(d.history.findData(sid))
        self.wait(lambda:not d.busy and d.snapshot_result is not None and d.snapshot_result['snapshot_id']==sid)
        self.assertEqual(d.snapshot_result['source_integrity'],'source_changed');self.assertFalse(d.open_button.isEnabled())
        self.assertFalse(d.snapshot_result['is_latest']);self.assertIn('来源已变化',d.snapshot_heading.text())
        with patch.object(self.window,'open_run') as opened:d.open_source();opened.assert_not_called()
    def test_stale_manual_pause_is_rejected_without_overriding_external_change(self):
        d=self.create();wid=d.watches.currentData()
        self.fx.service.store.set_active(wid,False)
        d.toggle_pause();self.wait(lambda:not d.busy)
        self.assertFalse(self.fx.service.get(wid)['active']);self.assertIn('state changed',d.status.text())
        self.assertIsNone(d.selected);self.assertIsNone(d.snapshot_result)
    def test_replaced_workspace_before_queued_operation_never_writes_old_root(self):
        d=self.select();pending=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,cb,**kw:pending.append((fn,cb))):d.create_watch()
        old=self.window.output;self.window.output=self.fx.root/'new-workspace'
        try:
            with self.assertRaisesRegex(ValueError,'身份'):pending[0][0]()
            pending[0][1](None,'context changed')
            self.assertEqual(self.fx.service.store.list()['watches'],[]);self.assertIsNone(d.snapshot_result)
        finally:self.window.output=old
    def test_closing_before_delayed_snapshot_callback_discards_result(self):
        d=self.create();view=deepcopy(d.snapshot_result);pending=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,cb,**kw:pending.append((fn,cb))):d.select_history()
        d.close();pending[0][1](view,None)
        self.assertIsNone(d.snapshot_result);self.assertEqual(d.maturity_table.rowCount(),0)
    def test_display_projection_preserves_negative_zero_and_unknown_without_classifying(self):
        snapshot={'preview':{'windows':{'5':{'horizons':{'1':{'status':'insufficient_mature_dates',
            'mature_observations':0,'pending_observations':3,'valid_ic_sessions':0,'metrics':{'rank_ic':-.4}}}}}},
            'baseline_differences':{'5':{'1':{'rank_ic_difference':None}}},
            'sequential_monitor':{'status':'INSUFFICIENT','horizons':{'1':{'status':'INSUFFICIENT_NEW_DATES',
                'new_mature_sessions':0,'complete_blocks':0,'pending_block_sessions':0,'current_e_value':1.0,
                'max_e_value':1.0,'evidence_threshold':20.0}}}}
        original=deepcopy(snapshot);row=maturity_rows(snapshot)[0]
        self.assertEqual(row[1:4],[0,3,0]);self.assertEqual(row[5],-.4);self.assertIsNone(row[6])
        self.assertEqual(sequential_rows(snapshot)[0][2],0);self.assertEqual(snapshot,original)
        self.assertIn('未配置',sequential_status_label('LEGACY_NOT_CONFIGURED'))
        self.assertIn('阻断',sequential_status_label('HISTORICAL_REVISION_BLOCKED'))


if __name__=='__main__':unittest.main()
