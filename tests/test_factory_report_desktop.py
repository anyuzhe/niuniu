import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import time
import hashlib
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_alpha_factory as factory_fixtures
from quantlab.workbench.jobs import JobQueue
from quantlab.desktop.app import MainWindow
from quantlab.desktop.alpha_factory import AlphaFactoryDialog
from quantlab.desktop.factory_report import FactoryReportDialog,export_factory_report
from quantlab.agent.factory_report import build_factory_report
from quantlab.agent.evidence_review import EVIDENCE_TOOLS


class FactoryReportDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=factory_fixtures.AlphaFactoryTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        proposal=self.fx.service.propose(str(uuid4()),self.fx.v2_plan())
        queue=JobQueue(self.fx.output,self.fx.fx.root)
        try:self.fx.service.submit(proposal['proposal_id'],proposal['prepared_digest'],lambda:queue,confirmed=True)
        finally:queue.close()
        self.state=self.fx.service.sync(proposal['proposal_id']);self.pid=self.state['proposal_id']
        self.window=MainWindow(self.fx.output);self.addCleanup(self.close_window)
    def wait(self,predicate):
        end=time.monotonic()+15
        while time.monotonic()<end:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('callback did not settle')
    def close_window(self):
        for dialog in self.window.dialogs:dialog.close()
        self.wait(lambda:not self.window.callbacks)
        self.window.close();QApplication.processEvents()
    def open_report(self):
        dialog=FactoryReportDialog(self.window,self.pid);self.window.show_dialog(dialog)
        self.wait(lambda:not dialog.busy);self.assertIsNotNone(dialog.report,dialog.status.text())
        return dialog
    def sources(self):
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.fx.output.rglob('*')
                if p.is_file() and p.suffix in ('.json','.parquet') and '_assistant' not in p.parts}
    def test_real_report_and_export_are_same_digest_and_do_not_recompute(self):
        before=self.sources();dialog=self.open_report();report=dialog.report
        self.assertIn(self.state['result_run_id'],dialog.text.toPlainText())
        target=self.fx.output/'export.md';meta=export_factory_report(self.fx.output,self.pid,report['report_digest'],target)
        self.assertEqual(meta['report_digest'],report['report_digest']);self.assertFalse(meta['reproduction_bundle'])
        self.assertEqual(target.read_text(),dialog.text.toPlainText())
        original=target.read_bytes()
        with self.assertRaises(FileExistsError):export_factory_report(self.fx.output,self.pid,report['report_digest'],target)
        self.assertEqual(target.read_bytes(),original);self.assertEqual(before,self.sources())
        json_target=self.fx.output/'export.json'
        export_factory_report(self.fx.output,self.pid,report['report_digest'],json_target,format='json')
        self.assertEqual(json.loads(json_target.read_text())['report_digest'],report['report_digest'])
    def test_factory_button_opens_report_and_ai_handoff_never_calls_model(self):
        factory=AlphaFactoryDialog(self.window,self.pid);self.window.show_dialog(factory)
        self.wait(lambda:not factory.busy and factory.current is not None)
        factory.report_button.click();dialog=self.window.dialogs[-1]
        self.assertIsInstance(dialog,FactoryReportDialog);self.wait(lambda:not dialog.busy)
        before=self.sources()
        with patch('quantlab.agent.chat_runtime.make_provider') as model:
            dialog.ask_ai();self.wait(lambda:not dialog.busy);model.assert_not_called()
        chat=self.window._research_chat_dialog
        self.assertEqual(chat.runtime.tool_profile,'evidence');self.assertFalse(chat.consent.isChecked())
        self.assertIn(dialog.report['report_digest'],chat.input.toPlainText())
        self.assertIn(self.pid,chat.input.toPlainText())
        self.assertTrue({t['name'] for t in chat.runtime.api.schemas()} <= EVIDENCE_TOOLS)
        for c in (chat.approvals_button,chat.grant_button,chat.recovery_button,chat.recovery_mode):self.assertFalse(c.isEnabled())
        self.assertEqual(before,self.sources())
    def test_existing_busy_chat_is_not_replaced_by_report_handoff(self):
        self.window.research_chat();old=self.window._research_chat_dialog
        old.input.setPlainText('原工作');old.set_busy(True)
        try:
            dialog=self.open_report();dialog.ask_ai();self.wait(lambda:not dialog.busy)
            self.assertIs(self.window._research_chat_dialog,old);self.assertEqual(old.input.toPlainText(),'原工作')
            self.assertNotEqual(old.runtime.tool_profile,'evidence')
        finally:old.set_busy(False)
    def test_state_change_blocks_old_report_export_and_ai_handoff(self):
        dialog=self.open_report();old=dialog.report['report_digest']
        current=self.fx.service.get(self.pid);current['last_sync_at']='changed';self.fx.service.store.save(current)
        target=self.fx.output/'should-not-exist.md'
        with self.assertRaises(ValueError):export_factory_report(self.fx.output,self.pid,old,target)
        self.assertFalse(target.exists())
        with patch.object(self.window,'review_research_evidence') as open_chat:
            dialog.ask_ai();self.wait(lambda:not dialog.busy);open_chat.assert_not_called()
        self.assertIsNone(dialog.report);self.assertFalse(dialog.ai_button.isEnabled())
    def test_workspace_change_or_close_blocks_late_report_and_export(self):
        dialog=self.open_report();old=self.window.output;self.window.output=old/'other'
        try:
            with patch.object(self.window,'review_research_evidence') as open_chat:
                dialog.ask_ai();open_chat.assert_not_called()
        finally:self.window.output=old
        other=FactoryReportDialog(self.window,self.pid);self.window.show_dialog(other);other.close()
        self.wait(lambda:not self.window.callbacks);self.assertIsNone(other.report)
    def test_plain_workbench_can_open_evidence_mode_without_old_writes(self):
        self.assertTrue(self.window.review_research_evidence('请查原有证据'))
        chat=self.window._research_chat_dialog
        self.assertEqual(chat.runtime.tool_profile,'evidence')
        chat.profile.setCurrentIndex(chat.profile.findData('research'))
        self.assertTrue(chat.approvals_button.isEnabled());self.assertTrue(chat.grant_button.isEnabled())
        self.assertFalse(chat.consent.isChecked())
    def test_data_workbench_report_handoff_uses_same_restricted_profile(self):
        from quantlab.desktop.data_workbench import DataConnectedWorkbench
        with patch('quantlab.desktop.market_pages.build_market_overview',side_effect=ValueError('Isolated report test')):
            window=DataConnectedWorkbench(self.fx.output,self.fx.fx.root);window.tracking_controller.timer.stop()
            try:
                self.wait(lambda:not window.callbacks)
                self.assertTrue(window.review_research_evidence('核对已存在的研究证据'))
                chat=window._research_chat_dialog
                self.assertEqual(chat.runtime.tool_profile,'evidence')
                self.assertTrue({t['name'] for t in chat.runtime.api.schemas()} <= EVIDENCE_TOOLS)
                self.assertIsNone(chat.runtime.live_quotes);self.assertFalse(chat.grant_button.isEnabled())
                self.assertIsNone(window.queue)
            finally:
                for dialog in window.dialogs:dialog.close()
                self.wait(lambda:not window.callbacks);window.close();QApplication.processEvents()
    def test_promoted_watch_navigation_only_opens_existing_exact_watch(self):
        factory=AlphaFactoryDialog(self.window,self.pid);self.window.show_dialog(factory)
        self.wait(lambda:not factory.busy and factory.current is not None)
        wid=str(uuid4());candidate=self.state['prepared']['candidates'][0]['candidate_id']
        current={**self.state,'promotions':[{'watch_id':wid,'candidate_id':candidate}]}
        with patch.object(factory.service,'get',return_value=current):
            factory.select();self.wait(lambda:not factory.busy)
            with patch.object(self.window,'factor_watches') as opened:
                factory.watch_button.click();self.wait(lambda:not factory.busy);opened.assert_called_once_with(wid)
        self.assertEqual(self.fx.service.get(self.pid)['promotions'],[])

if __name__=='__main__':unittest.main()
