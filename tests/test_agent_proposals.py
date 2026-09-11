import json
import time
import unittest
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from types import SimpleNamespace
import test_core
from test_workbench_jobs import spec as job_spec
from quantlab.agent.planning import ResearchBudget,ProposalError,parse_spec,preview_experiment
from quantlab.agent.proposals import ProposalService
from quantlab.agent.proposal_tools import ResearchProposalAPI
from quantlab.storage.codec import encode
from quantlab.workbench.jobs import JobQueue


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.output=self.fixture.root/'proposal-runs';self.output.mkdir();self.queue=None
        self.addCleanup(lambda:self.queue.close() if self.queue else None)
        self.service=ProposalService(self.output,self.fixture.root)
        self.api=ResearchProposalAPI(self.output,self.fixture.root)
        self.spec=job_spec(symbols=list(self.fixture.symbols),replay=True)
    def get_queue(self):
        if self.queue is None:self.queue=JobQueue(self.output,self.fixture.root)
        return self.queue
    def proposal(self):return self.service.propose(str(uuid4()),self.spec)
    def settled(self,job_id):
        deadline=time.time()+15
        while time.time()<deadline:
            value=next(j for j in self.queue.list() if j['job_id']==job_id)
            if value['status'] not in ('queued','running'):return value
            time.sleep(.02)
        self.fail('Research job did not settle')

    def test_preview_is_data_free_and_model_cannot_approve(self):
        with patch('quantlab.data.mqc.MQCParquetProvider.load',side_effect=AssertionError('no data read')):
            result=self.api.call('preview_experiment',{'spec_json':encode(self.spec)})
        self.assertTrue(result['ok'],result);self.assertEqual(list(self.output.iterdir()),[])
        self.assertEqual(len(self.api.schemas()),9)
        for name in ('approve_experiment','approve_and_submit','submit','run_shell'):
            self.assertEqual(self.api.call(name,{})['error']['code'],'UNKNOWN_TOOL')
        self.assertFalse(self.api.call('get_capabilities',{})['data']['approval_tools_available_to_model'])

    def test_invalid_json_paths_and_budget_limits(self):
        for text in ('[]','{"a":1,"a":2}','{"v":NaN}','x'*65537):
            with self.subTest(text=text[:20]),self.assertRaises(ProposalError):parse_spec(text)
        for changes in ({'symbols':self.spec['symbols']*101},{'start':'1900-01-01'},
                {'bootstrap':{'resamples':10001}},{'horizons':list(range(1,7))},
                {'universe':{'mode':'listing','reference_manifest':'/other/private.json'}}):
            with self.subTest(changes=changes),self.assertRaises(ProposalError):
                preview_experiment({**self.spec,**changes})
        summary=preview_experiment({**self.spec,'mode':'sweep','grid':{'lookback':[2,3]},
            'split':{'train_end':'2025-01-04','valid_end':'2025-01-07'}})
        self.assertEqual(summary['estimate']['leaf_studies'],6)

    def test_proposal_idempotency_rejection_and_no_queue_side_effect(self):
        key=str(uuid4());first=self.service.propose(key,self.spec)
        second=self.service.propose(key,self.spec)
        self.assertEqual(first,second);self.assertFalse((self.output/'_jobs').exists())
        with self.assertRaises(ProposalError):self.service.propose(key,{**self.spec,'question':'different'})
        with self.assertRaises(ProposalError):
            self.service.approve_and_submit(first['proposal_id'],'wrong',self.get_queue)
        self.assertIsNone(self.queue)
        self.service.store.reject(first['proposal_id'],first['proposal_digest'])
        with self.assertRaises(ProposalError):
            self.service.approve_and_submit(first['proposal_id'],first['proposal_digest'],self.get_queue)
        self.assertIsNone(self.queue)

    def test_host_approval_real_queue_and_duplicate_click(self):
        proposal=self.proposal()
        first=self.service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        result=self.settled(first['job']['job_id']);self.assertEqual(result['status'],'completed',result)
        reopened=ProposalService(self.output,self.fixture.root)
        second=reopened.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        self.assertEqual(second['job']['job_id'],first['job']['job_id'])
        self.assertEqual(second['job']['run_id'],result['run_id']);self.assertEqual(len(self.queue.list()),1)
        self.assertTrue((self.output/result['run_id']/'experiment.json').exists())
        self.assertEqual(reopened.store.get(proposal['proposal_id'])['status'],'submitted')

    def test_stale_code_budget_and_corrupt_payload_rejected(self):
        proposal=self.proposal()
        with patch('quantlab.agent.proposals.runtime_fingerprint',return_value={'changed':True}):
            with self.assertRaises(ProposalError):self.service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        changed=ProposalService(self.output,self.fixture.root,budget=replace(ResearchBudget(),max_symbols=99))
        with self.assertRaises(ProposalError):changed.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        self.assertIsNone(self.queue)
        with self.service.store.transaction() as connection:
            connection.execute('UPDATE proposals SET payload=? WHERE id=?',('{}',proposal['proposal_id']))
        with self.assertRaises(ProposalError):self.service.store.get(proposal['proposal_id'])

    def test_lost_submission_acknowledgement_never_duplicates_job(self):
        proposal=self.proposal();queue=self.get_queue();original=queue.submit
        def lose_ack(*args,**kwargs):
            original(*args,**kwargs);raise OSError('simulated acknowledgement loss')
        with patch.object(queue,'submit',side_effect=lose_ack),self.assertRaises(OSError):
            self.service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        self.assertEqual(self.service.store.get(proposal['proposal_id'])['status'],'approved')
        self.service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        final=self.settled(proposal['job_id'])
        self.assertEqual(final['status'],'completed',final);self.assertEqual(len(queue.list()),1)
        self.queue.close();self.queue=None
        replay=self.service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        self.assertEqual(replay['job']['run_id'],final['run_id']);self.assertEqual(len(self.queue.list()),1)

    def test_pending_limit_and_workspace_binding(self):
        service=ProposalService(self.output,self.fixture.root,budget=replace(ResearchBudget(),max_pending_proposals=1))
        first=service.propose(str(uuid4()),self.spec)
        with self.assertRaises(ProposalError):service.propose(str(uuid4()),self.spec)
        other=self.fixture.root/'other';other.mkdir()
        moved=ProposalService(self.output,other,budget=service.budget)
        with self.assertRaises(ProposalError):moved.approve_and_submit(first['proposal_id'],first['proposal_digest'],self.get_queue)

    def test_active_budget_retains_approval_for_retry(self):
        service=ProposalService(self.output,self.fixture.root,budget=replace(ResearchBudget(),max_active_jobs=1))
        proposal=service.propose(str(uuid4()),self.spec)
        full=SimpleNamespace(root=self.output,data_root=self.fixture.root,
            list=lambda:[{'job_id':str(uuid4()),'status':'running'}])
        with self.assertRaises(ProposalError):
            service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],lambda:full)
        self.assertEqual(service.store.get(proposal['proposal_id'])['status'],'approved')
        result=service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        self.assertEqual(self.settled(result['job']['job_id'])['status'],'completed')

    def test_cooperative_deadline_stops_at_checkpoint(self):
        from quantlab.progress import checkpoint
        service=ProposalService(self.output,self.fixture.root,budget=replace(ResearchBudget(),cooperative_seconds=1))
        proposal=service.propose(str(uuid4()),self.spec)
        def slow(*args):time.sleep(1.1);checkpoint();self.fail('deadline should stop work')
        with patch('quantlab.workbench.jobs.execute',side_effect=slow):
            result=service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
            final=self.settled(result['job']['job_id'])
        self.assertEqual(final['status'],'failed');self.assertIn('TimeoutError',final['error'])

    def test_pending_job_checks_runtime_again_before_execution(self):
        import threading
        from quantlab.experiments.runner import runtime_fingerprint
        entered=threading.Event();release=threading.Event();calls=[];queue=self.get_queue()
        def fake(*args):
            calls.append(1);entered.set();release.wait(5)
            return SimpleNamespace(run_id=str(uuid4()),experiment_id='fixture')
        with patch('quantlab.workbench.jobs.execute',side_effect=fake):
            queue.submit(str(uuid4()),self.spec);self.assertTrue(entered.wait(5))
            job_id=str(uuid4());guard={'runtime':runtime_fingerprint(),'cooperative_seconds':10,'max_active_jobs':4}
            queue.submit(job_id,self.spec,execution_guard=guard)
            try:
                with patch('quantlab.experiments.runner.runtime_fingerprint',return_value={'changed':True}):
                    release.set();final=self.settled(job_id)
            finally:release.set()
        self.assertEqual(final['status'],'failed');self.assertIn('代码或依赖环境已变化',final['error'])
        self.assertEqual(len(calls),1)

    def test_sqlite_store_rejects_external_symlink(self):
        outside=self.fixture.root/'outside';outside.mkdir()
        (self.output/'_agent').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ProposalError):self.proposal()
        self.assertEqual(list(outside.iterdir()),[])

    def test_expired_proposal_and_missing_submitted_job_fail_closed(self):
        proposal=self.proposal()
        with self.service.store.transaction() as connection:
            connection.execute('UPDATE proposals SET created_at=? WHERE id=?',('2020-01-01T00:00:00+00:00',proposal['proposal_id']))
        with self.assertRaises(ProposalError) as error:
            self.service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        self.assertEqual(error.exception.code,'STALE_PROPOSAL');self.assertIsNone(self.queue)
        fresh=self.proposal()
        self.service.approve_and_submit(fresh['proposal_id'],fresh['proposal_digest'],self.get_queue)
        self.settled(fresh['job_id']);self.queue.close();self.queue=None
        (self.output/'_jobs'/(fresh['job_id']+'.json')).unlink()
        with self.assertRaises(ProposalError) as error:
            self.service.approve_and_submit(fresh['proposal_id'],fresh['proposal_digest'],self.get_queue)
        self.assertEqual(error.exception.code,'LOST_JOB');self.assertEqual(self.queue.list(),[])

    def test_concurrent_approval_does_not_create_two_jobs(self):
        from concurrent.futures import ThreadPoolExecutor
        proposal=self.proposal();queue=self.get_queue()
        def approve(_):
            return self.service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],lambda:queue)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(approve,range(2)))
        self.assertEqual(results[0]['job']['job_id'],results[1]['job']['job_id'])
        self.assertEqual(len(queue.list()),1)
        self.assertEqual(self.settled(proposal['job_id'])['status'],'completed')
