import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from quantlab.agent.model_config import ModelConfig
from quantlab.devstudio.runtime import DevAgentRuntime,DevRuntimeError
from quantlab.devstudio.service import DevStudioService


def cmd(*args,cwd):
    r=subprocess.run(list(args),cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if r.returncode:raise RuntimeError(r.stderr)
    return r.stdout.strip()


class ScriptedProvider:
    calls=[]
    def __init__(self,config):self.config=config
    def run(self,system,messages,tools,dispatch,emit,stop):
        names={t['name'] for t in tools};ScriptedProvider.calls.append((system,names,self.config.model,self.config.effort))
        status=dispatch('dev_task_status',{},'status')['data']
        if 'Niuniu Main Developer Agent' in system:
            if not status['subtasks']:
                impl=dispatch('dev_create_subtask',{'role':'IMPLEMENTER','title':'implement','instruction':'change VALUE to 2',
                    'depends_on':[],'lease_paths':['src/app.py'],'acceptance_criteria':['VALUE=2'],'effort':'high'},'1')['data']
                tester=dispatch('dev_create_subtask',{'role':'TESTER','title':'test','instruction':'run frozen test',
                    'depends_on':[impl['subtask_id']],'lease_paths':[],'acceptance_criteria':['test passes'],'effort':''},'2')['data']
                dispatch('dev_create_subtask',{'role':'REVIEWER','title':'review','instruction':'review exact diff and tests',
                    'depends_on':[tester['subtask_id']],'lease_paths':[],'acceptance_criteria':['scope correct'],'effort':''},'3')
            else:
                dispatch('dev_accept_task',{'verdict':'ACCEPT','summary':'all frozen criteria and tests pass','evidence':['reviewer pass','frozen test pass']},'4')
            return {'text':'main done','model':'fake','provider':'fake','tool_calls':4,'usage':{}}
        if 'IMPLEMENTER' in system:
            self.assert_tools(names,{'dev_write_file'},forbidden={'dev_run_frozen_test','dev_create_subtask','dev_accept_task'})
            read=dispatch('dev_read_file',{'path':'src/app.py'},'r')['data']
            dispatch('dev_write_file',{'path':'src/app.py','text':'VALUE = 2\n','expected_sha256':read['sha256']},'w')
            dispatch('dev_submit_result',{'summary':'changed value','verdict':'PASS','evidence':['src/app.py'],'stop_reason':''},'s')
        elif 'read-only TESTER' in system:
            self.assert_tools(names,{'dev_run_frozen_test'},forbidden={'dev_write_file','dev_create_subtask'})
            result=dispatch('dev_run_frozen_test',{'command_index':0},'t')['data']
            dispatch('dev_submit_result',{'summary':'frozen test '+('passed' if result['passed'] else 'failed'),
                'verdict':'PASS' if result['passed'] else 'FAIL','evidence':['frozen test index 0'],'stop_reason':''},'s')
        elif 'independent read-only Reviewer' in system:
            self.assert_tools(names,set(),forbidden={'dev_write_file','dev_run_frozen_test','dev_create_subtask'})
            diff=dispatch('dev_diff',{},'d')['data']
            verdict='PASS' if 'VALUE = 2' in diff['patch'] else 'NEEDS_CHANGES'
            dispatch('dev_submit_result',{'summary':'review '+verdict,'verdict':verdict,'evidence':['actual diff'],'stop_reason':''},'s')
        else:raise AssertionError(system)
        return {'text':'subtask done','model':'fake','provider':'fake','tool_calls':3,'usage':{}}
    @staticmethod
    def assert_tools(names,required,forbidden):
        assert required<=names
        assert not (forbidden & names)


class NoResultProvider:
    def __init__(self,config):pass
    def run(self,system,messages,tools,dispatch,emit,stop):return {'text':'forgot tool','model':'fake','provider':'fake','tool_calls':0,'usage':{}}


class DevStudioRuntimeTests(unittest.TestCase):
    def setUp(self):
        ScriptedProvider.calls=[];self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        (self.repo/'.gitignore').write_text('artifacts/\n.venv/\n__pycache__/\n')
        (self.repo/'src').mkdir();(self.repo/'src/app.py').write_text('VALUE = 1\n')
        (self.repo/'tests').mkdir();(self.repo/'tests/__init__.py').write_text('')
        (self.repo/'tests/test_sample.py').write_text('import unittest\nfrom src.app import VALUE\nclass T(unittest.TestCase):\n    def test_value(self): self.assertEqual(VALUE,2)\n')
        cmd('git','init','-b','main',cwd=self.repo);cmd('git','config','user.email','test@example.invalid',cwd=self.repo);cmd('git','config','user.name','Test User',cwd=self.repo)
        cmd('git','add','.',cwd=self.repo);cmd('git','commit','-m','base',cwd=self.repo)
        bindir=self.repo/'.venv/bin';bindir.mkdir(parents=True);os.symlink(sys.executable,bindir/'python')
        self.output=self.repo/'artifacts';self.output.mkdir();self.service=DevStudioService(self.output,self.repo);self.tasks=[]
        self.task=self.service.create_task({'title':'runtime','request':'change value','acceptance_criteria':['VALUE becomes 2'],
            'allowed_paths':['src/app.py'],'test_commands':[['python','-m','unittest','tests.test_sample']],
            'max_parallel_subagents':3,'notes':''});self.tasks.append(self.task['task_id'])
        self.config=ModelConfig(model='main-model',effort='medium')
    def tearDown(self):
        for tid in self.tasks:
            try:self.service.cleanup(tid,force=True)
            except Exception:pass
        self.temp.cleanup()

    def test_full_dynamic_cycle_stops_at_human_gate(self):
        runtime=DevAgentRuntime(self.service,self.config,ScriptedProvider)
        final=runtime.run_cycle(self.task['task_id'])
        self.assertEqual(final['state'],'READY_FOR_HUMAN')
        self.assertEqual([s['spec']['role'] for s in final['subtasks']],['IMPLEMENTER','TESTER','REVIEWER'])
        self.assertTrue(final['test_runs'][0]['passed']);self.assertEqual(final['main_acceptance']['verdict'],'ACCEPT')
        self.assertEqual((self.repo/'src/app.py').read_text(),'VALUE = 1\n')
        self.assertEqual(Path(final['worktree_path'],'src/app.py').read_text(),'VALUE = 2\n')
        impl_call=next(c for c in ScriptedProvider.calls if c[0].startswith('You are an IMPLEMENTER'))
        self.assertEqual(impl_call[2:4],('main-model','high'))
        with self.assertRaises(Exception):self.service.human_merge(final['task_id'],'feat: runtime')
        merged=self.service.human_merge(final['task_id'],'feat: runtime',confirmed=True)
        self.assertEqual(merged['state'],'MERGED');self.assertEqual((self.repo/'src/app.py').read_text(),'VALUE = 2\n')

    def test_subagent_return_without_result_is_blocked(self):
        impl=self.service.add_subtask(self.task['task_id'],{'role':'IMPLEMENTER','title':'impl','instruction':'edit','depends_on':[],
            'lease_paths':['src/app.py'],'acceptance_criteria':[],'model':'','effort':''})
        runtime=DevAgentRuntime(self.service,self.config,NoResultProvider)
        with self.assertRaises(DevRuntimeError) as error:runtime.run_subtask(self.task['task_id'],impl['subtask_id'])
        self.assertEqual(error.exception.code,'SUBAGENT_NO_RESULT')
        state=self.service.get(self.task['task_id']);self.assertEqual(state['subtasks'][0]['status'],'BLOCKED')


if __name__=='__main__':unittest.main()
