import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from PyQt6.QtWidgets import QApplication
from test_phase1_desktop_evidence import _Window
from test_context_experiments import ContextProvider, context_config, runner
from quantlab.desktop.factor_evidence import RunResearchLinksDialog
from quantlab.trading.research_evidence import archive_research_reference

class ResearchLinksDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        r=runner(ContextProvider(),self.root).run(replace(context_config(),context=None,replay=True))
        self.source=archive_research_reference(self.root,r.run_id)['source']
    def test_native_readonly_dialog_uses_same_service_and_marks_unregistered(self):
        window=_Window(self.root);dialog=RunResearchLinksDialog(window,self.source)
        work,done,_=window.calls.pop();result=work();done(result,'')
        self.assertEqual(result['status'],'UNREGISTERED');self.assertIn('UNREGISTERED',dialog.status.text())
        self.assertIsNone(dialog.next_offset);dialog.reject()
    def test_close_or_root_switch_rejects_late_result(self):
        window=_Window(self.root);dialog=RunResearchLinksDialog(window,self.source)
        work,done,_=window.calls.pop();result=work();dialog.reject();done(result,'')
        self.assertNotIn('UNREGISTERED',dialog.status.text())
        window2=_Window(self.root);dialog2=RunResearchLinksDialog(window2,self.source)
        work,done,_=window2.calls.pop();result=work();window2.output=self.root/'elsewhere';done(result,'')
        self.assertNotIn('UNREGISTERED',dialog2.status.text());dialog2.reject()
