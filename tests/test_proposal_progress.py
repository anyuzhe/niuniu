"""F12 progress projections on isolated real proposal/queue fixtures, no real network/model."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_core
from test_workbench_jobs import spec as job_spec
from quantlab.agent.proposals import ProposalService
from quantlab.agent.proposal_progress import read_proposal_progress
from quantlab.storage.codec import digest, encode
from quantlab.workbench.jobs import JobQueue


def hashes(root):
    import hashlib
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


class ProposalProgressTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_core.CoreTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.output=(self.fx.root/'progress-out').resolve();self.output.mkdir()
        self.service=ProposalService(self.output,self.fx.root)
        self.spec=job_spec(symbols=list(self.fx.symbols),replay=True)
        self.proposal=self.service.propose(str(uuid4()),self.spec)
        self.queue=None;self.addCleanup(lambda:self.queue.close() if self.queue else None)

    def get_queue(self):
        if self.queue is None:self.queue=JobQueue(self.output,self.fx.root)
        return self.queue

    def completed(self):
        result=self.service.approve_and_submit(self.proposal['proposal_id'],self.proposal['proposal_digest'],self.get_queue)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            job=next(j for j in self.queue.list() if j['job_id']==result['job']['job_id'])
            if job['status'] not in ('queued','running'):
                self.assertEqual(job['status'],'completed',job);return job
            time.sleep(.02)
        self.fail('isolated queue did not finish')

    def report(self):return read_proposal_progress(self.output,self.proposal['proposal_id'])

    def write_job(self,job):
        path=self.output/'_jobs'/(self.proposal['job_id']+'.json')
        path.write_text(encode(job));return path

    def test_pending_read_does_not_create_worker_or_modify_journal(self):
        before=hashes(self.output)
        report=self.report()
        self.assertEqual(report['phase'],'awaiting_approval');self.assertFalse(report['incomplete'])
        self.assertIsNone(report['job']);self.assertEqual(report['freeze']['state'],'not_created')
        self.assertTrue(report['refresh_recommended']);self.assertEqual(before,hashes(self.output))
        self.assertFalse((self.output/'_jobs').exists())

    def test_rejected_and_unapproved_candidate_are_not_execution(self):
        folder=self.output/'_approval_input_freezes'/self.proposal['proposal_id'];folder.mkdir(parents=True)
        (folder/'manifest.json').write_text('partial')
        report=self.report();self.assertEqual(report['freeze']['state'],'unapproved_candidate')
        self.service.store.reject(self.proposal['proposal_id'],self.proposal['proposal_digest'])
        report=self.report();self.assertEqual(report['phase'],'rejected');self.assertFalse(report['refresh_recommended'])

    def test_approved_but_no_job_is_distinct_and_never_enqueued(self):
        from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
        ApprovalInputFreezeStore(self.output,self.fx.root).capture(self.proposal['proposal_id'],self.spec,self.proposal['plan']['qualification'])
        with self.service.store.transaction() as c:c.execute("UPDATE proposals SET status='approved' WHERE id=?",(self.proposal['proposal_id'],))
        before=hashes(self.output);report=self.report()
        self.assertEqual(report['phase'],'approved_not_enqueued');self.assertFalse(report['incomplete'])
        self.assertEqual(report['freeze']['state'],'manifest_checked');self.assertEqual(before,hashes(self.output))

    def test_completed_real_queue_has_same_ids_without_source_access(self):
        job=self.completed();before=hashes(self.output)
        with patch('quantlab.data.provider.local_data_provider',side_effect=AssertionError('must not read market data')):
            report=self.report()
        self.assertEqual(report['phase'],'completed');self.assertFalse(report['errors'],report)
        self.assertTrue(report['can_open_result']);self.assertEqual(report['result']['run_id'],job['run_id'])
        self.assertFalse(report['process_liveness_verified']);self.assertFalse(report['freeze']['payload_bytes_verified'])
        self.assertEqual(before,hashes(self.output))

    def test_new_process_reads_same_result_without_resuming(self):
        job=self.completed();before=hashes(self.output)
        r=subprocess.run([sys.executable,'-B','-c',
            'import json,sys;from quantlab.agent.proposal_progress import read_proposal_progress;print(json.dumps(read_proposal_progress(sys.argv[1],sys.argv[2])))',
            str(self.output),self.proposal['proposal_id']],capture_output=True,text=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stderr);report=json.loads(r.stdout)
        self.assertTrue(report['can_open_result']);self.assertEqual(report['result']['run_id'],job['run_id'])
        self.assertEqual(before,hashes(self.output))

    def test_active_cancel_and_failure_states_preserve_attempt_and_error(self):
        job=self.completed()
        for state in ('queued','running','failed','cancelled','interrupted'):
            with self.subTest(state=state):
                self.write_job({**job,'status':state,'run_id':None,'experiment_id':None,'attempt':3,
                    'error':'synthetic failure' if state=='failed' else None,
                    'progress':{'stage':'stage A','completed':2,'total':9,'updated_at':'2026-09-22T01:00:00+00:00'}})
                report=self.report();self.assertEqual(report['phase'],state,report)
                self.assertEqual(report['job']['attempt'],3);self.assertFalse(report['can_open_result'])
                self.assertEqual(report['refresh_recommended'],state in ('queued','running'))
        self.write_job({**job,'status':'running','run_id':None,'cancel_requested':True})
        self.assertEqual(self.report()['phase'],'cancel_requested')

    def test_submitted_missing_job_is_not_a_fresh_pending_task(self):
        self.completed();path=self.output/'_jobs'/(self.proposal['job_id']+'.json');path.unlink()
        report=self.report();self.assertEqual(report['phase'],'missing_job')
        self.assertEqual(report['errors'][0]['code'],'LOST_JOB');self.assertFalse(path.exists())

    def test_wrong_job_spec_and_guard_block_result_link(self):
        job=self.completed()
        for changed in ({**job,'spec':{**job['spec'],'question':'other'}},{**job,'execution_guard':None},{**job,'job_id':str(uuid4())}):
            self.write_job(changed);report=self.report()
            self.assertTrue(report['incomplete']);self.assertFalse(report['can_open_result'])
            self.assertEqual(report['errors'][0]['stage'],'job')

    def test_bad_freeze_is_disclosed_but_no_repair(self):
        self.completed();path=self.output/'_approval_input_freezes'/self.proposal['proposal_id']/'manifest.json'
        path.write_text('{}');before=hashes(self.output);report=self.report()
        self.assertTrue(report['incomplete']);self.assertFalse(report['can_open_result'])
        self.assertEqual(report['freeze']['state'],'unavailable');self.assertEqual(before,hashes(self.output))

    def test_result_missing_wrong_identity_and_failed_header_do_not_open(self):
        job=self.completed();path=self.output/job['run_id']/'experiment.json';raw=path.read_bytes()
        for changed in ({'run_id':str(uuid4()),'experiment_id':job['experiment_id'],'status':'completed'},
                        {'run_id':job['run_id'],'experiment_id':job['experiment_id'],'status':'failed'}):
            path.write_text(encode(changed));report=self.report()
            self.assertTrue(report['incomplete']);self.assertFalse(report['can_open_result'])
        path.unlink();self.assertFalse(self.report()['can_open_result']);path.write_bytes(raw)
        self.assertTrue(self.report()['can_open_result'])

    def test_duplicate_json_and_invalid_status_fail_closed(self):
        job=self.completed();path=self.write_job(job)
        path.write_text('{"status":"failed","status":"completed"}')
        self.assertEqual(self.report()['errors'][0]['stage'],'job')
        self.write_job({**job,'status':'pretend_success'})
        self.assertFalse(self.report()['can_open_result'])

    def test_result_duplicate_status_is_not_a_completed_header(self):
        job=self.completed();path=self.output/job['run_id']/'experiment.json'
        path.write_text('{"run_id":'+json.dumps(job['run_id'])+',"experiment_id":'+json.dumps(job['experiment_id'])+',"status":"failed","status":"completed"}')
        report=self.report();self.assertTrue(report['incomplete']);self.assertFalse(report['can_open_result'])

    def test_proposal_duplicate_question_is_not_accepted_by_checksum_alone(self):
        payload=encode(self.proposal['plan'])
        question=json.dumps(self.spec['question'],ensure_ascii=False)
        needle='"question": '+question
        self.assertIn(needle,payload)
        payload=payload.replace(needle,'"question": "other", '+needle,1)
        with self.service.store.transaction() as c:
            c.execute('UPDATE proposals SET payload=? WHERE id=?',(payload,self.proposal['proposal_id']))
        report=self.report();self.assertTrue(report['incomplete']);self.assertIsNone(report['proposal'])

    def test_changed_job_during_observation_invalidates_result(self):
        job=self.completed()
        from quantlab.agent import proposal_progress as module
        original=module._json;count=[0]
        def changing(path,*args):
            if Path(path).parent.name=='_jobs':
                count[0]+=1
                if count[0]==2:self.write_job({**job,'status':'running','run_id':None})
            return original(path,*args)
        with patch.object(module,'_json',side_effect=changing):report=self.report()
        self.assertFalse(report['can_open_result'])
        self.assertIn('CHANGED_DURING_READ',{e['code'] for e in report['errors']})

    def test_freeze_change_after_header_read_is_not_a_current_success(self):
        self.completed()
        from quantlab.agent import proposal_progress as module
        original=module._proposal;calls=[0]
        def changing(*args):
            calls[0]+=1
            if calls[0]==2:
                (self.output/'_approval_input_freezes'/self.proposal['proposal_id']/'manifest.json').write_text('{}')
            return original(*args)
        with patch.object(module,'_proposal',side_effect=changing):report=self.report()
        self.assertTrue(report['incomplete']);self.assertFalse(report['can_open_result'])

    def test_invalid_id_missing_root_and_symlink_never_create_state(self):
        with self.assertRaises(ValueError):read_proposal_progress(self.output,'../bad')
        missing=self.fx.root/'missing'
        with self.assertRaises(ValueError):read_proposal_progress(missing,self.proposal['proposal_id'])
        self.assertFalse(missing.exists())
        link=self.fx.root/'alias';link.symlink_to(self.output,target_is_directory=True)
        with self.assertRaises(ValueError):read_proposal_progress(link,self.proposal['proposal_id'])
        job=self.completed();folder=self.output/'_jobs';folder.rename(self.output/'saved-jobs')
        folder.symlink_to(self.output/'saved-jobs',target_is_directory=True)
        self.assertTrue(self.report()['incomplete'])

    def test_model_tool_keeps_errors_and_no_new_mutation_permissions(self):
        from quantlab.agent.chat_runtime import ChatRuntime
        from quantlab.agent.mcp_server import build_mcp_api
        for api in (ChatRuntime(self.output,self.fx.root).api,build_mcp_api(self.output,self.fx.root)):
            names=[s['name'] for s in api.schemas()];self.assertEqual(len(names),len(set(names)))
            self.assertIn('get_proposal_progress',names)
            value=api.call('get_proposal_progress',{'proposal_id':self.proposal['proposal_id']})
            self.assertTrue(value['ok'],value);self.assertEqual(value['data']['phase'],'awaiting_approval')
            for name in ('approve_proposal','resume_job','cancel_job'):self.assertNotIn(name,names)

    def test_locked_spec_and_first_reviewer_do_not_gain_progress_tool(self):
        from test_research_spec_fidelity import synthetic_pair
        from quantlab.agent.research_specs import ResearchSpecStore
        from quantlab.agent.research_spec_tools import ResearchSpecAPI
        from quantlab.agent.peer_review import ReviewReadOnlyAPI
        from quantlab.agent.catalog import ReadOnlyResearchAPI
        md,js=synthetic_pair(self.fx.root)
        sid=ResearchSpecStore(self.output).import_pair(md,js,confirmed=True)['spec_id']
        locked=ResearchSpecAPI(ReadOnlyResearchAPI(self.output),self.output,self.fx.root,active_spec=sid)
        self.assertNotIn('get_proposal_progress',{t['name'] for t in locked.schemas()})
        self.assertEqual(locked.call('get_proposal_progress',{'proposal_id':self.proposal['proposal_id']})['error']['code'],'SPEC_SUBSTITUTION_REJECTED')
        reviewer=ReviewReadOnlyAPI(self.output,self.fx.root)
        self.assertNotIn('get_proposal_progress',{t['name'] for t in reviewer.schemas()})

    def test_missing_proposal_has_no_fabricated_evidence(self):
        from quantlab.agent.catalog import ReadOnlyResearchAPI
        result=ReadOnlyResearchAPI(self.output).call('get_proposal_progress',{'proposal_id':str(uuid4())})
        self.assertTrue(result['ok']);self.assertTrue(result['data']['incomplete']);self.assertEqual(result['evidence'],[])

    def test_large_model_report_is_explicitly_rejected_not_trimmed(self):
        from quantlab.agent.catalog import ReadOnlyResearchAPI
        plan={**self.proposal['plan'],'spec':{**self.spec,'question':'x'*26000}}
        with self.service.store.transaction() as c:
            c.execute('UPDATE proposals SET payload=?,checksum=? WHERE id=?',(encode(plan),digest(plan),self.proposal['proposal_id']))
        result=ReadOnlyResearchAPI(self.output).call('get_proposal_progress',{'proposal_id':self.proposal['proposal_id']})
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'RESULT_TOO_LARGE')

    def test_real_mcp_stdio_returns_readonly_progress(self):
        from mcp import Client,StdioServerParameters
        from quantlab.agent.mcp_server import build_mcp_server
        async def check():
            params=StdioServerParameters(command=sys.executable,args=['-B','-m','quantlab.agent.mcp_server','--output',str(self.output),'--data-root',str(self.fx.root)],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            for server in (build_mcp_server(self.output,self.fx.root),params):
                async with Client(server,read_timeout_seconds=35) as client:
                    tools=(await client.list_tools()).tools
                    tool=next(t for t in tools if t.name=='get_proposal_progress');self.assertTrue(tool.annotations.read_only_hint)
                    response=await client.call_tool('get_proposal_progress',{'proposal_id':self.proposal['proposal_id']})
                    data=json.loads(response.content[0].text)
                    self.assertTrue(data['ok'],data);self.assertEqual(data['data']['phase'],'awaiting_approval')
        asyncio.run(check())


if __name__=='__main__':unittest.main()
