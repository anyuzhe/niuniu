import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from pathlib import Path

import test_core
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication
from quantlab.desktop.app import MainWindow
from quantlab.desktop.research_session_grant import ResearchSessionGrantDialog
from quantlab.agent.research_session_grant import grant_status


class ResearchSessionGrantDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.output=self.fixture.root/'desktop-session';self.output.mkdir();self.window=MainWindow(self.output,self.fixture.root)
        self.dialog=ResearchSessionGrantDialog(self.window);self.addCleanup(self.dialog.close);self.addCleanup(self.window.close)
        self.dialog.symbols.setText(','.join(self.fixture.symbols));self.dialog.start.setDate(QDate.fromString('2025-01-01','yyyy-MM-dd'))
        self.dialog.end.setDate(QDate.fromString('2025-01-10','yyyy-MM-dd'))
    def test_open_is_read_only_preview_then_explicit_confirm_authorizes_and_revokes(self):
        self.assertFalse((self.output/'_research_session_grants').exists())
        self.dialog.preview();self.assertIsNotNone(self.dialog.plan);self.assertFalse(self.dialog.confirm.isChecked())
        self.assertFalse((self.output/'_research_session_grants').exists())
        self.dialog.authorize();self.assertEqual(grant_status(self.output,self.fixture.root)['status'],'not_configured')
        self.dialog.confirm.setChecked(True);self.dialog.authorize();status=grant_status(self.output,self.fixture.root)
        self.assertTrue(status['enabled']);self.assertEqual(status['used']['jobs'],0)
        self.dialog.confirm.setChecked(False);self.dialog.revoke();self.assertTrue(grant_status(self.output,self.fixture.root)['enabled'])
        self.dialog.confirm.setChecked(True);self.dialog.revoke();self.assertFalse(grant_status(self.output,self.fixture.root)['enabled'])


if __name__=='__main__':unittest.main()
