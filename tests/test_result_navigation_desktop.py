"""Cross-entry result navigation on isolated journals and offscreen widgets."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication
from quantlab.desktop.agent_proposals import ProposalDialog
from quantlab.desktop.strategy_workspace import StrategyWorkspaceDialog
from quantlab.desktop.proposal_progress import ProposalProgressDialog
from quantlab.storage.codec import encode
import test_proposal_progress as progress_fixture
from test_proposal_progress import hashes
from test_proposal_progress_desktop import Host


class ResultNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if cls.app.platformName() != 'offscreen': raise RuntimeError('offscreen required')

    def setUp(self):
        self.fx = progress_fixture.ProposalProgressTests(); self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.host = Host(self.fx)
        self.dialogs = []
        self.addCleanup(self.close_widgets)
        self.dialog = ProposalDialog(self.host); self.dialogs.append(self.dialog)
        self.select()

    def close_widgets(self):
        for d in self.dialogs:
            if not sip.isdeleted(d): d.close(); sip.delete(d)
        self.host.close(); sip.delete(self.host); QApplication.processEvents()

    def select(self):
        record = self.fx.service.store.get(self.fx.proposal['proposal_id'])
        self.dialog.render([record], record['proposal_id'])

    def ready(self):
        job = self.fx.completed(); self.select(); self.dialog.job_status()
        self.assertEqual(self.dialog.run_id, job['run_id'], self.dialog.status.text())
        return job

    def test_legacy_reads_same_bound_result_without_writing_or_starting_queue(self):
        job = self.fx.completed(); self.select(); before = hashes(self.fx.output)
        self.dialog.job_status(); self.dialog.open_result()
        self.assertEqual(self.host.opened, job['run_id'])
        self.assertEqual(hashes(self.fx.output), before)
        self.assertEqual(len(self.fx.queue.list()), 1)
        self.assertIsNone(self.dialog.selected)

    def test_legacy_rejects_job_whose_spec_does_not_match_selected_proposal(self):
        job = self.fx.completed()
        self.fx.write_job({**job, 'spec': {**job['spec'], 'question': 'different proposal'}})
        self.select(); self.dialog.job_status()
        self.assertIsNone(self.dialog.run_id)
        self.assertFalse(self.dialog.open_button.isEnabled())
        self.assertIn('不一致', self.dialog.status.text())

    def test_legacy_rechecks_missing_result_at_click(self):
        job = self.ready()
        (self.fx.output/job['run_id']/'experiment.json').unlink()
        self.dialog.open_result()
        self.assertIsNone(self.host.opened)
        self.assertIsNone(self.dialog.run_id)
        self.assertFalse(self.dialog.open_button.isEnabled())

    def test_legacy_changed_workspace_cannot_open_old_result(self):
        self.ready(); other = self.fx.fx.root/'other-out'; other.mkdir()
        self.host.output = other
        self.dialog.open_result()
        self.assertIsNone(self.host.opened)
        self.assertIsNone(self.dialog.run_id)
        self.assertIn('工作空间', self.dialog.status.text())

    def test_legacy_same_path_replacement_invalidates_result(self):
        self.ready(); original = self.fx.output; backup = original.with_name('saved-output')
        original.rename(backup); shutil.copytree(backup, original)
        self.dialog.open_result()
        self.assertIsNone(self.host.opened)
        self.assertIsNone(self.dialog.run_id)

    def test_legacy_close_before_callback_does_not_rearm_result(self):
        self.fx.completed(); self.select(); self.host.deferred = True
        self.dialog.job_status(); self.assertEqual(len(self.host.pending), 1)
        self.dialog.reject(); self.host.finish()
        self.assertIsNone(self.dialog.run_id)
        self.assertFalse(self.dialog.open_button.isEnabled())
        self.assertFalse(self.dialog.busy)

    def test_legacy_changed_draft_clears_old_result_link(self):
        self.ready(); self.dialog.draft.setPlainText(encode({**self.fx.spec, 'question': 'new draft'}))
        self.assertIsNone(self.dialog.run_id)
        self.assertFalse(self.dialog.open_button.isEnabled())

    def test_legacy_dispatch_failure_clears_result_and_unlocks(self):
        self.ready(); self.host.broken = True
        self.dialog.open_result()
        self.assertIsNone(self.host.opened)
        self.assertIsNone(self.dialog.run_id)
        self.assertFalse(self.dialog.busy)
        self.assertIn('dispatch', self.dialog.status.text())

    def test_progress_context_invalidation_clears_visible_old_report(self):
        self.fx.completed()
        monitor = ProposalProgressDialog(self.host, self.fx.proposal['proposal_id'])
        self.dialogs.append(monitor)
        self.assertTrue(monitor.report['can_open_result'])
        self.host.output = self.fx.fx.root
        monitor.refresh()
        self.assertIsNone(monitor.report)
        self.assertEqual(monitor.details.toPlainText(), '{}')
        self.assertEqual(monitor.stage.text(), '')

    def workspace(self):
        d = StrategyWorkspaceDialog(self.host, self.host); self.dialogs.append(d)
        d.left_run.setText(str(uuid4())); d.right_run.setText(str(uuid4()))
        self.requested_comparison_ids = (d.left_run.text(), d.right_run.text())
        self.host.deferred = True
        d.compare_results(); self.assertEqual(len(self.host.pending), 1)
        return d

    def deliver_comparison(self, d):
        _, callback = self.host.pending.pop(0)
        left, right = self.requested_comparison_ids
        callback({'comparable': True, 'left': {'run_id': left}, 'right': {'run_id': right}}, '')
        self.assertFalse(d.busy)

    def test_compare_close_rejects_late_result(self):
        d = self.workspace(); d.reject(); self.deliver_comparison(d)
        self.assertEqual(d.result_details.toPlainText(), '{}')

    def test_compare_changed_ids_reject_late_result(self):
        d = self.workspace(); d.right_run.setText(str(uuid4())); self.deliver_comparison(d)
        self.assertEqual(d.result_details.toPlainText(), '{}')
        self.assertIn('忽略', d.status.text())

    def test_compare_workspace_change_rejects_late_result(self):
        d = self.workspace(); self.host.output = self.fx.fx.root; self.deliver_comparison(d)
        self.assertEqual(d.result_details.toPlainText(), '{}')
        self.assertIn('工作空间', d.status.text())

    def test_compare_same_path_replacement_rejects_late_result(self):
        d = self.workspace(); original = self.fx.output; backup = original.with_name('prior-output')
        original.rename(backup); shutil.copytree(backup, original)
        self.deliver_comparison(d)
        self.assertEqual(d.result_details.toPlainText(), '{}')

    def test_archive_query_after_root_change_never_reads_the_old_workspace(self):
        d = StrategyWorkspaceDialog(self.host, self.host); self.dialogs.append(d)
        self.host.output = self.fx.fx.root
        with patch('quantlab.trading.strategy_run_catalog.list_strategy_runs') as read:
            d.load_archives()
        read.assert_not_called()
        self.assertFalse(d.busy)
        self.assertIn('工作空间', d.status.text())

    def test_invalid_async_response_restores_controls_and_clears_prior_result(self):
        d = self.workspace()
        _, callback = self.host.pending.pop(0)
        callback(None, '')
        self.assertFalse(d.busy)
        self.assertTrue(d.tabs.isEnabled())
        self.assertEqual(d.result_details.toPlainText(), '{}')
        self.assertIn('失败', d.status.text())


    def test_preview_with_selection_already_empty_disarms_previous_result(self):
        self.dialog.draft.setPlainText(encode(self.fx.spec)); self.ready()
        self.assertIsNone(self.dialog.selected)
        self.dialog.preview()
        self.assertIsNone(self.dialog.run_id)
        self.assertFalse(self.dialog.open_button.isEnabled())
        self.assertEqual(len(self.fx.queue.list()), 1)

    def test_input_check_with_selection_already_empty_disarms_previous_result(self):
        self.dialog.draft.setPlainText(encode(self.fx.spec)); self.ready()
        with patch('quantlab.data.archived_research_check.check_archived_daily_research',
                   return_value={'compatible': False, 'blockers': [{'role': 'primary', 'message': 'fixture only'}]}):
            self.dialog.check_inputs()
        self.assertIsNone(self.dialog.run_id)
        self.assertFalse(self.dialog.open_button.isEnabled())
        self.assertIsNone(self.host.opened)


    def test_unchanged_comparison_context_accepts_matching_reply(self):
        d = self.workspace(); self.deliver_comparison(d)
        self.assertTrue(json.loads(d.result_details.toPlainText())['comparable'])
        self.assertTrue(d.tabs.isEnabled())

    def test_comparison_reply_with_other_ids_cannot_be_displayed(self):
        d = self.workspace(); _, callback = self.host.pending.pop(0)
        callback({'comparable': True, 'left': {'run_id': str(uuid4())}, 'right': {'run_id': str(uuid4())}}, '')
        self.assertEqual(d.result_details.toPlainText(), '{}')
        self.assertFalse(d.busy)
        self.assertIn('编号', d.status.text())


if __name__ == '__main__': unittest.main()
