"""Six-role host contracts and actual temporary-Git lifecycle, no paid model/data."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from threading import Event
import json
import os
import subprocess
import sys
import tempfile
import unittest

from quantlab.agent.model_config import ModelConfig, ModelError
from quantlab.devstudio.contracts import normalize_task_spec
from quantlab.devstudio.planning import DevRequestPlanner, RequestPlanningAPI, build_plan
from quantlab.devstudio.runtime import DevAgentRuntime
from quantlab.devstudio.service import DevStudioService, DevStudioError
from quantlab.devstudio.team import (DOMAINS, owner_for_path, safe_development_path,
                                    load_team_models, save_team_models, normalize_models)

PATHS = {'DATA': 'src/quantlab/data/example.py', 'CORE': 'src/quantlab/factors/example.py',
         'AI': 'src/quantlab/agent/example.py', 'APP': 'src/quantlab/desktop/example.py'}
COMMAND = ['python', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_team_sample.py', '-v']


def models():
    return {domain: asdict(ModelConfig(model='test-' + domain.lower(), effort='low' if domain == 'APP' else 'medium')) for domain in DOMAINS}


class ToyProject:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='niuniu-team-test-')
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.output = self.root / 'output'
        self.output.mkdir()
        (self.repo / '.gitignore').write_text('.venv/\n__pycache__/\n')
        for path in PATHS.values():
            p = self.repo / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('VALUE = 1\n')
        (self.repo / 'src/quantlab/__init__.py').write_text('')
        (self.repo / 'README.md').write_text('Synthetic team test repository.\n')
        (self.repo / 'tests').mkdir()
        (self.repo / 'tests/test_team_sample.py').write_text(
            'import unittest\nfrom quantlab.data.example import VALUE as DATA\n'
            'from quantlab.factors.example import VALUE as CORE\n'
            'from quantlab.agent.example import VALUE as AI\n'
            'from quantlab.desktop.example import VALUE as APP\n'
            'class T(unittest.TestCase):\n'
            '    def test_values(self): self.assertEqual([DATA,CORE,AI,APP],[2,2,2,2])\n')
        (self.repo / 'tests/test_zero.py').write_text('import unittest\n')
        (self.repo / 'tests/test_skip.py').write_text(
            'import unittest\n@unittest.skip("not evidence")\nclass T(unittest.TestCase):\n'
            '    def test_skip(self): pass\n')
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test User')
        self.git('add', '.')
        self.git('commit', '-m', 'synthetic base')
        bindir = self.repo / '.venv/bin'
        bindir.mkdir(parents=True)
        os.symlink(sys.executable, bindir / 'python')
        self.service = DevStudioService(self.output, self.repo)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.PIPE, text=True).strip()

    def proposal(self):
        return {'title': '四域协作测试', 'acceptance_criteria': ['四个模块 VALUE 均改为 2，主工作区直到确认合并前不变'],
                'path_owners': {p: d for d, p in PATHS.items()}, 'test_commands': [list(COMMAND)],
                'notes': '四个实施域独立修改；QA 在所有写入结束后测试，随后独立审核。'}

    def plan(self):
        return build_plan(self.service.workspace, '把四个模块的 VALUE 改为 2', self.proposal(), models())

    def task(self):
        return self.service.create_from_plan(self.plan(), confirmed=True)

    def cleanup(self):
        for task in self.service.list():
            try: self.service.cleanup(task['task_id'], force=True)
            except Exception: pass
        self.tmp.cleanup()


class ScriptedTeamProvider:
    """Drives the real role tools; assertions/test execution are never mocked."""
    calls = []
    proposal = None
    fail_first_app = False

    def __init__(self, config):
        self.config = config

    def run(self, system, messages, tools, dispatch, emit, stop):
        context = json.loads(messages[0]['content'])
        names = {t['name'] for t in tools}
        def call(name, args):
            result = dispatch(name, args, name)
            if not result['ok']: raise AssertionError(result['error'])
            return result['data']
        if 'read-only LEAD development planner' in system:
            self.calls.append(('PLAN', self.config.model, self.config.effort, names))
            call('dev_list_files', {'prefix': 'src/', 'offset': 0})
            call('dev_read_file', {'path': PATHS['APP']})
            call('dev_propose_team_plan', {'plan_json': json.dumps(self.proposal, ensure_ascii=False)})
            return {'text': 'planned', 'model': self.config.model, 'provider': 'scripted'}
        status = call('dev_task_status', {})
        if 'Niuniu Main Developer Agent' in system:
            self.calls.append(('LEAD', self.config.model, self.config.effort, names))
            if not status['subtasks']:
                ids = []
                for domain, path in PATHS.items():
                    sub = call('dev_create_subtask', {'domain': domain, 'role': 'IMPLEMENTER', 'title': domain,
                        'instruction': 'Change only your leased VALUE to 2.', 'depends_on': [], 'lease_paths': [path],
                        'acceptance_criteria': ['VALUE=2'], 'effort': ''})
                    ids.append(sub['subtask_id'])
                tester = call('dev_create_subtask', {'domain': 'QA', 'role': 'TESTER', 'title': 'run tests',
                    'instruction': 'Run every frozen command.', 'depends_on': ids, 'lease_paths': [],
                    'acceptance_criteria': ['real tests pass'], 'effort': ''})
                call('dev_create_subtask', {'domain': 'QA', 'role': 'REVIEWER', 'title': 'independent review',
                    'instruction': 'Review actual changes and evidence.', 'depends_on': [tester['subtask_id']],
                    'lease_paths': [], 'acceptance_criteria': ['scope and evidence'], 'effort': ''})
            elif any(s['status'] == 'BLOCKED' for s in status['subtasks']):
                app = next(s for s in status['subtasks'] if s['spec'].get('domain') == 'APP')
                call('dev_reopen_subtask', {'subtask_id': app['subtask_id'], 'instruction': 'Repair VALUE to exactly 2; do not weaken tests.'})
            else:
                call('dev_diff', {})
                call('dev_accept_task', {'verdict': 'ACCEPT', 'summary': 'All four domains, actual tests and independent review passed.',
                                         'evidence': ['actual diff', 'frozen test', 'reviewer']})
        else:
            sub = context['active_subtask']
            role, domain = sub['spec']['role'], sub['spec']['domain']
            self.calls.append((domain + ':' + role, self.config.model, self.config.effort, names))
            verdict = 'PASS'
            if role == 'IMPLEMENTER':
                path = sub['spec']['lease_paths'][0]
                before = call('dev_read_file', {'path': path})
                value = 3 if self.fail_first_app and domain == 'APP' and sub['attempts'] == 1 else 2
                call('dev_write_file', {'path': path, 'text': f'VALUE = {value}\n', 'expected_sha256': before['sha256']})
            elif role == 'TESTER':
                for index in range(len(status['spec']['test_commands'])):
                    evidence = call('dev_run_frozen_test', {'command_index': index})
                    if not evidence['passed']: verdict = 'FAIL'
            elif role == 'REVIEWER':
                diff = call('dev_diff', {})
                if diff['patch'].count('+VALUE = 2') != 4: verdict = 'NEEDS_CHANGES'
            call('dev_submit_result', {'summary': domain + ' ' + role + ' ' + verdict, 'verdict': verdict,
                                       'evidence': ['actual role tools'], 'stop_reason': ''})
        return {'text': 'done', 'model': self.config.model, 'provider': 'scripted'}


class DevTeamTests(unittest.TestCase):
    def setUp(self):
        self.project = ToyProject()
        self.service = self.project.service
        ScriptedTeamProvider.calls = []
        ScriptedTeamProvider.proposal = self.project.proposal()
        ScriptedTeamProvider.fail_first_app = False

    def tearDown(self):
        self.project.cleanup()

    def impl(self, task, domain='APP'):
        return self.service.add_subtask(task['task_id'], {'domain': domain, 'role': 'IMPLEMENTER', 'title': domain,
            'instruction': 'Change value', 'depends_on': [], 'lease_paths': [PATHS[domain]],
            'acceptance_criteria': ['VALUE=2'], 'model': '', 'effort': ''})

    def test_read_only_planner_then_four_domain_lifecycle_and_human_gate(self):
        before = self.project.git('worktree', 'list', '--porcelain')
        planner = DevRequestPlanner(self.service, models(), ScriptedTeamProvider)
        plan = planner.plan('把四个模块的 VALUE 改为 2', allow_send=True)
        self.assertEqual(self.project.git('worktree', 'list', '--porcelain'), before)
        self.assertEqual(self.service.list(), [])
        with self.assertRaises(DevStudioError): self.service.create_from_plan(plan)
        task = self.service.create_from_plan(plan, confirmed=True)
        runtime = DevAgentRuntime(self.service, provider_factory=ScriptedTeamProvider)
        final = runtime.run_cycle(task['task_id'])
        self.assertEqual(final['state'], 'READY_FOR_HUMAN')
        self.assertEqual(len(final['subtasks']), 6)
        for path in PATHS.values():
            self.assertEqual((self.project.repo / path).read_text(), 'VALUE = 1\n')
            self.assertEqual((Path(task['worktree_path']) / path).read_text(), 'VALUE = 2\n')
        test = final['test_runs'][-1]
        self.assertEqual(test['tests_run'], 1)
        self.assertIn(task['worktree_path'], test['stdout_tail'])
        self.assertFalse(test['os_sandbox'])
        roles = {r[0].split(':')[0] for r in ScriptedTeamProvider.calls}
        self.assertTrue(set(DOMAINS) <= roles)
        app = next(c for c in ScriptedTeamProvider.calls if c[0] == 'APP:IMPLEMENTER')
        self.assertEqual(app[1:3], ('test-app', 'low'))
        for domain, _, _, tools in ScriptedTeamProvider.calls:
            if domain.startswith(('LEAD', 'QA', 'PLAN')): self.assertNotIn('dev_write_file', tools)
        with self.assertRaises(DevStudioError): self.service.human_merge(task['task_id'], 'test: merge')
        merged = self.service.human_merge(task['task_id'], 'test: six roles', confirmed=True)
        self.assertEqual(merged['state'], 'MERGED')
        self.assertFalse(merged['merge']['pushed'])
        self.assertEqual((self.project.repo / PATHS['APP']).read_text(), 'VALUE = 2\n')

    def test_failed_test_returns_to_owner_and_invalidates_qa(self):
        ScriptedTeamProvider.fail_first_app = True
        task = self.project.task()
        final = DevAgentRuntime(self.service, provider_factory=ScriptedTeamProvider).run_cycle(task['task_id'])
        self.assertEqual(final['state'], 'READY_FOR_HUMAN')
        app = next(s for s in final['subtasks'] if s['spec'].get('domain') == 'APP')
        tester = next(s for s in final['subtasks'] if s['spec']['role'] == 'TESTER')
        self.assertEqual((app['attempts'], tester['attempts']), (2, 2))
        self.assertEqual([r['passed'] for r in final['test_runs']], [False, True])
        self.assertIn('SUBTASK_REOPENED', [e['kind'] for e in final['events']])

    def test_profiles_frozen_at_confirmation(self):
        task = self.project.task()
        changed = models()
        changed['APP']['model'] = 'changed-later'
        save_team_models(self.project.output, changed)
        DevAgentRuntime(self.service, provider_factory=ScriptedTeamProvider).run_cycle(task['task_id'])
        self.assertIn(('APP:IMPLEMENTER', 'test-app', 'low'), [c[:3] for c in ScriptedTeamProvider.calls])
        self.assertEqual(load_team_models(self.project.output)['APP']['model'], 'changed-later')

    def test_wrong_domain_and_cross_directory_data_owner(self):
        self.assertEqual(owner_for_path('src/quantlab/agent/live_stock_quote.py'), 'DATA')
        self.assertEqual(owner_for_path('src/quantlab/data/provider.py'), 'CORE')
        proposal = self.project.proposal()
        proposal['path_owners'][PATHS['DATA']] = 'APP'
        with self.assertRaises(ValueError): build_plan(self.service.workspace, 'x', proposal, models())
        self.assertEqual(self.service.list(), [])

    def test_no_secrets_runtime_data_or_directory_scope(self):
        for path in ('.env', 'artifacts/log.txt', '/tmp/file.py', '../x.py', 'C:/x.py', 'src/secret.key', 'lake/x.py', 'bad\x00.py'):
            with self.subTest(path=path), self.assertRaises(ValueError): safe_development_path(path)
        p = self.project.proposal()
        p['path_owners'] = {'src/quantlab/desktop': 'APP'}
        with self.assertRaises(ValueError): build_plan(self.service.workspace, 'x', p, models())

    def test_plan_hash_request_and_base_changes_rejected(self):
        plan = self.project.plan()
        bad = deepcopy(plan)
        bad['spec']['request'] = 'different request'
        with self.assertRaises(DevStudioError): self.service.create_from_plan(bad, confirmed=True)
        (self.project.repo / 'README.md').write_text('new base\n')
        self.project.git('add', 'README.md')
        self.project.git('commit', '-m', 'move main')
        with self.assertRaises(DevStudioError): self.service.create_from_plan(plan, confirmed=True)
        self.assertEqual(self.service.list(), [])

    def test_planner_requires_send_consent_and_blocks_secret_reads(self):
        planner = DevRequestPlanner(self.service, models(), ScriptedTeamProvider)
        with self.assertRaises(ModelError): planner.plan('x')
        api = RequestPlanningAPI(self.service, 'x', models())
        self.assertFalse(api.call('dev_read_file', {'path': '.env'})['ok'])
        self.assertFalse(api.call('dev_write_file', {'path': PATHS['APP'], 'text': 'x'})['ok'])
        self.assertFalse(api.call('dev_propose_team_plan', {'plan_json': '{"x":1,"x":2}'})['ok'])

    def test_missing_or_unsafe_tests_rejected(self):
        for commands in ([], [['sh', '-c', 'true']], [['python', '-m', 'compileall', 'src']]):
            p = self.project.proposal(); p['test_commands'] = commands
            with self.assertRaises(ValueError): build_plan(self.service.workspace, 'x', p, models())
        p = self.project.proposal(); p['test_commands'][0][7] = 'test_absent.py'
        with self.assertRaises(ValueError): build_plan(self.service.workspace, 'x', p, models())

    def test_model_cannot_change_domain_profile_or_qa_write(self):
        task = self.project.task()
        spec = {'domain': 'QA', 'role': 'IMPLEMENTER', 'title': 'bad', 'instruction': 'bad',
                'depends_on': [], 'lease_paths': [PATHS['APP']], 'acceptance_criteria': [], 'model': '', 'effort': ''}
        with self.assertRaises(DevStudioError): self.service.add_subtask(task['task_id'], spec)
        spec.update(domain='APP', model='self-selected')
        with self.assertRaises(DevStudioError): self.service.add_subtask(task['task_id'], spec)
        spec.update(model='', effort='xhigh')
        with self.assertRaises(DevStudioError): self.service.add_subtask(task['task_id'], spec)
        spec.update(effort=''); spec.pop('domain')
        with self.assertRaises(DevStudioError): self.service.add_subtask(task['task_id'], spec)

    def test_existing_file_requires_cas_and_wrong_owner_is_rejected(self):
        task = self.project.task(); sub = self.impl(task)
        tid, sid = task['task_id'], sub['subtask_id']
        self.service.start_subtask(tid, sid)
        with self.assertRaises(DevStudioError) as error: self.service.write_file(tid, sid, PATHS['APP'], 'VALUE=2\n')
        self.assertEqual(error.exception.code, 'CAS_REQUIRED')
        with self.assertRaises(DevStudioError): self.service.write_file(tid, sid, PATHS['DATA'], 'VALUE=2\n', '0'*64)
        with self.assertRaises(DevStudioError): self.service.write_file(tid, sid, PATHS['APP'], 'VALUE=2\n', '0'*64)
        self.assertEqual((Path(task['worktree_path']) / PATHS['APP']).read_text(), 'VALUE = 1\n')

    def test_zero_tests_and_all_skipped_cannot_pass(self):
        task = self.project.task()
        for name in ('test_zero.py', 'test_skip.py'):
            command = list(COMMAND); command[7] = name
            evidence = self.service.workspace.run_test(task['worktree_path'], command, require_tests=True)
            # Some Python versions return 5 for zero discovered tests; the host
            # must reject zero/all-skipped execution regardless of runner exit policy.
            if name == 'test_zero.py':
                self.assertEqual(evidence['tests_run'], 0)
            else:
                self.assertEqual(evidence['returncode'], 0)
                self.assertEqual((evidence['tests_run'], evidence['tests_skipped']), (1, 1))
            self.assertFalse(evidence['passed'])

    def test_duplicate_execution_lock_and_running_subtask_rejected(self):
        task = self.project.task()
        with self.service.execution_lock():
            with self.assertRaises(DevStudioError) as error:
                DevAgentRuntime(self.service, provider_factory=ScriptedTeamProvider).run_cycle(task['task_id'])
        self.assertEqual(error.exception.code, 'REPO_BUSY')
        sub = self.impl(task)
        self.service.start_subtask(task['task_id'], sub['subtask_id'])
        with self.assertRaises(DevStudioError): self.service.start_subtask(task['task_id'], sub['subtask_id'])

    def test_failed_dependency_and_attempt_limit(self):
        task = self.project.task(); sub = self.impl(task)
        tid, sid = task['task_id'], sub['subtask_id']
        tester = self.service.add_subtask(tid, {'domain': 'QA', 'role': 'TESTER', 'title': 'QA', 'instruction': 'test',
            'depends_on': [], 'lease_paths': [], 'acceptance_criteria': [], 'model': '', 'effort': ''})
        for attempt in range(3):
            self.service.start_subtask(tid, sid)
            self.service.finish_subtask(tid, sid, {'summary': 'failed', 'verdict': 'FAIL', 'changed_files': [], 'tests': [], 'evidence': [], 'stop_reason': ''})
            with self.assertRaises(DevStudioError): self.service.start_subtask(tid, tester['subtask_id'])
            if attempt < 2: self.service.reopen_subtask(tid, sid)
        with self.assertRaises(DevStudioError) as error: self.service.reopen_subtask(tid, sid)
        self.assertEqual(error.exception.code, 'ATTEMPT_BUDGET')

    def test_mutation_after_acceptance_blocks_merge(self):
        task = self.project.task()
        DevAgentRuntime(self.service, provider_factory=ScriptedTeamProvider).run_cycle(task['task_id'])
        (Path(task['worktree_path']) / PATHS['APP']).write_text('VALUE = 99\n')
        with self.assertRaises(DevStudioError) as error: self.service.human_merge(task['task_id'], 'bad', confirmed=True)
        self.assertEqual(error.exception.code, 'STALE_ACCEPTANCE')
        self.assertEqual((self.project.repo / PATHS['APP']).read_text(), 'VALUE = 1\n')

    def test_stop_before_dispatch_does_not_call_models(self):
        task = self.project.task(); stop = Event(); stop.set()
        state = DevAgentRuntime(self.service, provider_factory=ScriptedTeamProvider).run_cycle(task['task_id'], stop=stop)
        self.assertEqual(state['state'], 'BLOCKED')
        self.assertEqual(ScriptedTeamProvider.calls, [])
        self.assertEqual(state['subtasks'], [])

    def test_exact_edit_and_range_keep_unrelated_source_and_scope(self):
        from quantlab.devstudio.tools import SubtaskDevAPI, MainDevAPI
        task=self.project.task();sub=self.impl(task);tid=task['task_id'];sid=sub['subtask_id']
        self.service.start_subtask(tid,sid)
        api=SubtaskDevAPI(self.service,tid,sid)
        result=api.call('dev_read_range',{'path':PATHS['APP'],'start_line':1,'limit':1})
        self.assertTrue(result['ok']);sha=result['data']['sha256']
        self.assertEqual(result['data']['text'],'VALUE = 1\n')
        changed=api.call('dev_replace_text',{'path':PATHS['APP'],'old':'1','new':'2','expected_sha256':sha})
        self.assertTrue(changed['ok'],changed)
        self.assertEqual((Path(task['worktree_path'])/PATHS['APP']).read_text(),'VALUE = 2\n')
        self.assertFalse(api.call('dev_replace_text',{'path':PATHS['APP'],'old':'2','new':'3','expected_sha256':sha})['ok'])
        self.assertFalse(MainDevAPI(self.service,tid).call('dev_replace_text',{'path':PATHS['APP'],'old':'2','new':'3','expected_sha256':sha})['ok'])
        self.assertEqual((self.project.repo/PATHS['APP']).read_text(),'VALUE = 1\n')

    def test_writer_limit_and_qa_exclusivity(self):
        task=self.project.task();tid=task['task_id']
        a=self.impl(task,'DATA');b=self.impl(task,'CORE');c=self.impl(task,'APP')
        self.service.start_subtask(tid,a['subtask_id']);self.service.start_subtask(tid,b['subtask_id'])
        with self.assertRaises(DevStudioError):self.service.start_subtask(tid,c['subtask_id'])
        result={'summary':'checked','verdict':'PASS','changed_files':[],'tests':[],'evidence':[],'stop_reason':''}
        self.service.finish_subtask(tid,a['subtask_id'],result);self.service.finish_subtask(tid,b['subtask_id'],result)
        self.service.start_subtask(tid,c['subtask_id']);self.service.finish_subtask(tid,c['subtask_id'],result)
        qa=self.service.add_subtask(tid,{'domain':'QA','role':'TESTER','title':'QA','instruction':'test','depends_on':[],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        self.service.start_subtask(tid,qa['subtask_id'])
        with self.assertRaises(DevStudioError):self.impl(task,'AI')
        explorer=self.service.add_subtask(tid,{'domain':'AI','role':'EXPLORER','title':'look','instruction':'look','depends_on':[],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        with self.assertRaises(DevStudioError):self.service.start_subtask(tid,explorer['subtask_id'])

    def test_indirect_dependency_cycle_rejected_without_persisting_task(self):
        task=self.project.task();tid=task['task_id']
        qa=self.service.add_subtask(tid,{'domain':'QA','role':'TESTER','title':'QA','instruction':'test','depends_on':[],
            'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        explorer=self.service.add_subtask(tid,{'domain':'APP','role':'EXPLORER','title':'look','instruction':'look',
            'depends_on':[qa['subtask_id']],'lease_paths':[],'acceptance_criteria':[],'model':'','effort':''})
        before=self.service.get(tid)
        with self.assertRaises(DevStudioError) as error:
            self.service.add_subtask(tid,{'domain':'APP','role':'IMPLEMENTER','title':'cycle','instruction':'bad',
                'depends_on':[explorer['subtask_id']],'lease_paths':[PATHS['APP']],'acceptance_criteria':[],'model':'','effort':''})
        self.assertEqual(error.exception.code,'DEPENDENCY_CYCLE')
        self.assertEqual(self.service.get(tid),before)

    def test_reopening_after_merge_is_forbidden(self):
        task=self.project.task();tid=task['task_id']
        state=DevAgentRuntime(self.service,provider_factory=ScriptedTeamProvider).run_cycle(tid)
        self.service.human_merge(tid,'test: final gate',confirmed=True)
        with self.assertRaises(DevStudioError):self.service.reopen_subtask(tid,state['subtasks'][0]['subtask_id'])

    def test_planner_budget_is_host_enforced(self):
        class Excessive:
            def __init__(self,config):pass
            def run(self,system,messages,tools,dispatch,emit,stop):
                for i in range(3):dispatch('dev_list_files',{'prefix':'','offset':0},str(i))
        profiles=models();profiles['LEAD']['max_tool_calls']=1
        with self.assertRaises(ModelError):DevRequestPlanner(self.service,profiles,Excessive).plan('x',allow_send=True)
        self.assertEqual(self.service.list(),[])

    def test_http_and_codex_profile_routing_without_network(self):
        from unittest.mock import patch
        from quantlab.devstudio.team import make_provider
        config=ModelConfig(provider='responses',model='test-model')
        with patch('quantlab.agent.http_provider.HTTPProvider') as http:
            make_provider(config);self.assertEqual(http.call_args.args[0],config)
        with patch('quantlab.agent.codex_provider.CodexProvider') as codex:
            make_provider(ModelConfig());codex.assert_called_once()

    def test_expired_plan_and_cli_approval_gate(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from quantlab.storage.codec import digest
        from quantlab.agent.dev_studio_cli import main
        plan=self.project.plan();plan['expires_at']='2000-01-01T00:00:00+00:00'
        plan['plan_hash']=digest({k:v for k,v in plan.items() if k!='plan_hash'})
        with self.assertRaises(DevStudioError):self.service.create_from_plan(plan,confirmed=True)
        plan=self.project.plan();path=self.project.root/'plan.json';path.write_text(json.dumps(plan))
        args=['--repo-root',str(self.project.repo),'--output',str(self.project.output),'--approve-plan','--spec-json',str(path)]
        with redirect_stdout(StringIO()) as out:code=main(args)
        self.assertEqual(code,2);self.assertIn('CONFIRMATION_REQUIRED',out.getvalue())
        with redirect_stdout(StringIO()):code=main([*args,'--confirm'])
        self.assertEqual(code,0);self.assertEqual(len(self.service.list()),1)

    def test_models_reject_credentials_or_missing_role(self):
        value = models(); value['APP']['api_key'] = 'not-a-real-secret'
        with self.assertRaises((ValueError, TypeError)): normalize_models(value)
        value = models(); value.pop('QA')
        with self.assertRaises(ValueError): normalize_models(value)


if __name__ == '__main__':
    unittest.main()
