import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from uuid import uuid4
import time
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

import test_alpha_factory as factory_fixtures
from quantlab.desktop.data_workbench import DataConnectedWorkbench
from quantlab.desktop.alpha_factory import AlphaFactoryDialog
from quantlab.desktop.research_agenda import ResearchAgendaDialog


class AlphaFactoryDesktopTests(unittest.TestCase):
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
        # Keep the actual data-connected host, but do not read the production
        # DATA catalog merely to test its Factory/Agenda dialogs.
        isolation=patch('quantlab.desktop.market_pages.build_market_overview',
                        side_effect=ValueError('Isolated Factory test: no market overview configured'))
        isolation.start();self.addCleanup(isolation.stop)
        self.fx=factory_fixtures.AlphaFactoryTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.proposal=self.fx.service.propose(str(uuid4()),self.fx.plan())
        self.window=DataConnectedWorkbench(self.fx.output,self.fx.fx.root);self.window.tracking_controller.timer.stop()
        self.wait(lambda:not self.window.callbacks)
    def tearDown(self):
        self.wait(lambda:not self.window.callbacks)
        for dialog in self.window.dialogs:dialog.close()
        if self.window.queue:self.window.queue.close()
        self.window.close();QApplication.processEvents()
    def test_selection_never_submits_without_confirmation(self):
        dialog=AlphaFactoryDialog(self.window,self.proposal['proposal_id']);self.window.show_dialog(dialog)
        self.wait(lambda:not dialog.busy);self.assertFalse(dialog.confirm.isChecked())
        with patch.object(dialog.service,'submit',side_effect=AssertionError('must not submit')) as submit:
            dialog.submit();submit.assert_not_called()
        self.assertFalse((self.fx.output/'_jobs').exists())
    def test_explicit_confirmation_calls_host_submit(self):
        dialog=AlphaFactoryDialog(self.window,self.proposal['proposal_id']);self.window.show_dialog(dialog)
        self.wait(lambda:not dialog.busy);dialog.confirm.setChecked(True)
        expected=dialog.current
        with patch.object(dialog.service,'submit',return_value={**expected,'status':'submitted'}) as submit:
            dialog.submit();self.wait(lambda:not dialog.busy)
        submit.assert_called_once();self.assertTrue(submit.call_args.kwargs['confirmed'])
    def test_agenda_open_is_read_only(self):
        before=list(self.fx.output.glob('_jobs/*.json'))
        dialog=ResearchAgendaDialog(self.window);self.window.show_dialog(dialog);self.wait(lambda:not dialog.busy)
        self.assertEqual(before,list(self.fx.output.glob('_jobs/*.json')))
        self.assertIn('当前',dialog.status.text())
