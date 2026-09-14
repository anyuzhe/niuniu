import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantlab.agent.playbook_tools import PlaybookResearchAPI
from quantlab.devstudio.tools import MainDevAPI,SubtaskDevAPI
from quantlab.devstudio.service import DevStudioService


class DummyService:
    def __init__(self,role='IMPLEMENTER'):
        self.role=role
    def get(self,task_id):
        return {'task_id':task_id,'state':'RUNNING','spec':{'test_commands':[['python','-m','unittest','x']]},
            'subtasks':[{'subtask_id':'00000000-0000-0000-0000-000000000002','status':'RUNNING',
                'spec':{'role':self.role,'lease_paths':['src/x.py']}}], 'test_runs':[]}


class DevStudioSecurityTests(unittest.TestCase):
    def test_research_agent_has_no_dev_write_or_merge_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            names={x['name'] for x in PlaybookResearchAPI(Path(tmp)).schemas()}
        self.assertFalse(any(name.startswith('dev_') for name in names))
        self.assertFalse({'human_merge','git_push','dev_write_file'} & names)

    def test_role_tool_catalogs_are_least_privilege(self):
        task='00000000-0000-0000-0000-000000000001';sub='00000000-0000-0000-0000-000000000002'
        main={x['name'] for x in MainDevAPI(DummyService(),task).schemas()}
        self.assertIn('dev_create_subtask',main);self.assertIn('dev_accept_task',main)
        self.assertNotIn('dev_write_file',main);self.assertNotIn('dev_run_frozen_test',main)
        implementer={x['name'] for x in SubtaskDevAPI(DummyService('IMPLEMENTER'),task,sub).schemas()}
        tester={x['name'] for x in SubtaskDevAPI(DummyService('TESTER'),task,sub).schemas()}
        reviewer={x['name'] for x in SubtaskDevAPI(DummyService('REVIEWER'),task,sub).schemas()}
        self.assertIn('dev_write_file',implementer);self.assertNotIn('dev_run_frozen_test',implementer)
        self.assertIn('dev_run_frozen_test',tester);self.assertNotIn('dev_write_file',tester)
        self.assertNotIn('dev_write_file',reviewer);self.assertNotIn('dev_run_frozen_test',reviewer)
        self.assertFalse({'dev_create_subtask','dev_accept_task'} & reviewer)


    def test_main_agent_can_read_and_search_isolated_worktree_but_not_write(self):
        import os,subprocess,sys
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)/'repo';repo.mkdir();(repo/'.gitignore').write_text('artifacts/\n.venv/\n')
            (repo/'README.md').write_text('牛牛 Dev Studio\n');(repo/'src').mkdir();(repo/'src/app.py').write_text('VALUE=1\n')
            subprocess.run(['git','init','-b','main'],cwd=repo,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            subprocess.run(['git','config','user.email','test@example.invalid'],cwd=repo,check=True)
            subprocess.run(['git','config','user.name','Test User'],cwd=repo,check=True)
            subprocess.run(['git','add','.'],cwd=repo,check=True);subprocess.run(['git','commit','-m','base'],cwd=repo,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            bindir=repo/'.venv/bin';bindir.mkdir(parents=True);os.symlink(sys.executable,bindir/'python')
            output=repo/'artifacts';output.mkdir();service=DevStudioService(output,repo)
            task=service.create_task({'title':'read','request':'read repo','acceptance_criteria':['inspect'],
                'allowed_paths':['src/app.py'],'test_commands':[],'max_parallel_subagents':1,'notes':''})
            try:
                api=MainDevAPI(service,task['task_id'])
                read=api.call('dev_read_file',{'path':'README.md'})
                self.assertTrue(read['ok']);self.assertIn('牛牛',read['data']['text'])
                search=api.call('dev_search',{'query':'牛牛'})
                self.assertTrue(search['ok']);self.assertTrue(any(r['path']=='README.md' for r in search['data']))
                self.assertNotIn('dev_write_file',{tool['name'] for tool in api.schemas()})
            finally:service.cleanup(task['task_id'],force=True)

    def test_cli_has_merge_but_no_push_action(self):
        source=Path('src/quantlab/agent/dev_studio_cli.py').read_text()
        self.assertIn("'merge'",source);self.assertNotIn("'push'",source)
        self.assertIn('Human merge is explicit',source)


if __name__=='__main__':unittest.main()
