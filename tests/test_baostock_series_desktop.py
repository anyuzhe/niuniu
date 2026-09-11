import time
import unittest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_baostock_series as fixtures
from quantlab.desktop.data_workbench import DataConnectedWorkbench
from quantlab.desktop.baostock_series import BaostockSeriesDialog


class SeriesDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait(self,condition):
        until=time.monotonic()+15
        while time.monotonic()<until:
            QApplication.processEvents()
            if condition():return
            QTest.qWait(10)
        self.fail('Qt callback timeout')
    def setUp(self):
        self.fixture=fixtures.BaostockSeriesTests();self.fixture.setUp()
        self.sid,_=self.fixture.series();self.new=self.fixture.batch('2025-01-10')
        self.window=DataConnectedWorkbench(self.fixture.root,None)
        for timer in self.window.findChildren(QTimer):timer.stop()
        self.wait(lambda:not self.window.callbacks)
        self.dialog=BaostockSeriesDialog(self.window);self.window.show_dialog(self.dialog)
        self.wait(lambda:not self.dialog.busy)
        self.dialog.channels.setCurrentIndex(self.dialog.channels.findData(self.sid))
        self.dialog.batches.setCurrentIndex(self.dialog.batches.findData(self.new))
    def tearDown(self):
        self.wait(lambda:not self.window.callbacks)
        self.dialog.close();self.window.close();QApplication.processEvents();self.fixture.doCleanups()
    def test_preview_confirmation_publish_and_stable_source_selection(self):
        self.dialog.preview();self.wait(lambda:not self.dialog.busy)
        self.assertIsNotNone(self.dialog.plan,self.dialog.status.text())
        self.dialog.accept_plan();self.assertEqual(self.fixture.service.get(self.sid)['generation'],1)
        self.dialog.confirm.setChecked(True);self.dialog.accept_plan();self.wait(lambda:not self.dialog.busy)
        self.assertEqual(self.fixture.service.get(self.sid)['generation'],2)
        self.dialog.select();self.assertEqual(self.window.data_root,self.fixture.service.folder(self.sid))
        self.assertFalse((self.fixture.root/'_jobs').exists())
    def test_change_clears_plan_and_does_not_create_a_channel(self):
        self.dialog.preview();self.wait(lambda:not self.dialog.busy)
        self.dialog.confirm.setChecked(True);self.dialog.name.setText('changed')
        self.assertIsNone(self.dialog.plan);self.assertFalse(self.dialog.confirm.isChecked())
        self.dialog.create();self.assertEqual(len(self.fixture.service.list()['series']),1)
    def test_late_preview_does_not_apply_to_a_different_selection(self):
        pending=[];original=self.window.async_call
        self.window.async_call=lambda fn,done,guarded=False:pending.append((fn,done))
        try:
            self.dialog.preview();fn,done=pending.pop();value=fn()
            self.dialog.batches.setCurrentIndex(-1);done(value,None)
            self.assertIsNone(self.dialog.plan)
        finally:self.window.async_call=original
