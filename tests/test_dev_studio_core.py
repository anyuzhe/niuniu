import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from quantlab.devstudio.service import DevStudioError,DevStudioService


def cmd(*args,cwd):
    result=subprocess.run(list(args),cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if result.returncode:raise RuntimeError(result.stderr)
    return result.stdout.strip()


class DevStudioCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        (self.repo/'.gitignore').write_text('artifacts/\n.venv/\n__pycache__/\n')
        (self.repo/'src').mkdir();(self.repo/'src/app.py').write_text('VALUE = 1\n')
        (self.repo/'文档').mkdir();(self.repo/'文档/说明.md').write_text('初始\n')
        (self.repo/'tests').mkdir();(self.repo/'tests/__init__.py').write_text('')
        (self.repo/'tests/test_sample.py').write_text('import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n')
        cmd('git','init','-b','main',cwd=self.repo);cmd('git','config','user.email','test@example.invalid',cwd=self.repo);cmd('git','config','user.name','Test User',cwd=self.repo)
        cmd('git','add','.',cwd=self.repo);cmd('git','commit','-m','base',cwd=self.repo)
        bindir=self.repo/'.venv/bin';bindir.mkdir(parents=True);os.symlink(sys.executable,bindir/'python')
        self.output=self.repo/'artifacts';self.output.mkdir();self.service=DevStudioService(self.output,self.repo)
        self.spec={'title':'change value','request':'change VALUE safely','acceptance_criteria':['VALUE becomes 2'],
            'allowed_paths':['src/app.py'],'test_commands':[['python','-m','unittest','tests.test_sample']],
            'max_parallel_subagents':3,'notes':''}
        self.tasks=[]
    def tearDown(self):
        # Remove any live worktrees before temp directory cleanup.
        for task_id in self.tasks:
            try:self.service.cleanup(task_id,force=True)
            except Exception:pass
        self.temp.cleanup()

    def task(self):
        task=self.service.create_task(self.spec);self.tasks.append(task['task_id']);return task



    def test_parallel_budget_and_disjoint_writer_leases(self):
        spec={**self.spec,'allowed_paths':['src/app.py','文档/说明.md'],'test_commands':[],'max_parallel_subagents':3}
        task=self.service.create_task(spec);self.tasks.append(task['task_id']);tid=task['task_id']
        a=self.service.add_subtask(tid,{'role':'IMPLEMENTER','title':'a','instruction':'a','depends_on':[],
            'lease_paths':['src/app.py'],'acceptance_criteria':[],'model':'','effort':''})
        b=self.service.add_subtask(tid,{'role':'IMPLEMENTER','title':'b','instruction':'b','depends_on':[],
            'lease_paths':['文档/说明.md'],'acceptance_criteria':[],'model':'','effort':''})
        c=self.service.add_subtask(tid,{'role':'EXPLORER','title':'c','instruction':'c','depends_on':[],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        d=self.service.add_subtask(tid,{'role':'EXPLORER','title':'d','instruction':'d','depends_on':[],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        self.service.start_subtask(tid,a['subtask_id']);self.service.start_subtask(tid,b['subtask_id']);self.service.start_subtask(tid,c['subtask_id'])
        with self.assertRaises(DevStudioError) as budget:self.service.start_subtask(tid,d['subtask_id'])
        self.assertEqual(budget.exception.code,'PARALLEL_BUDGET')

    def test_unicode_git_paths_are_preserved_exactly(self):
        spec={**self.spec,'allowed_paths':['文档/说明.md'],'test_commands':[]}
        task=self.service.create_task(spec);self.tasks.append(task['task_id']);tid=task['task_id']
        impl=self.service.add_subtask(tid,{'role':'IMPLEMENTER','title':'中文文档','instruction':'更新说明','depends_on':[],
            'lease_paths':['文档/说明.md'],'acceptance_criteria':[],'model':'','effort':''})
        self.service.start_subtask(tid,impl['subtask_id']);before=self.service.read_file(tid,impl['subtask_id'],'文档/说明.md')
        self.service.write_file(tid,impl['subtask_id'],'文档/说明.md','更新后\n',before['sha256'])
        self.service.finish_subtask(tid,impl['subtask_id'],{'summary':'updated','changed_files':['文档/说明.md'],'tests':[],
            'evidence':[],'verdict':'PASS','stop_reason':''})
        audit=self.service.audit_changes(tid);self.assertTrue(audit['ok']);self.assertEqual(audit['changed_files'],['文档/说明.md'])

    def test_worktree_isolated_and_path_leases_fail_closed(self):
        task=self.task();self.assertEqual(task['state'],'DRAFT');self.assertEqual((self.repo/'src/app.py').read_text(),'VALUE = 1\n')
        impl=self.service.add_subtask(task['task_id'],{'role':'IMPLEMENTER','title':'edit','instruction':'edit app',
            'depends_on':[],'lease_paths':['src/app.py'],'acceptance_criteria':['value 2'],'model':'','effort':''})
        with self.assertRaises(DevStudioError) as conflict:
            self.service.add_subtask(task['task_id'],{'role':'IMPLEMENTER','title':'other','instruction':'other edit',
                'depends_on':[],'lease_paths':['src/app.py'],'acceptance_criteria':[],'model':'','effort':''})
        self.assertEqual(conflict.exception.code,'LEASE_CONFLICT')
        with self.assertRaises(DevStudioError):
            self.service.add_subtask(task['task_id'],{'role':'EXPLORER','title':'bad','instruction':'read',
                'depends_on':[],'lease_paths':['src/app.py'],'acceptance_criteria':[],'model':'','effort':''})
        self.service.start_subtask(task['task_id'],impl['subtask_id'])
        before=self.service.read_file(task['task_id'],impl['subtask_id'],'src/app.py')
        self.service.write_file(task['task_id'],impl['subtask_id'],'src/app.py','VALUE = 2\n',before['sha256'])
        with self.assertRaises(DevStudioError) as lease:
            self.service.write_file(task['task_id'],impl['subtask_id'],'tests/test_sample.py','bad\n')
        self.assertEqual(lease.exception.code,'LEASE_VIOLATION')
        self.assertEqual((self.repo/'src/app.py').read_text(),'VALUE = 1\n')
        self.assertEqual(Path(task['worktree_path'],'src/app.py').read_text(),'VALUE = 2\n')

    def test_test_review_accept_and_human_merge(self):
        task=self.task();tid=task['task_id']
        impl=self.service.add_subtask(tid,{'role':'IMPLEMENTER','title':'edit','instruction':'edit',
            'depends_on':[],'lease_paths':['src/app.py'],'acceptance_criteria':['value 2'],'model':'','effort':''})
        tester=self.service.add_subtask(tid,{'role':'TESTER','title':'test','instruction':'run frozen test',
            'depends_on':[impl['subtask_id']],'lease_paths':[],'acceptance_criteria':['tests pass'],'model':'','effort':''})
        reviewer=self.service.add_subtask(tid,{'role':'REVIEWER','title':'review','instruction':'review diff',
            'depends_on':[tester['subtask_id']],'lease_paths':[],'acceptance_criteria':['scope safe'],'model':'','effort':''})
        self.service.start_subtask(tid,impl['subtask_id']);before=self.service.read_file(tid,impl['subtask_id'],'src/app.py')
        self.service.write_file(tid,impl['subtask_id'],'src/app.py','VALUE = 2\n',before['sha256'])
        self.service.finish_subtask(tid,impl['subtask_id'],{'summary':'edited','changed_files':['src/app.py'],'tests':[],
            'evidence':['lease respected'],'verdict':'PASS','stop_reason':''})
        self.service.start_subtask(tid,tester['subtask_id'])
        evidence=self.service.run_test(tid,tester['subtask_id'],['python','-m','unittest','tests.test_sample'])
        self.assertTrue(evidence['passed'])
        with self.assertRaises(DevStudioError) as write:
            self.service.write_file(tid,tester['subtask_id'],'src/app.py','VALUE = 3\n')
        self.assertEqual(write.exception.code,'WRITE_FORBIDDEN')
        self.service.finish_subtask(tid,tester['subtask_id'],{'summary':'test passed','changed_files':[],
            'tests':[evidence],'evidence':['unittest'],'verdict':'PASS','stop_reason':''})
        self.service.start_subtask(tid,reviewer['subtask_id'])
        diff=self.service.diff(tid,reviewer['subtask_id']);self.assertIn('VALUE = 2',diff['patch'])
        self.service.finish_subtask(tid,reviewer['subtask_id'],{'summary':'independent review passed','changed_files':[],
            'tests':[],'evidence':['diff reviewed'],'verdict':'PASS','stop_reason':''})
        ready=self.service.accept(tid,'ACCEPT','criteria met');self.assertEqual(ready['state'],'READY_FOR_HUMAN')
        with self.assertRaises(DevStudioError) as confirmation:self.service.human_merge(tid,'feat: test merge')
        self.assertEqual(confirmation.exception.code,'CONFIRMATION_REQUIRED')
        merged=self.service.human_merge(tid,'feat: test merge',confirmed=True)
        self.assertEqual(merged['state'],'MERGED');self.assertEqual((self.repo/'src/app.py').read_text(),'VALUE = 2\n')
        self.assertEqual(cmd('git','log','-1','--pretty=%s',cwd=self.repo),'feat: test merge')
        self.assertFalse(merged['merge']['pushed'])

    def test_accept_rechecks_actual_diff_not_subtask_claim(self):
        task=self.task();tid=task['task_id']
        impl=self.service.add_subtask(tid,{'role':'IMPLEMENTER','title':'edit','instruction':'edit',
            'depends_on':[],'lease_paths':['src/app.py'],'acceptance_criteria':[],'model':'','effort':''})
        reviewer=self.service.add_subtask(tid,{'role':'REVIEWER','title':'review','instruction':'review',
            'depends_on':[impl['subtask_id']],'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        self.service.start_subtask(tid,impl['subtask_id']);self.service.write_file(tid,impl['subtask_id'],'src/app.py','VALUE = 2\n')
        self.service.finish_subtask(tid,impl['subtask_id'],{'summary':'done','changed_files':['src/app.py'],'tests':[],
            'evidence':[],'verdict':'PASS','stop_reason':''})
        # Simulate an out-of-band mutation inside isolated worktree.
        Path(task['worktree_path'],'tests/test_sample.py').write_text('BROKEN = True\n')
        self.service.start_subtask(tid,reviewer['subtask_id']);self.service.finish_subtask(tid,reviewer['subtask_id'],
            {'summary':'claimed pass','changed_files':[],'tests':[],'evidence':[],'verdict':'PASS','stop_reason':''})
        with self.assertRaises(DevStudioError) as scope:self.service.accept(tid,'ACCEPT','claimed complete')
        self.assertEqual(scope.exception.code,'FINAL_DIFF_SCOPE')

    def test_main_head_move_blocks_human_merge(self):
        task=self.task();tid=task['task_id']
        impl=self.service.add_subtask(tid,{'role':'IMPLEMENTER','title':'edit','instruction':'edit','depends_on':[],
            'lease_paths':['src/app.py'],'acceptance_criteria':[],'model':'','effort':''})
        reviewer=self.service.add_subtask(tid,{'role':'REVIEWER','title':'review','instruction':'review','depends_on':[impl['subtask_id']],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        self.service.start_subtask(tid,impl['subtask_id']);self.service.write_file(tid,impl['subtask_id'],'src/app.py','VALUE = 2\n')
        self.service.finish_subtask(tid,impl['subtask_id'],{'summary':'done','changed_files':['src/app.py'],'tests':[],
            'evidence':[],'verdict':'PASS','stop_reason':''})
        self.service.start_subtask(tid,reviewer['subtask_id']);self.service.finish_subtask(tid,reviewer['subtask_id'],
            {'summary':'pass','changed_files':[],'tests':[],'evidence':[],'verdict':'PASS','stop_reason':''})
        # No frozen test commands for this variant.
        state=self.service.get(tid);state['spec']['test_commands']=[]
        with self.service.store.locked(tid):self.service.store._save(state)
        self.service.accept(tid,'ACCEPT','ready')
        (self.repo/'README.md').write_text('main moved\n');cmd('git','add','README.md',cwd=self.repo);cmd('git','commit','-m','concurrent main',cwd=self.repo)
        with self.assertRaises(DevStudioError) as moved:self.service.human_merge(tid,'feat: should not merge',confirmed=True)
        self.assertEqual(moved.exception.code,'MAIN_MOVED')


    def test_reviewer_pass_becomes_stale_after_final_diff_changes(self):
        task=self.task();tid=task['task_id']
        impl=self.service.add_subtask(tid,{'role':'IMPLEMENTER','title':'edit','instruction':'edit','depends_on':[],
            'lease_paths':['src/app.py'],'acceptance_criteria':[],'model':'','effort':''})
        tester=self.service.add_subtask(tid,{'role':'TESTER','title':'test','instruction':'test','depends_on':[impl['subtask_id']],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        reviewer=self.service.add_subtask(tid,{'role':'REVIEWER','title':'review','instruction':'review','depends_on':[tester['subtask_id']],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        self.service.start_subtask(tid,impl['subtask_id']);self.service.write_file(tid,impl['subtask_id'],'src/app.py','VALUE = 2\n')
        self.service.finish_subtask(tid,impl['subtask_id'],{'summary':'done','changed_files':['src/app.py'],'tests':[],'evidence':[],'verdict':'PASS','stop_reason':''})
        self.service.start_subtask(tid,tester['subtask_id']);ev=self.service.run_test(tid,tester['subtask_id'],['python','-m','unittest','tests.test_sample'])
        self.service.finish_subtask(tid,tester['subtask_id'],{'summary':'tested','changed_files':[],'tests':[ev],'evidence':[],'verdict':'PASS','stop_reason':''})
        self.service.start_subtask(tid,reviewer['subtask_id']);self.service.finish_subtask(tid,reviewer['subtask_id'],
            {'summary':'pass','changed_files':[],'tests':[],'evidence':[],'verdict':'PASS','stop_reason':''})
        Path(task['worktree_path'],'src/app.py').write_text('VALUE = 3\n')
        with self.assertRaises(DevStudioError) as stale:self.service.accept(tid,'ACCEPT','should fail')
        self.assertEqual(stale.exception.code,'STALE_REVIEW')

    def test_test_pass_becomes_stale_after_final_diff_changes(self):
        task=self.task();tid=task['task_id']
        impl=self.service.add_subtask(tid,{'role':'IMPLEMENTER','title':'edit','instruction':'edit','depends_on':[],
            'lease_paths':['src/app.py'],'acceptance_criteria':[],'model':'','effort':''})
        tester=self.service.add_subtask(tid,{'role':'TESTER','title':'test','instruction':'test','depends_on':[impl['subtask_id']],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        reviewer=self.service.add_subtask(tid,{'role':'REVIEWER','title':'review','instruction':'review','depends_on':[tester['subtask_id']],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        self.service.start_subtask(tid,impl['subtask_id']);self.service.write_file(tid,impl['subtask_id'],'src/app.py','VALUE = 2\n')
        self.service.finish_subtask(tid,impl['subtask_id'],{'summary':'done','changed_files':['src/app.py'],'tests':[],'evidence':[],'verdict':'PASS','stop_reason':''})
        self.service.start_subtask(tid,tester['subtask_id']);ev=self.service.run_test(tid,tester['subtask_id'],['python','-m','unittest','tests.test_sample'])
        self.service.finish_subtask(tid,tester['subtask_id'],{'summary':'tested','changed_files':[],'tests':[ev],'evidence':[],'verdict':'PASS','stop_reason':''})
        Path(task['worktree_path'],'src/app.py').write_text('VALUE = 3\n')
        self.service.start_subtask(tid,reviewer['subtask_id']);self.service.finish_subtask(tid,reviewer['subtask_id'],
            {'summary':'pass current diff','changed_files':[],'tests':[],'evidence':[],'verdict':'PASS','stop_reason':''})
        with self.assertRaises(DevStudioError) as stale:self.service.accept(tid,'ACCEPT','should fail')
        self.assertEqual(stale.exception.code,'STALE_TESTS')


if __name__=='__main__':unittest.main()
