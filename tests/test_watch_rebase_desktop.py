import time
import unittest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_watch_rebase as fixtures
from quantlab.desktop.data_workbench import DataConnectedWorkbench
from quantlab.desktop.watch_rebase import WatchRebaseDialog


class WatchRebaseDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait(self,condition):
        until=time.monotonic()+20
        while time.monotonic()<until:
            QApplication.processEvents()
            if condition():return
            QTest.qWait(10)
        self.fail('Qt callback timeout')
    def setUp(self):
        self.f=fixtures.WatchRebaseTests();self.f.setUp()
        self.window=DataConnectedWorkbench(self.f.f.output,self.f.f.root)
        for timer in self.window.findChildren(QTimer):timer.stop()
        self.wait(lambda:not self.window.callbacks)
        self.dialog=WatchRebaseDialog(self.window);self.window.show_dialog(self.dialog)
        self.wait(lambda:not self.dialog.busy)
        self.dialog.old.setCurrentIndex(self.dialog.old.findData(self.f.watch))
        self.dialog.candidate.setCurrentIndex(self.dialog.candidate.findData(self.f.new.run_id))
    def tearDown(self):
        self.wait(lambda:not self.window.callbacks)
        for dialog in self.window.dialogs:dialog.close()
        self.window.close();QApplication.processEvents();self.f.doCleanups()
    def test_preview_confirmation_and_creation_are_separate(self):
        d=self.dialog;self.assertFalse(d.accept_button.isEnabled())
        d.accept_plan();self.assertFalse((self.f.f.output/'_watch_rebases').exists())
        d.preview();self.wait(lambda:not d.busy)
        self.assertIsNotNone(d.plan,d.status.text());plan=d.plan
        self.assertFalse(d.accept_button.isEnabled());d.confirm.setChecked(True)
        d.accept_plan();self.wait(lambda:not d.busy)
        self.assertFalse(self.f.f.service.store.read(plan['new_watch_id'])[1]['active'])
        self.assertFalse(list(self.f.f.output.glob('_jobs/*.json')))
        d.show_history();self.wait(lambda:not d.busy)
        self.assertIn(plan['new_watch_id'],d.details.toPlainText())
    def test_changed_name_clears_confirmation_and_plan(self):
        d=self.dialog;d.preview();self.wait(lambda:not d.busy);d.confirm.setChecked(True)
        d.name.setText('changed')
        self.assertIsNone(d.plan);self.assertFalse(d.confirm.isChecked())
        self.assertFalse(d.accept_button.isEnabled())
    def test_late_preview_cannot_reapprove_changed_selection(self):
        pending=[];original=self.window.async_call
        self.window.async_call=lambda fn,done,guarded=False:pending.append((fn,done))
        try:
            self.dialog.preview();fn,done=pending.pop();value=fn()
            self.dialog.name.setText('changed during read');done(value,None)
            self.assertIsNone(self.dialog.plan);self.assertFalse(self.dialog.accept_button.isEnabled())
        finally:self.window.async_call=original
