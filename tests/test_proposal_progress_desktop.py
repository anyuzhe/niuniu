"""F12 offscreen tracking UI; synthetic journals only, no visible desktop."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json
import unittest
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QMainWindow
from PyQt6.QtTest import QTest
import test_proposal_progress as fixture
from quantlab.desktop.proposal_progress import ProposalProgressDialog
from quantlab.desktop.agent_proposals import ProposalDialog


class Host(QMainWindow):
    def __init__(self,fx):
        super().__init__();self.output=fx.output;self.data_root=fx.fx.root
        self.pending=[];self.deferred=False;self.broken=False;self.opened=None;self.dialogs=[]
    def async_call(self,work,callback,guarded=False):
        if self.broken:raise RuntimeError('synthetic dispatch failure')
        if self.deferred:self.pending.append((work,callback));return
        try:value=work()
        except Exception as error:callback(None,str(error))
        else:callback(value,'')
    def finish(self):
        work,callback=self.pending.pop(0)
        try:value=work()
        except Exception as error:callback(None,str(error))
        else:callback(value,'')
    def open_run(self,run_id):self.opened=run_id
    def show_dialog(self,dialog):self.dialogs.append(dialog)
    def get_research_queue(self):raise AssertionError('monitor must never construct a queue')


class ProposalProgressDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=fixture.ProposalProgressTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.host=Host(self.fx);self.addCleanup(self.host.close)
        self.dialog=ProposalProgressDialog(self.host,self.fx.proposal['proposal_id']);self.addCleanup(self.dialog.close)
    def test_initial_read_is_not_auto_polling_or_execution(self):
        self.assertEqual(self.dialog.report['phase'],'awaiting_approval')
        self.assertFalse(self.dialog.timer.isActive());self.assertFalse(self.dialog.auto.isChecked())
        self.assertFalse(self.dialog.open_button.isEnabled());self.assertIsNone(self.fx.queue)
    def test_auto_refresh_is_explicit_bounded_and_does_not_change_task(self):
        d=self.dialog;d.MAX_AUTO_READS=2;d.auto.setChecked(True)
        self.assertTrue(d.timer.isActive());d._tick();d._tick()
        self.assertFalse(d.timer.isActive());self.assertFalse(d.auto.isChecked())
        self.assertFalse((self.fx.output/'_jobs').exists())
    def test_busy_poll_does_not_queue_overlapping_reads(self):
        d=self.dialog;self.host.deferred=True;d.auto.setChecked(True);d._tick()
        self.assertEqual(len(self.host.pending),1);left=d._auto_reads_left
        d._tick();d.refresh();self.assertEqual(len(self.host.pending),1);self.assertEqual(d._auto_reads_left,left)
        self.host.finish();self.assertFalse(d.busy)
    def test_close_drops_pending_read_and_stops_timer(self):
        d=self.dialog;self.host.deferred=True;d.auto.setChecked(True);d.refresh();d.close()
        self.host.finish();self.assertIsNone(d.report);self.assertFalse(d.busy);self.assertFalse(d.timer.isActive())
    def test_context_change_drops_old_success(self):
        d=self.dialog;self.host.deferred=True;d.refresh();self.host.output=self.fx.fx.root
        self.host.finish();self.assertIsNone(d.report);self.assertFalse(d.open_button.isEnabled())
        self.assertIn('工作空间',d.status.text())
    def test_same_path_replaced_workspace_invalidates_pending_read(self):
        import shutil
        d=self.dialog;self.host.deferred=True;d.refresh()
        original=self.fx.output;backup=original.with_name('saved-workspace')
        original.rename(backup);shutil.copytree(backup,original)
        self.host.finish()
        self.assertIsNone(d.report);self.assertFalse(d.open_button.isEnabled())
        self.assertIn('工作空间',d.status.text())

    def test_dispatch_error_restores_controls_and_clears_old_result(self):
        d=self.dialog;self.host.broken=True;d.auto.setChecked(True);d.refresh()
        self.assertFalse(d.busy);self.assertTrue(d.refresh_button.isEnabled());self.assertIsNone(d.report)
        self.assertFalse(d.timer.isActive());self.assertIn('dispatch',d.status.text())
    def test_completion_stops_poll_and_opens_same_real_result(self):
        d=self.dialog;d.auto.setChecked(True);job=self.fx.completed();d.refresh()
        self.assertTrue(d.open_button.isEnabled(),d.status.text());self.assertFalse(d.timer.isActive())
        d.open_result();self.assertEqual(self.host.opened,job['run_id']);self.assertEqual(len(self.fx.queue.list()),1)
    def test_corruption_after_display_prevents_opening_stale_result(self):
        job=self.fx.completed();d=self.dialog;d.refresh();self.assertTrue(d.open_button.isEnabled())
        path=self.fx.output/job['run_id']/'experiment.json';path.write_text('{}')
        d.open_result();self.assertIsNone(self.host.opened);self.assertFalse(d.open_button.isEnabled())
        self.assertTrue(d.report['incomplete'])
    def test_failure_shows_actual_error_without_recovery(self):
        job=self.fx.completed();self.fx.write_job({**job,'status':'failed','run_id':None,'error':'synthetic original failure'})
        before=fixture.hashes(self.fx.output);d=self.dialog;d.refresh()
        self.assertIn('失败',d.status.text());self.assertIn('synthetic original failure',d.stage.text())
        self.assertFalse(d.open_button.isEnabled());self.assertEqual(before,fixture.hashes(self.fx.output))
    def test_stale_proposal_window_does_not_open_monitor_in_new_workspace(self):
        proposal=ProposalDialog(self.host);self.addCleanup(proposal.close)
        proposal.render([self.fx.proposal],self.fx.proposal['proposal_id'])
        self.host.output=self.fx.fx.root.resolve()
        proposal.open_progress()
        self.assertEqual(self.host.dialogs,[])

    def test_expected_proposal_digest_is_checked_before_display(self):
        monitor=ProposalProgressDialog(self.host,self.fx.proposal['proposal_id'],expected_digest='0'*64)
        self.addCleanup(monitor.close)
        self.assertIsNone(monitor.report);self.assertFalse(monitor.open_button.isEnabled())
        self.assertIn('身份',monitor.status.text())

    def test_original_proposal_button_preserves_draft_but_disarms_approval(self):
        proposal=ProposalDialog(self.host);self.addCleanup(proposal.close)
        proposal.render([self.fx.proposal],self.fx.proposal['proposal_id'])
        proposal.draft.setPlainText(json.dumps(self.fx.spec));proposal.confirm.setChecked(True)
        before=proposal.draft.toPlainText();proposal.open_progress()
        self.assertFalse(proposal.confirm.isChecked());self.assertEqual(before,proposal.draft.toPlainText())
        self.assertEqual(len(self.host.dialogs),1)
        monitor=self.host.dialogs[0];self.addCleanup(monitor.close)
        self.assertEqual(monitor.proposal_id,self.fx.proposal['proposal_id']);self.assertIsNone(self.fx.queue)


if __name__=='__main__':unittest.main()
