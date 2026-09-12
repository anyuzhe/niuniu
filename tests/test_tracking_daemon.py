from pathlib import Path
import plistlib,tempfile,unittest
import test_tracking_scheduler as fixtures
from quantlab.agent.tracking_daemon import TrackingDaemon,daemon_active,daemon_lock,write_launchd
from quantlab.agent.tracking_control_store import ControlStore
from quantlab.workbench.jobs import JobQueue


class TrackingDaemonTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.TrackingSchedulerTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
    def test_empty_daemon_does_not_create_research_queue(self):
        daemon=TrackingDaemon(self.fx.output,self.fx.data)
        result=daemon.tick(at=fixtures.NOW)
        self.assertEqual(result['status'],'ok');self.assertEqual(result['result']['controls'],[])
        self.assertFalse((self.fx.output/'_jobs').exists())
    def test_existing_worker_causes_clean_skip_without_state_mutation(self):
        self.fx.grant();before=ControlStore(self.fx.output).get(self.fx.watch)
        queue=JobQueue(self.fx.output,self.fx.data)
        try:result=TrackingDaemon(self.fx.output,self.fx.data).tick(at=fixtures.NOW)
        finally:queue.close()
        self.assertEqual(result['status'],'workspace_busy')
        self.assertEqual(ControlStore(self.fx.output).get(self.fx.watch),before)

    def test_daemon_runs_authorized_job_then_releases_worker(self):
        self.fx.grant(max_jobs=1);daemon=TrackingDaemon(self.fx.output,self.fx.data)
        first=daemon.tick(at=fixtures.NOW);self.assertEqual(first['status'],'ok')
        self.assertIsNotNone(daemon.queue);daemon.close()
        second=daemon.tick(at=fixtures.NOW.replace(hour=21));daemon.close()
        state=ControlStore(self.fx.output).get(self.fx.watch)
        self.assertEqual(self.fx.watches.get(self.fx.watch)['snapshot_count'],2)
        self.assertEqual(state['cycles'][0]['status'],'synced')
        self.assertFalse(state['enabled']);self.assertEqual(state['status'],'budget_exhausted')
        probe=JobQueue(self.fx.output,self.fx.data);probe.close()
        self.assertEqual(second['status'],'ok')
    def test_single_daemon_lock_and_launchd_config(self):
        with daemon_lock(self.fx.output):
            self.assertTrue(daemon_active(self.fx.output))
            with self.assertRaisesRegex(ValueError,'已有跟踪守护进程'):
                with daemon_lock(self.fx.output):pass
        self.assertFalse(daemon_active(self.fx.output))
        path=self.fx.output/'test.plist';result=write_launchd(path,self.fx.output,self.fx.data,120)
        value=plistlib.loads(path.read_bytes())
        self.assertFalse(result['loaded']);self.assertFalse(result['authorization_created'])
        self.assertTrue(value['RunAtLoad']);self.assertIn('quantlab.agent.tracking_daemon',value['ProgramArguments'])
