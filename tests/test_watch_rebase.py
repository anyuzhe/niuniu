import unittest
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4
import test_watchlist as fixtures
from quantlab.agent.watch_rebase import WatchRebaseService
from quantlab.agent.watch_store import WatchStore
from quantlab.agent.tracking_control_store import ControlStore
from quantlab.agent.proposals import ProposalService
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.workbench.jobs import prepare,execute,JobQueue
from quantlab.storage.codec import digest


class WatchRebaseTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WatchlistTests()
        legacy = {**runtime_fingerprint(),'code_hash':'legacy-test-runtime'}
        with patch('quantlab.experiments.runner.runtime_fingerprint',return_value=legacy):
            self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.watch = self.f.create()['watch_id']
        self.f.service.store.set_active(self.watch,False)
        self.new = execute(prepare(self.f.spec),self.f.root,self.f.output)
        self.service = WatchRebaseService(self.f.output,self.f.root)
    def preview(self): return self.service.preview(self.watch,self.new.run_id,'新版基准')
    def accept(self,plan=None):
        plan = plan or self.preview()
        return self.service.accept(plan,digest(plan),confirmed=True)
    def test_matching_baseline_creates_paused_watch_and_preserves_history(self):
        folder = self.f.service.store.folder(self.watch)
        before = {str(p):p.read_bytes() for p in folder.rglob('*.json')}
        plan = self.preview();self.assertNotEqual(plan['old_runtime'],plan['runtime'])
        result = self.accept(plan);self.assertTrue(result['created'])
        definition,state = self.f.service.store.read(result['new_watch_id'])
        self.assertFalse(state['active']);self.assertEqual(len(state['history']),1)
        self.assertEqual(state['refresh_requests'],[])
        self.assertIsNone(ControlStore(self.f.output).get(result['new_watch_id']))
        self.assertEqual(before,{str(p):p.read_bytes() for p in folder.rglob('*.json')})
        self.assertFalse(self.accept(plan)['created'])
        self.assertFalse(list(self.f.output.glob('_jobs/*.json')))
    def test_confirmation_and_stale_preview_required(self):
        plan = self.preview()
        with self.assertRaisesRegex(ValueError,'确认'):
            self.service.accept(plan,digest(plan))
        with self.assertRaises(ValueError):self.service.accept(plan,'changed',confirmed=True)
        self.f.service.store.set_active(self.watch,True)
        with self.assertRaisesRegex(ValueError,'暂停'):self.accept(plan)
        self.assertFalse((self.f.output/'_watch_rebases').exists())
    def test_changes_in_parameters_period_or_source_rejected(self):
        for change in ({'parameters':{'lookback':3}},{'end':'2025-01-10'}):
            result = execute(prepare({**self.f.spec,**change}),self.f.root,self.f.output)
            with self.assertRaises(ValueError):self.service.preview(self.watch,result.run_id,'新版')
        (self.new.artifact_path/'observations.parquet').write_bytes(b'corrupt')
        with self.assertRaises(Exception):self.preview()
    def test_lost_final_receipt_reuses_new_watch_without_splicing(self):
        from quantlab.agent import watch_rebase
        plan = self.preview();write = watch_rebase.write_checked
        def interrupted(path,value):
            if value.get('status')=='completed': raise OSError('lost final receipt')
            return write(path,value)
        with patch.object(watch_rebase,'write_checked',side_effect=interrupted):
            with self.assertRaises(OSError):self.accept(plan)
        self.assertFalse(self.f.service.store.read(plan['new_watch_id'])[1]['active'])
        result = self.accept(plan)
        self.assertEqual(len(self.f.service.store.read(result['new_watch_id'])[1]['history']),1)
        self.assertFalse(self.accept(plan)['created'])
    def test_interrupted_initial_snapshot_can_be_recovered(self):
        plan = self.preview()
        with patch.object(WatchStore,'publish',side_effect=OSError('first snapshot interrupted')):
            with self.assertRaises(OSError):self.accept(plan)
        self.assertFalse(self.f.service.store.read(plan['new_watch_id'])[1]['active'])
        result = self.accept(plan)
        self.assertFalse(self.f.service.store.read(result['new_watch_id'])[1]['active'])
        self.assertEqual(len(self.f.service.store.read(result['new_watch_id'])[1]['history']),1)
    def test_wrong_runtime_active_grant_and_path_rejected(self):
        with self.assertRaises(ValueError):self.service.preview('../bad',self.new.run_id,'x')
        with patch('quantlab.agent.watch_rebase.runtime_fingerprint',return_value={'code_hash':'other'}):
            with self.assertRaisesRegex(ValueError,'当前代码'):self.preview()
        store = ControlStore(self.f.output)
        with store.locked(self.watch):store.save({'watch_id':self.watch,'enabled':True,'cycles':[]})
        with self.assertRaisesRegex(ValueError,'撤销'):self.preview()
    def test_rebuild_proposal_uses_original_approval_queue(self):
        request_id = str(uuid4())
        proposal = self.service.propose(self.watch,request_id)
        self.assertEqual(proposal['status'],'pending')
        self.assertEqual(proposal['proposal_id'],self.service.propose(self.watch,request_id)['proposal_id'])
        self.assertEqual(proposal['plan']['spec']['end'],self.f.spec['end'])
        self.assertFalse(list(self.f.output.glob('_jobs/*.json')))
        queue = JobQueue(self.f.output,self.f.root)
        try:
            ProposalService(self.f.output,self.f.root).approve_and_submit(
                proposal['proposal_id'],proposal['proposal_digest'],lambda:queue)
        finally:queue.close()
        self.assertEqual(queue.list()[0]['status'],'completed',queue.list())
        self.service.preview(self.watch,queue.list()[0]['run_id'],'审批后基准')
    def test_model_has_no_rebase_approval_tool(self):
        from quantlab.agent.market_data_tools import MarketDataResearchAPI
        api = MarketDataResearchAPI(self.f.output,self.f.root)
        for name in ('accept_rebase','authorize_rebase','rebase_watch'):
            self.assertFalse(api.call(name,{})['ok'])
    def test_concurrent_rebase_is_locked_and_does_not_create_partial_target(self):
        plan = self.preview()
        with ControlStore(self.f.output).locked(self.watch):
            with self.assertRaises(BlockingIOError):self.accept(plan)
        self.assertFalse(self.f.service.store.folder(plan['new_watch_id']).exists())
    def test_source_changed_after_confirmation_cannot_finish_rebase(self):
        import polars as pl
        plan=self.preview();create=self.service.watch.create
        def changed(*args,**kwargs):
            path=self.new.artifact_path/'bars.parquet'
            frame=pl.read_parquet(path)
            frame.with_columns(*[(pl.col(k)*2).alias(k) for k in ('open','high','low','close')]).write_parquet(path)
            return create(*args,**kwargs)
        with patch.object(self.service.watch,'create',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'期间来源变化'):self.accept(plan)
        self.assertFalse(self.f.service.store.read(plan['new_watch_id'])[1]['active'])
        self.assertEqual(self.service.history(self.watch)['records'][0]['status'],'prepared')
