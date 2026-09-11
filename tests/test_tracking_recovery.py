from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
import unittest
import test_tracking_scheduler as fixtures
from quantlab.agent.tracking_scheduler import TrackingScheduler
from quantlab.agent.tracking_control_store import control_summary
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.workbench.jobs import JobQueue
from quantlab.progress import ResearchCancelled
from quantlab.storage.codec import digest


class TrackingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.TrackingSchedulerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.grant(max_jobs=1)
        self.queue=JobQueue(self.f.output,self.f.data)
        with patch('quantlab.workbench.jobs.execute',side_effect=ResearchCancelled('manual recovery fixture')):
            TrackingScheduler(self.f.output,self.f.data,lambda:self.queue).tick(now=fixtures.NOW)
            self.queue.close()
        TrackingScheduler(self.f.output,self.f.data,lambda:self.queue).tick(now=fixtures.NOW+timedelta(minutes=1))
        self.job=self.queue.list()[0]['job_id']
    def resume_manually(self):
        self.queue=JobQueue(self.f.output,self.f.data)
        try:self.queue.resume(self.job)
        finally:self.queue.close()
        self.assertEqual(self.queue.list()[0]['status'],'completed')
    def reconcile(self):
        return TrackingScheduler(self.f.output,self.f.data,lambda:self.queue).reconcile_completed(self.f.watch)
    def test_completed_manual_retry_syncs_without_enabling_or_repeating(self):
        before=self.f.store.get(self.f.watch);self.resume_manually()
        with patch.object(self.queue,'submit',side_effect=AssertionError('must not submit')),patch.object(self.queue,'resume',side_effect=AssertionError('must not resume')):
            result=self.reconcile();again=self.reconcile()
        self.assertEqual(result['synchronized'],1);self.assertEqual(again['synchronized'],0)
        self.assertEqual(result['new_research_jobs'],0);self.assertEqual(result['resumed_jobs'],0)
        state=self.f.store.get(self.f.watch)
        self.assertFalse(state['enabled']);self.assertEqual(state['grant'],before['grant'])
        self.assertEqual(len(state['cycles']),1);self.assertEqual(len(self.queue.list()),1)
        self.assertEqual(state['cycles'][0]['manual_recovery']['attempt'],2)
        self.assertEqual(state['cycles'][0]['manual_recovery']['from_status'],'cancelled')
        self.assertEqual(self.f.watches.get(self.f.watch)['snapshot_count'],2)
        self.assertIsNotNone(control_summary(state)['last_reconciliation'])
    def test_terminal_job_not_manually_retried_is_only_reported(self):
        with patch.object(self.queue,'resume',side_effect=AssertionError('no retries')):
            result=self.reconcile()
        self.assertEqual(result['results'][0]['status'],'not_completed')
        self.assertEqual(result['synchronized'],0)
        self.assertEqual(self.f.watches.get(self.f.watch)['snapshot_count'],1)
    def test_revoked_grant_stays_revoked_for_execution_after_sync(self):
        self.resume_manually();self.f.store.revoke(self.f.watch)
        result=self.reconcile();state=self.f.store.get(self.f.watch)
        self.assertEqual(result['synchronized'],1);self.assertFalse(state['enabled'])
        self.assertEqual(state['recovery_previous_status'],'revoked')
        TrackingScheduler(self.f.output,self.f.data,lambda:self.queue).tick()
        self.assertEqual(len(self.queue.list()),1)
    def test_paused_watch_does_not_accept_recovered_result(self):
        self.resume_manually();self.f.watches.store.set_active(self.f.watch,False)
        result=self.reconcile()
        self.assertEqual(result['results'][0]['status'],'requires_review')
        self.assertEqual(result['synchronized'],0)
        self.assertEqual(self.f.watches.get(self.f.watch)['snapshot_count'],1)
    def test_changed_job_config_is_not_accepted(self):
        self.resume_manually();jobs=deepcopy(self.queue.list())
        jobs[0]['spec']['parameters']={'lookback':99}
        with patch.object(self.queue,'list',return_value=jobs):result=self.reconcile()
        self.assertEqual(result['results'][0]['status'],'requires_review')
        self.assertEqual(result['synchronized'],0)
    def test_missing_original_job_is_not_replaced(self):
        with patch.object(self.queue,'list',return_value=[]),patch.object(self.queue,'submit',side_effect=AssertionError('no replacement')):
            result=self.reconcile()
        self.assertEqual(result['results'][0]['status'],'requires_review')
        self.assertIn('缺失',result['results'][0]['error'])
        self.assertFalse(self.f.store.get(self.f.watch)['enabled'])
    def test_broken_recovered_archive_does_not_advance_snapshot(self):
        self.resume_manually();run=self.queue.list()[0]['run_id']
        (self.f.output/run/'bars.parquet').write_bytes(b'invalid isolated fixture')
        result=self.reconcile()
        self.assertEqual(result['results'][0]['status'],'requires_review')
        self.assertEqual(result['synchronized'],0)
        self.assertEqual(self.f.watches.get(self.f.watch)['snapshot_count'],1)
    def test_crash_after_snapshot_publish_does_not_duplicate_on_reopen(self):
        self.resume_manually()
        with patch('quantlab.agent.tracking_control_store.ControlStore.save',side_effect=SystemExit('simulated process loss')):
            with self.assertRaises(SystemExit):self.reconcile()
        self.assertEqual(self.f.watches.get(self.f.watch)['snapshot_count'],2)
        self.assertEqual(self.f.store.get(self.f.watch)['cycles'][0]['status'],'cancelled')
        result=self.reconcile()
        self.assertEqual(result['synchronized'],1)
        self.assertEqual(self.f.watches.get(self.f.watch)['snapshot_count'],2)
        self.assertEqual(len(self.queue.list()),1)
    def test_model_has_no_recovery_write_tool(self):
        api=MarketDataResearchAPI(self.f.output,self.f.data)
        before=digest(self.f.store.get(self.f.watch))
        for name in ('reconcile_completed','recover_tracking','resume_tracking'):
            self.assertFalse(api.call(name,{'watch_id':self.f.watch})['ok'])
        self.assertEqual(before,digest(self.f.store.get(self.f.watch)))
