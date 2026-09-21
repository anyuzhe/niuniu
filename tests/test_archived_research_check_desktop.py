"""F11 offscreen UI and real host handoff tests; no visible or production client."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_archived_dataset_lifecycle as fixtures
from quantlab.desktop.data_workbench import DataConnectedWorkbench
from quantlab.desktop.agent_proposals import ProposalDialog
from quantlab.desktop.archived_daily_dataset import ArchivedDailyDatasetDialog
from quantlab.storage.codec import encode


class ArchivedResearchCheckDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def wait(self, condition):
        end=time.monotonic()+15
        while time.monotonic()<end:
            QApplication.processEvents()
            if condition():return
            QTest.qWait(5)
        self.fail('Qt callbacks did not settle')

    def setUp(self):
        self.fx=fixtures.ArchivedDatasetLifecycleTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.exported=self.fx.export()
        self.window=DataConnectedWorkbench(self.fx.output,self.fx.destination)
        self.window.tracking_controller.timer.stop();self.addCleanup(self.cleanup)
        self.wait(lambda:not self.window.callbacks)
        self.dialog=ProposalDialog(self.window);self.window.dialogs.append(self.dialog)
        self.wait(lambda:not self.window.callbacks)
        self.dialog.draft.setPlainText(encode(self.fx.spec))

    def cleanup(self):
        self.wait(lambda:not self.window.callbacks)
        for d in list(self.window.dialogs):d.close()
        self.window.close();QApplication.processEvents()

    def test_match_is_readonly_and_draft_edit_invalidates_report(self):
        before=fixtures.files(self.fx.root);d=self.dialog;text=d.draft.toPlainText()
        d.check_inputs();self.wait(lambda:not d.busy and not self.window.callbacks)
        self.assertTrue(d.input_check['compatible'],d.input_status.text())
        self.assertEqual(d.draft.toPlainText(),text);self.assertIsNone(self.window.queue)
        self.assertFalse(d.confirm.isChecked());self.assertEqual(before,fixtures.files(self.fx.root))
        d.draft.setPlainText(encode({**self.fx.spec,'question':'new question'}))
        self.assertIsNone(d.input_check);self.assertIn('失效',d.input_status.text())

    def test_mismatch_reports_blockers_without_arming_old_proposal(self):
        d=self.dialog;d.create();self.wait(lambda:not d.busy and not self.window.callbacks)
        d.confirm.setChecked(True)
        d.draft.setPlainText(encode({**self.fx.spec,'adjustment':'qfq'}));text=d.draft.toPlainText()
        d.check_inputs();self.wait(lambda:not d.busy and not self.window.callbacks)
        self.assertFalse(d.input_check['compatible']);self.assertIn('qfq',d.input_status.text())
        self.assertEqual(d.draft.toPlainText(),text);self.assertIsNone(d.selected)
        self.assertFalse(d.approve_button.isEnabled());self.assertIsNone(self.window.queue)

    def delayed(self):
        pending=[]
        with patch.object(self.window,'async_call',side_effect=lambda work,done,guarded=False:pending.append((work,done))):
            self.dialog.check_inputs()
        return pending[0]

    def test_close_while_checking_drops_late_result_without_deletion(self):
        work,done=self.delayed();self.dialog.close();done(work(),'')
        self.assertIsNone(self.dialog.input_check);self.assertFalse(self.dialog.busy)
        self.assertFalse(self.dialog.confirm.isChecked())

    def test_context_and_draft_changes_invalidate_late_results(self):
        work,done=self.delayed();value=work()
        self.dialog.draft.setPlainText(encode({**self.fx.spec,'question':'changed'}));done(value,'')
        self.assertIsNone(self.dialog.input_check)
        work,done=self.delayed();value=work();old=self.window.data_root
        self.window.data_root=self.fx.source;done(value,'');self.window.data_root=old
        self.assertIsNone(self.dialog.input_check);self.assertIn('失效',self.dialog.input_status.text())

    def test_bad_package_and_dispatch_failures_restore_controls(self):
        d=self.dialog
        with patch.object(self.window,'async_call',side_effect=RuntimeError('dispatcher unavailable')):
            d.check_inputs()
        self.assertFalse(d.busy);self.assertIsNone(d.input_check);self.assertTrue(d.input_check_button.isEnabled())
        (self.fx.destination/'normalized/bars.parquet').write_bytes(b'bad')
        d.check_inputs();self.wait(lambda:not d.busy and not self.window.callbacks)
        self.assertIsNone(d.input_check);self.assertIn('失败',d.input_status.text())
        self.assertIsNone(self.window.queue)

    def test_selecting_saved_proposal_clears_unrelated_draft_check(self):
        d=self.dialog;d.draft.setPlainText(encode({**self.fx.spec,'question':'saved B','adjustment':'qfq'}))
        d.create();self.wait(lambda:not d.busy and not self.window.callbacks)
        d.draft.setPlainText(encode(self.fx.spec));d.check_inputs()
        self.wait(lambda:not d.busy and not self.window.callbacks)
        self.assertTrue(d.input_check['compatible'])
        d.listing.setCurrentRow(0)
        self.assertIsNotNone(d.selected)
        self.assertIsNone(d.input_check)
        self.assertNotIn('当前行情输入匹配',d.input_status.text())
        self.assertFalse(d.confirm.isChecked());self.assertIsNone(self.window.queue)

    def test_stale_open_panel_does_not_check_a_different_host_root(self):
        old=self.window.data_root;self.window.data_root=self.fx.source
        try:
            with patch('quantlab.data.archived_research_check.check_archived_daily_research',side_effect=AssertionError('read')) as check:
                self.dialog.check_inputs();check.assert_not_called()
            self.assertIn('已过期',self.dialog.input_status.text());self.assertIsNone(self.dialog.input_check)
        finally:self.window.data_root=old

    def test_input_panel_opens_empty_original_proposal_after_real_selection(self):
        self.dialog.close()
        self.window.data_root=self.fx.source
        panel=ArchivedDailyDatasetDialog(self.window);self.window.dialogs.append(panel)
        self.assertFalse(panel.proposals_button.isEnabled())
        panel.package_path.setText(str(self.fx.destination));panel.inspect_package()
        self.wait(lambda:not panel.busy and not self.window.callbacks)
        self.assertFalse(panel.proposals_button.isEnabled())
        panel.use_package();self.wait(lambda:not panel.busy and not self.window.callbacks)
        self.assertEqual(self.window.data_root,self.fx.destination)
        self.assertTrue(panel.proposals_button.isEnabled(),panel.status.text())
        panel.open_proposals();self.wait(lambda:not self.window.callbacks)
        opened=self.window.dialogs[-1];self.assertIsInstance(opened,ProposalDialog)
        self.assertEqual(opened.draft.toPlainText(),'');self.assertFalse(opened.confirm.isChecked())
        self.assertIsNone(self.window.queue);self.assertFalse((self.fx.output/'_jobs').exists())
        opened.draft.setPlainText(encode(self.fx.spec));opened.check_inputs()
        self.wait(lambda:not opened.busy and not self.window.callbacks)
        self.assertTrue(opened.input_check['compatible'])
        opened.create();self.wait(lambda:not opened.busy and not self.window.callbacks)
        self.assertEqual(opened.selected['status'],'pending');self.assertIsNone(self.window.queue)
        opened.confirm.setChecked(True);opened.approve()
        self.wait(lambda:not opened.busy and not self.window.callbacks)
        self.wait(lambda:all(j['status'] not in ('queued','running') for j in self.window.queue.list()))
        self.assertEqual(self.window.queue.list()[0]['status'],'completed')

    def test_handoff_never_switches_back_to_previously_selected_root(self):
        panel=ArchivedDailyDatasetDialog(self.window);self.window.dialogs.append(panel)
        panel._selected_input={'dataset_id':self.exported['dataset_id'],'path':str(self.fx.destination)}
        old=self.window.data_root;self.window.data_root=self.fx.source
        count=len(self.window.dialogs);panel.open_proposals()
        self.assertEqual(len(self.window.dialogs),count);self.assertEqual(self.window.data_root,self.fx.source)
        self.assertIn('不匹配',panel.status.text());self.window.data_root=old


if __name__=='__main__':unittest.main()
