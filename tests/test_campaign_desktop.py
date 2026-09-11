import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import time
import unittest
from PyQt6.QtWidgets import QApplication,QPushButton
from PyQt6.QtTest import QTest
from quantlab.desktop.app import MainWindow
from quantlab.desktop.research_campaign import CampaignDialog
from quantlab.desktop.agent_proposals import ProposalDialog
from test_campaigns import pack
import test_core


class CampaignDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait(self,predicate):
        until=time.monotonic()+10
        while time.monotonic()<until:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt work did not settle')
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp()
        self.output=self.fixture.root/'runs';self.output.mkdir()
        self.window=MainWindow(self.output,self.fixture.root)
    def tearDown(self):
        self.wait(lambda:not self.window.callbacks)
        for dialog in self.window.dialogs:dialog.close()
        self.window.close();QApplication.processEvents();self.fixture.tearDown()
    def test_builder_previews_saves_without_execution_and_selects_exact_proposal(self):
        self.window.research_campaign();dialog=self.window.dialogs[-1]
        self.assertIsInstance(dialog,CampaignDialog)
        dialog.raw.setPlainText(json.dumps(pack(self.fixture.symbols)));dialog.import_json()
        self.assertEqual(len(dialog.nodes),2)
        dialog.preview();self.wait(lambda:not dialog.busy)
        self.assertIn('4个固定族检验',dialog.status.text())
        dialog.save();self.wait(lambda:not self.window.callbacks)
        approvals=[d for d in self.window.dialogs if isinstance(d,ProposalDialog)]
        self.assertEqual(len(approvals),1);selected=approvals[0].selected
        self.assertEqual(selected['plan']['spec'],dialog.collect())
        self.assertFalse(approvals[0].confirm.isChecked());self.assertFalse(approvals[0].approve_button.isEnabled())
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
    def test_catalog_entry_and_dag_errors_are_visible(self):
        self.window.agent_catalog();catalog=self.window.dialogs[-1]
        self.assertTrue(any(b.text()=='编排固定研究包' for b in catalog.findChildren(QPushButton)))
        self.window.research_campaign();dialog=self.window.dialogs[-1]
        plan=pack(self.fixture.symbols);plan['nodes'][0]['depends_on']=['second']
        dialog.raw.setPlainText(json.dumps(plan));dialog.import_json()
        self.assertEqual(dialog.nodes,[]);self.assertIn('循环',dialog.status.text())
