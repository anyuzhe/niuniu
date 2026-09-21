"""Persist immediate-parent provenance through real proposal, queue, and archive paths."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_core
from test_strategy_package import package
from quantlab.agent.planning import ProposalError
from quantlab.agent.proposals import ProposalService
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.storage.bundle import reproduce_artifact
from quantlab.storage.codec import digest, encode
from quantlab.trading.strategy_package import compile_strategy, strategy_content_hash, validate_revision_source
from quantlab.trading.strategy_run_catalog import (get_strategy_run, make_strategy_revision_source,
    verify_strategy_revision_source)
from quantlab.workbench.jobs import JobQueue, execute, prepare


class StrategyRevisionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.CoreTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.output = self.fixture.root / 'lineage'; self.output.mkdir()
        self.parent = execute(prepare(compile_strategy(package())['spec']), self.fixture.root, self.output)
        detail = get_strategy_run(self.output, self.parent.run_id)
        self.source = make_strategy_revision_source(detail)
        self.revised = deepcopy(detail['package'])
        self.revised['revision_source'] = deepcopy(self.source)
        self.revised['version'] = 'draft-2'
        self.revised['spec']['portfolio']['max_position'] = 0.5

    def test_old_package_output_unchanged_and_reference_is_part_of_identity(self):
        old = compile_strategy(package())
        self.assertEqual(set(old['package']), {'format','strategy_key','name','version','lifecycle','spec'})
        self.assertEqual(old['compiled_spec_hash'], strategy_content_hash(old['spec']['strategy_package']))
        without = deepcopy(self.revised); without.pop('revision_source')
        linked = compile_strategy(self.revised); plain = compile_strategy(without)
        self.assertNotEqual(linked['package_hash'], plain['package_hash'])
        self.assertNotEqual(linked['compiled_spec_hash'], plain['compiled_spec_hash'])
        self.assertEqual(strategy_content_hash(linked['spec']['strategy_package']), plain['compiled_spec_hash'])
        self.assertEqual(compile_strategy(json.loads(encode(linked['package']))), linked)

    def test_reference_schema_and_same_version_change_fail_closed(self):
        for key,value in [('parent_run_id','../x'), ('parent_content_hash','A'*64),
                          ('parent_version','latest'), ('parent_strategy_key','')]:
            bad=deepcopy(self.source);bad[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_revision_source(bad)
        bad=deepcopy(self.source);bad['approved']=True
        with self.assertRaises(ValueError): validate_revision_source(bad)
        for bad in (None, [], {'format':'x'}):
            with self.subTest(bad=bad),self.assertRaises(ValueError): validate_revision_source(bad)
        same=deepcopy(self.revised);same['version']=self.source['parent_version']
        with self.assertRaisesRegex(ValueError,'版本'): compile_strategy(same)
        unchanged=package();unchanged['revision_source']=deepcopy(self.source)
        self.assertTrue(compile_strategy(unchanged))

    def test_forged_well_formed_reference_is_rejected_without_proposal_or_queue(self):
        for key in ('parent_package_hash','parent_compiled_spec_hash','parent_content_hash','parent_evidence_hash'):
            bad=deepcopy(self.revised);bad['revision_source'][key]='0'*64
            # Syntactic validity is not evidence authentication.
            spec=compile_strategy(bad)['spec']
            with self.subTest(key=key),self.assertRaisesRegex(ProposalError,'父来源'):
                ProposalService(self.output,self.fixture.root).propose(str(uuid4()),spec)
        self.assertFalse((self.output/'_jobs').exists())
        self.assertFalse((self.output/'_agent'/'proposals.sqlite3').exists())

    def test_proposal_new_process_roundtrip_preserves_link_and_pending_authority(self):
        spec=compile_strategy(self.revised)['spec']
        svc=ProposalService(self.output,self.fixture.root);request=str(uuid4())
        proposal=svc.propose(request,spec)
        self.assertEqual(proposal,svc.propose(request,spec))
        script=('import json,sys;from quantlab.agent.proposals import ProposalService;'
                'v=ProposalService(sys.argv[1],sys.argv[2]).get(sys.argv[3]);'
                'print(json.dumps(v,ensure_ascii=False))')
        child=subprocess.run([sys.executable,'-B','-c',script,str(self.output),str(self.fixture.root),proposal['proposal_id']],
                             capture_output=True,text=True,timeout=45)
        self.assertEqual(child.returncode,0,child.stderr)
        reopened=json.loads(child.stdout)
        self.assertEqual(reopened['proposal_digest'],proposal['proposal_digest'])
        self.assertEqual(reopened['plan']['spec']['strategy_package']['package']['revision_source'],self.source)
        self.assertEqual(reopened['plan']['strategy_revision_sources'][0]['status'],'verified')
        self.assertEqual(reopened['status'],'pending');self.assertIsNone(reopened['approved_at'])
        self.assertFalse((self.output/'_jobs').exists())

    def test_parent_changes_after_proposal_blocks_approval_without_starting_queue(self):
        svc=ProposalService(self.output,self.fixture.root)
        proposal=svc.propose(str(uuid4()),compile_strategy(self.revised)['spec'])
        (self.parent.artifact_path/'bars.parquet').write_bytes(b'broken parent')
        with patch.object(svc,'_current', wraps=svc._current), patch('quantlab.workbench.jobs.JobQueue') as queue:
            with self.assertRaises(ProposalError):
                svc.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],queue)
            queue.assert_not_called()
        self.assertEqual(svc.store.get(proposal['proposal_id'])['status'],'pending')
        self.assertFalse((self.output/'_jobs').exists())

    def test_parent_change_during_input_freeze_does_not_become_approved(self):
        from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
        svc=ProposalService(self.output,self.fixture.root)
        proposal=svc.propose(str(uuid4()),compile_strategy(self.revised)['spec'])
        capture=ApprovalInputFreezeStore.capture
        old_report=(self.parent.artifact_path/'report.md').read_bytes()
        def capture_then_change(store,*args,**kwargs):
            result=capture(store,*args,**kwargs)
            (self.parent.artifact_path/'report.md').write_text('changed after freeze',encoding='utf-8')
            return result
        with patch.object(ApprovalInputFreezeStore,'capture',capture_then_change),patch('quantlab.workbench.jobs.JobQueue') as queue:
            with self.assertRaises(ProposalError):
                svc.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],queue)
            queue.assert_not_called()
        self.assertEqual(svc.store.get(proposal['proposal_id'])['status'],'pending')
        self.assertFalse((self.output/'_jobs').exists())

        unapproved=svc.get(proposal['proposal_id'])
        self.assertNotIn('approval_freeze',unapproved)
        self.assertEqual(unapproved['unapproved_input_freeze']['status'],'not_approved')
        self.assertFalse(unapproved['unapproved_input_freeze']['execution_authorized'])
        # Even when the parent is repaired exactly, no silent adoption of old frozen inputs.
        (self.parent.artifact_path/'report.md').write_bytes(old_report)
        with patch('quantlab.workbench.jobs.JobQueue') as queue:
            with self.assertRaises(ProposalError) as failure:
                svc.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],queue)
            self.assertEqual(failure.exception.code,'UNAPPROVED_FREEZE_REQUIRES_NEW_PROPOSAL')
            queue.assert_not_called()
        self.assertEqual(svc.store.get(proposal['proposal_id'])['status'],'pending')

    def test_cli_verifies_saved_source_but_pure_preview_and_model_read_do_not_claim_authentication(self):
        import contextlib
        import io
        from quantlab.agent.catalog import ReadOnlyResearchAPI
        from quantlab.agent.strategy_package_cli import main
        api=ReadOnlyResearchAPI(self.output)
        contract=api.call('get_strategy_package_contract',{})
        self.assertIn('revision_source',contract['data']['optional'])
        preview=api.call('preview_strategy_package',{'package_json':encode(self.revised)})
        self.assertTrue(preview['ok'],preview)
        self.assertEqual(preview['data']['revision_source_verification'],'not_checked')
        self.assertFalse(preview['data']['execution_authorized'])
        target=self.output/'saved.json';target.write_text(encode(self.revised))
        before=snapshot_tree(self.output,self.parent.run_id)
        def cli():
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):
                code=main(['verify-revision-source','--package',str(target),'--output',str(self.output)])
            return code,json.loads(stream.getvalue())
        code,result=cli();self.assertEqual(code,0,result)
        self.assertEqual(result['data']['status'],'verified')
        self.assertEqual(before,snapshot_tree(self.output,self.parent.run_id))
        (self.parent.artifact_path/'report.md').write_text('changed')
        code,result=cli();self.assertEqual(code,2);self.assertFalse(result['ok'])
        target.write_text(encode(package()))
        code,result=cli();self.assertEqual(code,2);self.assertFalse(result['ok'])
        self.assertFalse((self.output/'_jobs').exists())
        self.assertFalse((self.output/'_agent'/'proposals.sqlite3').exists())

    def test_real_approved_execution_and_reproduction_preserve_source_without_inheriting_parent(self):
        before=snapshot_tree(self.output,self.parent.run_id)
        svc=ProposalService(self.output,self.fixture.root)
        proposal=svc.propose(str(uuid4()),compile_strategy(self.revised)['spec'])
        queue=JobQueue(self.output,self.fixture.root)
        try:
            submitted=svc.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],lambda:queue)
            job_id=submitted['job']['job_id'];deadline=time.monotonic()+40
            while True:
                job=next(j for j in queue.list() if j['job_id']==job_id)
                if job['status'] not in ('running','queued'):break
                if time.monotonic()>deadline:self.fail('queue did not finish: '+encode(job))
                time.sleep(.05)
            self.assertEqual(job['status'],'completed',job)
            self.assertNotEqual(job['run_id'],self.parent.run_id)
        finally:queue.close()
        detail=get_strategy_run(self.output,job['run_id'])
        self.assertEqual(detail['package']['revision_source'],self.source)
        self.assertEqual(detail['revision_source_verification'],'not_checked')
        self.assertEqual(verify_strategy_revision_source(self.output,self.source)['status'],'verified')
        self.assertEqual(before,snapshot_tree(self.output,self.parent.run_id))
        self.assertTrue((self.output/'_approval_input_freezes'/proposal['proposal_id']).is_dir())
        # Frozen child arithmetic remains self-contained: no recursive ancestor is a data input.
        with tempfile.TemporaryDirectory() as rerun:
            with patch('quantlab.trading.strategy_run_catalog.verify_strategy_revision_source',side_effect=AssertionError('no ancestor lookup during numerical reproduction')):
                result=reproduce_artifact(self.output/job['run_id'],rerun)
            self.assertEqual(result['status'],'numerically_matched')
            saved=json.loads((Path(rerun)/result['run_id']/'experiment.json').read_text())
            self.assertEqual(saved['manifest']['strategy_package']['package']['revision_source'],self.source)


if __name__=='__main__':unittest.main()
