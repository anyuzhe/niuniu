import time
import unittest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_candidate_review as fixtures
from quantlab.desktop.data_workbench import DataConnectedWorkbench
from quantlab.desktop.candidate_review import CandidateReviewDialog


class CandidateReviewDesktopTests(unittest.TestCase):
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
        self.fixture=fixtures.CandidateReviewTests();self.fixture.setUp()
        self.window=DataConnectedWorkbench(self.fixture.output,self.fixture.root)
        for timer in self.window.findChildren(QTimer):timer.stop()
        self.wait(lambda:not self.window.callbacks)
        self.dialog=CandidateReviewDialog(self.window);self.window.show_dialog(self.dialog)
        self.wait(lambda:not self.dialog.busy)
        self.dialog.candidate.setCurrentIndex(self.dialog.candidate.findData(self.fixture.a.run_id))
        self.dialog.baseline.setCurrentIndex(self.dialog.baseline.findData(self.fixture.b.run_id))
    def tearDown(self):
        self.wait(lambda:not self.window.callbacks)
        self.dialog.close();self.window.close();QApplication.processEvents()
        self.fixture.doCleanups()
    def test_read_only_compare_and_real_source_links(self):
        self.dialog.compare();self.wait(lambda:not self.dialog.busy)
        self.assertIsNotNone(self.dialog.last_result,self.dialog.status.text())
        self.assertEqual(self.dialog.last_result['candidate']['run_id'],self.fixture.a.run_id)
        self.assertEqual(self.dialog.last_result['new_research_jobs'],0)
        self.assertFalse((self.fixture.output/'_jobs').exists())
    def test_changes_clear_old_result_and_invalid_horizon_is_not_accepted(self):
        self.dialog.compare();self.wait(lambda:not self.dialog.busy)
        self.dialog.horizon.setValue(999);self.assertIsNone(self.dialog.last_result)
        self.dialog.compare();self.wait(lambda:not self.dialog.busy)
        self.assertIsNone(self.dialog.last_result)
        self.assertIn('持有期',self.dialog.status.text())
    def test_late_callback_cannot_overwrite_new_selection(self):
        pending=[];original=self.window.async_call
        self.window.async_call=lambda fn,done,guarded=False:pending.append((fn,done))
        try:
            self.dialog.compare();fn,done=pending.pop();value=fn()
            self.dialog.baseline.setCurrentIndex(self.dialog.baseline.findData(self.fixture.a.run_id))
            done(value,None)
            self.assertIsNone(self.dialog.last_result)
        finally:self.window.async_call=original
