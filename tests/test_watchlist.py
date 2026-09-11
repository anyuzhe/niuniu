import json
import unittest
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import polars as pl
import test_core
from test_campaigns import pack
from quantlab.workbench.jobs import prepare, execute, JobQueue
from quantlab.agent.watchlist import WatchService
from quantlab.agent.proposals import ProposalService
from quantlab.storage.artifact_integrity import snapshot_tree, verify_tree


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.CoreTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root; self.output = self.root/'watches'; self.output.mkdir()
        self.spec = deepcopy(pack(self.fixture.symbols)['nodes'][0]['spec'])
        self.spec.pop('permutation'); self.spec.update(end='2025-01-07',quantiles=3,horizons=[1,2])
        self.source = execute(prepare(self.spec),self.root,self.output)
        self.service = WatchService(self.output,self.root)
    def create(self):
        return self.service.create('固定动量',self.source.run_id,windows=[5],min_dates=1)
    def later(self, **changes):
        return execute(prepare({**self.spec,'end':'2025-01-10',**changes}),self.root,self.output)
    def test_create_advance_restart_and_duplicate_snapshots(self):
        before = snapshot_tree(self.output,self.source.run_id)
        initial = self.create(); watch = initial['watch_id']
        self.assertTrue(initial['created'])
        again = self.service.observe(watch,self.source.run_id)
        self.assertFalse(again['created'])
        later = self.later(); fresh = self.service.observe(watch,later.run_id)
        self.assertEqual(fresh['snapshot']['change']['kind'],'advanced')
        restored = WatchService(self.output,self.root)
        value = restored.get(watch)
        self.assertEqual(value['snapshot_count'],2)
        self.assertEqual(value['source_integrity'],'verified')
        self.assertEqual(value['history'][0]['source_run_id'],self.source.run_id)
        self.assertGreater(fresh['snapshot']['preview']['bars'],initial['snapshot']['preview']['bars'])
        self.assertFalse(restored.observe(watch,later.run_id)['created'])
        verify_tree(self.output,before)
    def test_parameter_price_or_cutoff_change_is_not_silently_accepted(self):
        watch = self.create()['watch_id']
        changed = self.later(parameters={'lookback':3})
        with self.assertRaisesRegex(ValueError,'parameters'):
            self.service.observe(watch,changed.run_id)
        with self.assertRaisesRegex(ValueError,'backwards'):
            self.service.observe(watch,self.source.run_id,'2025-01-05T15:00:00+08:00')
        self.service.store.set_active(watch,False)
        with self.assertRaisesRegex(ValueError,'paused'): self.service.observe(watch,self.source.run_id)
        self.assertEqual(self.service.get(watch)['snapshot_count'],1)
    def test_historical_price_revision_is_recorded_without_overwriting_baseline(self):
        initial = self.create(); watch = initial['watch_id']
        first = self.service.store.snapshot(watch,initial['snapshot']['snapshot_id'])
        path = next((self.root/'lake/silver/qfq_kline_daily').glob('*.parquet'))
        frame = pl.read_parquet(path)
        frame.with_columns((pl.col('close').cast(pl.Float64)*1.001).alias('close')).write_parquet(path)
        later = self.later(); revised = self.service.observe(watch,later.run_id)
        self.assertTrue(revised['snapshot']['change']['historical_revision'])
        self.assertTrue(any(a['kind']=='historical_input_revision' for a in revised['snapshot']['alerts']))
        self.assertEqual(self.service.store.snapshot(watch,first['snapshot_id']),first)
    def test_corrupt_and_missing_source_report_integrity_loss(self):
        watch = self.create()['watch_id']; path = self.source.artifact_path/'observations.parquet'
        path.write_bytes(b'changed')
        self.assertEqual(self.service.get(watch)['source_integrity'],'source_changed')
        path.unlink()
        self.assertNotEqual(self.service.get(watch)['source_integrity'],'verified')
        self.assertEqual(self.service.get(watch)['snapshot_count'],1)
    def test_refresh_proposal_requires_host_approval_and_sync_is_idempotent(self):
        watch = self.create()['watch_id']; request = str(uuid4())
        proposal = self.service.propose_refresh(watch,'2025-01-10',request)
        self.assertEqual(proposal['status'],'pending')
        self.assertEqual(self.service.propose_refresh(watch,'2025-01-10',request)['proposal_id'],proposal['proposal_id'])
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
        with self.assertRaises(ValueError):self.service.sync_refresh(watch,proposal['proposal_id'])
        queue = JobQueue(self.output,self.root)
        try:
            ProposalService(self.output,self.root).approve_and_submit(
                proposal['proposal_id'],proposal['proposal_digest'],lambda:queue)
        finally: queue.close()
        self.assertEqual(queue.list()[0]['status'],'completed',queue.list())
        synced = self.service.sync_refresh(watch,proposal['proposal_id'])
        self.assertTrue(synced['created'])
        self.assertFalse(self.service.sync_refresh(watch,proposal['proposal_id'])['created'])
        self.assertEqual(self.service.get(watch)['snapshot_count'],2)
        self.assertEqual(len(queue.list()),1)
    def test_store_rejects_path_escape_and_snapshot_modification(self):
        watch = self.create()['watch_id']
        with self.assertRaises(ValueError):self.service.store.read('../outside')
        _, state = self.service.store.read(watch)
        path = self.service.store.folder(watch)/'snapshots'/(state['history'][0]+'.json')
        value = json.loads(path.read_text()); value['preview']['bars'] = 99999
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.service.get(watch)
    def test_reading_absent_watchlist_does_not_create_storage(self):
        empty = self.root/'empty'; empty.mkdir()
        self.assertEqual(WatchService(empty).store.list()['watches'],[])
        self.assertEqual(list(empty.iterdir()),[])
    def test_agent_can_query_but_not_create_or_refresh_watches(self):
        from quantlab.agent.watch_tools import WatchResearchAPI
        watch = self.create()['watch_id']; api = WatchResearchAPI(self.output,self.root)
        listed = api.call('list_factor_watches',{'query':'固定','offset':0,'limit':10})
        self.assertTrue(listed['ok'],listed)
        self.assertEqual(listed['data']['watches'][0]['watch_id'],watch)
        found = api.call('get_factor_watch',{'watch_id':watch})
        self.assertTrue(found['ok'],found)
        self.assertEqual(found['data']['source_integrity'],'verified')
        self.assertTrue(any(r['kind']=='watch' for r in found['evidence']))
        for name in ('create_watch','refresh_watch','approve_refresh'):
            self.assertFalse(api.call(name,{})['ok'])
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
    def test_changed_statistical_implementation_requires_new_watch(self):
        from unittest.mock import patch
        watch = self.create()['watch_id']
        with patch('quantlab.agent.watchlist.tracking_fingerprint',return_value='changed'):
            with self.assertRaisesRegex(ValueError,'algorithm'):
                self.service.propose_refresh(watch,'2025-01-10',str(uuid4()))
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
