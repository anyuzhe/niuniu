import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from quantlab.desktop.app import MainWindow
from test_research_chat import FakeProvider


class RecoveryDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.window=MainWindow(self.root);self.window.research_chat()
        self.dialog=self.window._research_chat_dialog
    def wait(self,predicate):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('callback did not settle')
    def tearDown(self):
        for dialog in self.window.dialogs:dialog.close()
        self.wait(lambda:not self.window.callbacks)
        self.window.close();QApplication.processEvents();self.tmp.cleanup()
    def seed(self):
        d=self.dialog;tid=d.runtime.store.begin(d.session_id,'研究测试',{})
        d.runtime.store.finish(tid,'partial','已停止调用工具，研究尚未收尾。',{'needs_followup':True})
        d.select_session()
    def test_partial_visible_recovery_prefill_not_auto_send_then_filtered_send(self):
        self.seed();d=self.dialog
        self.assertIn('未完成',d.transcript.toPlainText());self.assertIn('未完成',d.status.text())
        provider=FakeProvider(text='已核对原记录，没有重跑。')
        with patch('quantlab.agent.chat_runtime.make_provider',return_value=provider):
            d.recovery_button.click()
            self.assertFalse(provider.called);self.assertTrue(d.recovery_mode.isChecked())
            self.assertEqual(d.runtime.tool_profile,'research');self.assertIn('不要重跑',d.input.toPlainText())
            d.send();self.assertFalse(provider.called)
            d.consent.setChecked(True);d.send();self.wait(lambda:not d.busy)
        self.assertTrue(provider.called)
        self.assertNotIn('submit_granted_experiment',provider.tools)
        self.assertNotIn('record_hypothesis',provider.tools)
        self.assertIn('record_finding',provider.tools)
        self.assertFalse((self.root/'_jobs').exists())
        self.assertTrue(d.runtime.store.turns(d.session_id)[-1]['metadata']['recovery_only'])
    def test_stale_workspace_cannot_send_or_prefill_recovery(self):
        self.seed();d=self.dialog;d.input.setPlainText('保留原输入');d.consent.setChecked(True)
        original=self.window.output;self.window.output=self.root/'other'
        try:
            provider=FakeProvider()
            with patch('quantlab.agent.chat_runtime.make_provider',return_value=provider):
                d.prepare_recovery();d.send()
            self.assertFalse(provider.called);self.assertEqual(d.input.toPlainText(),'保留原输入')
            self.assertIn('工作空间已变化',d.status.text())
        finally:self.window.output=original


if __name__=='__main__':unittest.main()
