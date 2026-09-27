import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

import test_watchlist
from quantlab.desktop.app import MainWindow
from quantlab.desktop.factor_watches import FactorWatchDialog
from quantlab.desktop.proposal_progress import ProposalProgressDialog
from quantlab.agent.watchlist import WatchService
from quantlab.agent.proposal_progress import read_proposal_progress
from quantlab.trading.research_evidence import archive_research_reference


class WatchWorkflowDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.fx=test_watchlist.WatchlistTests(); self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.window=MainWindow(self.fx.output)
        self.window.data_root=self.fx.root  # No unrelated automatic market overview on construction.
        self.addCleanup(self.close_window)

    def wait(self,predicate):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            QApplication.processEvents()
            if predicate(): return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')

    def close_window(self):
        for dialog in self.window.dialogs: dialog.close()
        self.wait(lambda:not self.window.callbacks)
        self.window.close(); QApplication.processEvents()

    def open_watch(self):
        self.window.factor_watches(); dialog=next(d for d in self.window.dialogs if isinstance(d,FactorWatchDialog))
        self.wait(lambda:not dialog.busy and dialog.watches.count() >= 0)
        return dialog

    def test_initial_load_does_not_scan_archives_and_source_is_explicit(self):
        with patch.object(self.window.catalog,'list',side_effect=AssertionError('must not read archive catalog')) as listing:
            dialog=self.open_watch()
            listing.assert_not_called()
            self.assertEqual(dialog.source.count(),0)
            self.assertIsNone(dialog.source.currentData())
        ref=archive_research_reference(self.fx.output,self.fx.source.run_id)
        dialog.select_source(ref)
        self.assertEqual(dialog.source.currentData(),self.fx.source.run_id)
        self.assertEqual(dialog._selected_reference()['source']['fingerprint'],ref['source']['fingerprint'])

    def test_inspection_binds_exact_history_without_unavailable_ai_action(self):
        service=WatchService(self.fx.output,self.fx.root)
        first=service.create('桌面历史',self.fx.source.run_id,windows=[5],min_dates=1)
        second_run=self.fx.later(); second=service.observe(first['watch_id'],second_run.run_id)
        dialog=self.open_watch(); self.wait(lambda:dialog.watches.count()==1)
        dialog.watches.setCurrentIndex(dialog.watches.findData(first['watch_id']))
        self.wait(lambda:not dialog.busy and dialog.history.count()==2 and dialog.snapshot_result is not None)
        latest_id=second['snapshot']['snapshot_id']
        self.assertEqual(dialog.snapshot_result['snapshot_id'],latest_id)
        dialog.history.setCurrentIndex(dialog.history.findData(first['snapshot']['snapshot_id']))
        self.wait(lambda:not dialog.busy and dialog.snapshot_result is not None and dialog.snapshot_result['snapshot_id']==first['snapshot']['snapshot_id'])
        self.assertFalse(dialog.snapshot_result['is_latest'])
        self.assertEqual(dialog.shown_run_id,self.fx.source.run_id)
        self.assertFalse(hasattr(dialog,'ai_button'))
        self.assertGreater(dialog.maturity_table.rowCount(),0)
        self.assertIn('历史',dialog.snapshot_heading.text())
        self.assertEqual(dialog.snapshot_result['snapshot'],first['snapshot'])

    def test_refresh_progress_is_read_only_and_proposal_must_belong_to_watch(self):
        dialog=self.open_watch(); reference=archive_research_reference(self.fx.output,self.fx.source.run_id)
        dialog.select_source(reference);dialog.name.setText('进度只读');dialog.windows.setText('5');dialog.minimum.setValue(1)
        dialog.create_watch();self.wait(lambda:not dialog.busy and dialog.selected is not None)
        watch_id=dialog.watches.currentData()
        dialog.end.setDate(__import__('PyQt6.QtCore',fromlist=['QDate']).QDate(2025,1,10))
        dialog.propose_refresh();self.wait(lambda:not dialog.busy and dialog.requests.count()==1)
        proposal_id,job_id=dialog.requests.currentData()
        before=list((self.fx.output/'_jobs').glob('*.json'))
        dialog.open_progress();self.wait(lambda:not dialog.busy)
        progress=next(d for d in self.window.dialogs if isinstance(d,ProposalProgressDialog))
        self.wait(lambda:not progress.busy and progress.report is not None)
        self.assertEqual(progress.report['phase'],'awaiting_approval')
        self.assertEqual(list((self.fx.output/'_jobs').glob('*.json')),before)
        progress.close()
        # A proposal/job pair not present in the watch request ledger is rejected before progress I/O.
        with patch.object(dialog.service,'get',return_value={**dialog.selected,'refresh_requests':[]}):
            dialog._open_verified_progress({**dialog.selected,'refresh_requests':[]},watch_id,proposal_id,job_id)
        self.assertIn('不再属于',dialog.status.text())

    def test_root_change_blocks_each_mutation_and_discards_late_read(self):
        dialog=self.open_watch();dialog.select_source(archive_research_reference(self.fx.output,self.fx.source.run_id))
        dialog.name.setText('root变化');dialog.windows.setText('5');dialog.minimum.setValue(1)
        before=WatchService(self.fx.output,self.fx.root).store.list()
        old_output=self.window.output;self.window.output=str(self.fx.output/'replaced-root')
        try:
            dialog.create_watch();dialog.attach();dialog.toggle_pause();dialog.sync_refresh();dialog.propose_refresh()
            self.assertEqual(WatchService(self.fx.output,self.fx.root).store.list(),before)
        finally:self.window.output=old_output

    def test_pause_uses_state_digest_and_inspect_rejects_stale_digest(self):
        created=WatchService(self.fx.output,self.fx.root).create('CAS pause',self.fx.source.run_id,windows=[5],min_dates=1)
        service=WatchService(self.fx.output,self.fx.root);watch=service.get(created['watch_id'])
        inspected=service.inspect_snapshot(created['watch_id'],created['snapshot']['snapshot_id'])
        self.assertFalse(inspected['claim_verified']);self.assertEqual(inspected['source_integrity'],'verified')
        with self.assertRaisesRegex(ValueError,'changed'):
            service.inspect_snapshot(created['watch_id'],created['snapshot']['snapshot_id'],expected_digest='0'*64)
        service.store.set_active(created['watch_id'],False,expected_state_digest=watch['state_digest'])
        with self.assertRaisesRegex(ValueError,'changed'):
            service.store.set_active(created['watch_id'],True,expected_state_digest=watch['state_digest'])


if __name__=='__main__': unittest.main()
