import os,time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from uuid import uuid4
import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_restricted_dsl as fixtures
from quantlab.desktop.data_workbench import DataConnectedWorkbench
from quantlab.desktop.dsl_candidates import DslCandidateDialog
from quantlab.agent.dsl_candidates import DslCandidateService

class DslCandidateDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait(self,predicate):
        end=time.monotonic()+15
        while time.monotonic()<end:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback timeout')
    def setUp(self):
        self.fx=fixtures.RestrictedDslTests();self.fx.setUp();self.source=self.fx.source()
        self.service=DslCandidateService(self.fx.output);self.request=str(uuid4())
        self.service.propose(self.request,'桌面DSL候选',fixtures.sample_ast(),self.source.run_id)
        self.window=DataConnectedWorkbench(self.fx.output,self.fx.fx.root);self.window.tracking_controller.timer.stop()
        self.wait(lambda:not self.window.callbacks);self.dialog=DslCandidateDialog(self.window);self.window.show_dialog(self.dialog)
        self.wait(lambda:not self.dialog.busy)
    def tearDown(self):
        self.wait(lambda:not self.window.callbacks);self.dialog.close();self.window.close();QApplication.processEvents();self.fx.doCleanups()
    def test_selection_does_not_register(self):
        self.assertEqual(self.service.list()['total'],0);self.assertFalse(self.dialog.register_button.isEnabled())
        self.dialog.pending.setCurrentIndex(0);QApplication.processEvents()
        self.assertEqual(self.service.list()['total'],0);self.assertFalse((self.fx.output/'_jobs').exists())
    def test_explicit_confirmation_registers_without_research(self):
        self.dialog.pending.setCurrentIndex(0);self.dialog.confirm.setChecked(True);self.assertTrue(self.dialog.register_button.isEnabled())
        self.dialog.register_button.click();self.wait(lambda:not self.dialog.busy)
        listing=self.service.list();self.assertEqual(listing['total'],1);self.assertEqual(listing['candidates'][0]['name'],'桌面DSL候选')
        self.assertFalse((self.fx.output/'_jobs').exists())
