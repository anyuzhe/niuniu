import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from datetime import datetime,timedelta,timezone
import unittest,time
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import QDate
from quantlab.desktop.data_workbench import DataConnectedWorkbench
from quantlab.desktop.tracking_control import TrackingControlDialog
from quantlab.agent.tracking_control_store import ControlStore
import test_tracking_scheduler as fixtures


class TrackingControlDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait(self,predicate):
        limit=time.monotonic()+15
        while time.monotonic()<limit:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def setUp(self):
        self.fixture=fixtures.TrackingSchedulerTests();self.fixture.setUp()
        self.window=DataConnectedWorkbench(self.fixture.output,self.fixture.data)
        self.window.tracking_controller.timer.stop()
        self.wait(lambda:not self.window.callbacks)
    def tearDown(self):
        self.wait(lambda:not self.window.callbacks)
        for dialog in self.window.dialogs:dialog.close()
        self.window.close();QApplication.processEvents();self.fixture.doCleanups()
    def dialog(self):
        dialog=TrackingControlDialog(self.window,self.fixture.watch)
        self.window.show_dialog(dialog);self.wait(lambda:not dialog.busy)
        return dialog
    def test_no_implicit_authorization_and_changed_fields_clear_confirmation(self):
        dialog=self.dialog();self.assertFalse(dialog.confirm.isChecked())
        self.assertFalse(dialog.enable_button.isEnabled())
        with patch('quantlab.desktop.tracking_control.authorize_control') as authorize:
            dialog.enable();authorize.assert_not_called()
        plan=self.fixture.plan()
        with patch('quantlab.desktop.tracking_control.preview_control',return_value=plan):
            dialog.preview();self.wait(lambda:not dialog.busy)
        dialog.confirm.setChecked(True);self.assertTrue(dialog.enable_button.isEnabled())
        dialog.jobs.setValue(2)
        self.assertFalse(dialog.confirm.isChecked());self.assertIsNone(dialog.plan)
        self.assertIsNone(ControlStore(self.fixture.output).get(self.fixture.watch))
    def test_controller_no_grant_never_creates_queue(self):
        with patch.object(self.window,'get_research_queue',side_effect=AssertionError('no authorization')) as queue:
            self.window.tracking_controller.check()
            self.wait(lambda:not self.window.tracking_controller.busy)
        queue.assert_not_called()
        self.assertFalse(ControlStore(self.fixture.output).root.exists())
