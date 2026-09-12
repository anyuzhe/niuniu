import time
from uuid import uuid4
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_candidate_review as fixtures
from quantlab.agent.incremental_evidence import IncrementalEvidenceService
from quantlab.desktop.data_workbench import DataConnectedWorkbench
from quantlab.desktop.incremental_evidence import IncrementalEvidenceDialog


class IncrementalEvidenceDesktopTests(unittest.TestCase):
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
        self.fx=fixtures.CandidateReviewTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.service=IncrementalEvidenceService(self.fx.output)
        plan={'candidate_run_id':self.fx.a.run_id,'control_run_ids':[self.fx.b.run_id],
            'train_end':'2025-01-06','horizon':1,'alpha':.05,'return_pair':None}
        self.proposal=self.service.propose(str(uuid4()),plan)
        self.window=DataConnectedWorkbench(self.fx.output,self.fx.root)
        for timer in self.window.findChildren(QTimer):timer.stop()
        self.wait(lambda:not self.window.callbacks)
        self.dialog=IncrementalEvidenceDialog(self.window,self.proposal['proposal_id'])
        self.window.show_dialog(self.dialog);self.wait(lambda:not self.dialog.busy)
    def tearDown(self):
        self.wait(lambda:not self.window.callbacks)
        self.dialog.close();self.window.close();QApplication.processEvents()
    def test_selection_never_executes_without_confirmation(self):
        self.assertFalse(self.dialog.confirm.isChecked());self.assertFalse(self.dialog.run_button.isEnabled())
        with patch.object(self.service,'execute',side_effect=AssertionError('different service instance')):
            self.dialog.select();self.wait(lambda:not self.dialog.busy)
        self.assertEqual(self.service.get(self.proposal['proposal_id'])['status'],'pending')
    def test_explicit_confirmation_runs_fixed_plan(self):
        self.dialog.confirm.setChecked(True);self.assertTrue(self.dialog.run_button.isEnabled())
        self.dialog.execute();self.wait(lambda:not self.dialog.busy)
        state=self.service.get(self.proposal['proposal_id'])
        self.assertEqual(state['status'],'completed');self.assertIsNotNone(state['result_run_id'])
        self.assertFalse(self.dialog.confirm.isChecked());self.assertFalse(self.dialog.run_button.isEnabled())
        self.assertTrue(self.dialog.open_button.isEnabled())
