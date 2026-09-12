import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4

from quantlab.agent.agent_memory import AgentMemoryLoader,AgentMemoryError
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.model_config import ModelConfig,ModelError
from quantlab.agent.peer_review import PeerReviewService,ReviewReadOnlyAPI
from quantlab.agent.team_config import TeamConfigStore,default_team_config,role_model_config


class FakeRoleProvider:
    def __init__(self,role,registry):self.role=role;self.registry=registry;self.system='';self.messages=[];self.tools=[]
    def run(self,system,messages,tools,dispatch,emit,stop):
        self.system=system;self.messages=json.loads(json.dumps(messages));self.tools=[t['name'] for t in tools]
        self.registry[self.role]=self
        result=dispatch('get_capabilities',{},self.role+'-cap')
        if not result['ok']:raise RuntimeError('capability query failed')
        text='独立意见-'+self.role
        if self.role=='chief_researcher':text='Chief综合：已阅读独立意见'
        return {'text':text,'model':'fixture-'+self.role,'provider':'fixture','tool_calls':1,'usage':{}}


class ChatProvider:
    def __init__(self,request):self.request=request;self.result=None;self.system=''
    def run(self,system,messages,tools,dispatch,emit,stop):
        self.system=system
        self.result=dispatch('propose_peer_review',{'request_id':'model-id','request_json':json.dumps(self.request,ensure_ascii=False)},'p1')
        return {'text':'建议同行复核','model':'fixture','provider':'fixture','tool_calls':1,'usage':{}}

class AITeamTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.repo=Path(__file__).resolve().parents[1]
    def tearDown(self):self.temp.cleanup()

    def spec(self,**updates):
        value={'question':'这份A股判断是否存在证据遗漏？','context':'只核对当前工作空间证据，不新增研究。',
            'reviewers':['market_scanner','skeptic','quant_researcher'],'parent_task_id':None}
        value.update(updates);return value

    def test_git_first_memory_has_hashes_and_no_vector_authority(self):
        loader=AgentMemoryLoader(self.repo);bundle=loader.load('skeptic')
        self.assertTrue(bundle['files']);self.assertTrue(bundle['memory_hash']);self.assertIn('Core Rules',bundle['text'])
        self.assertTrue(any(f['path'].endswith('roles/skeptic.md') for f in bundle['files']))
        self.assertFalse(loader.status()['vector_database_authoritative'])
        self.assertEqual(loader.status()['source_of_truth'],'git_markdown')

    def test_dirty_git_memory_is_rejected_for_formal_agent_use(self):
        loader=AgentMemoryLoader(self.repo)
        with patch('quantlab.agent.agent_memory.memory_git_status',return_value={'tracked':True,'dirty':True,'changes':[' M agent_memory/rules/core.md']}):
            with self.assertRaises(AgentMemoryError):loader.load('skeptic')

    def test_team_role_model_override_has_no_secret(self):
        store=TeamConfigStore(self.root);team=default_team_config();team['roles']['skeptic']['model']='review-model';team['roles']['skeptic']['effort']='high'
        store.save(team);loaded=store.load();base=ModelConfig(model='base-model')
        cfg=role_model_config(base,loaded,'skeptic')
        self.assertEqual((cfg.model,cfg.effort),('review-model','high'))
        self.assertNotIn('api_key',store.path.read_text())
        self.assertFalse(loaded['roles']['developer']['enabled'])

    def test_review_api_excludes_all_write_and_proposal_tools(self):
        api=ReviewReadOnlyAPI(self.root,self.root);names={t['name'] for t in api.schemas()}
        self.assertIn('get_experiment',names);self.assertIn('get_research_agenda',names)
        self.assertFalse(any(name.startswith(('propose_','record_','preview_')) for name in names))
        denied=api.call('propose_experiment',{})
        self.assertFalse(denied['ok']);self.assertEqual(denied['error']['code'],'REVIEW_TOOL_DENIED')

    def test_peer_review_is_independent_then_chief_synthesis_only(self):
        service=PeerReviewService(self.root,self.root,self.repo);task=service.propose(str(uuid4()),self.spec())
        registry={}
        result=service.run(task['task_id'],ModelConfig(model='base'),allow_send=True,
            provider_factory=lambda role,cfg,key:FakeRoleProvider(role,registry))
        self.assertEqual(result['status'],'completed');self.assertEqual(len(result['rounds']),2)
        first=result['rounds'][0];self.assertEqual(first['kind'],'independent');self.assertEqual(len(first['outputs']),3)
        for role in self.spec()['reviewers']:
            text=registry[role].messages[0]['content']
            self.assertNotIn('独立意见-',text);self.assertNotIn('Chief综合',text)
            self.assertIn('这是独立第一轮',registry[role].system)
        chief_text=registry['chief_researcher'].messages[0]['content']
        self.assertIn('独立意见-market_scanner',chief_text);self.assertIn('独立意见-skeptic',chief_text)
        self.assertIn('第二轮 Chief 综合',registry['chief_researcher'].system)
        self.assertEqual(result['stop_reason'],'completed')
        self.assertEqual(result['frozen']['memory']['skeptic']['git_commit'],AgentMemoryLoader(self.repo).load('skeptic')['git_commit'])
        self.assertFalse((self.root/'_jobs').exists())

    def test_chat_can_only_propose_pending_review_not_launch_it(self):
        runtime=ChatRuntime(self.root,self.root);cid=runtime.store.create();provider=ChatProvider(self.spec(reviewers=['skeptic']))
        result=runtime.send(cid,'请找反方复核',ModelConfig(model='base'),allow_send=True,provider=provider)
        self.assertTrue(provider.result['ok']);task=runtime.api.peer_reviews.get(provider.result['data']['task_id'])
        self.assertEqual(task['status'],'pending');self.assertEqual(task['rounds'],[])
        self.assertFalse((self.root/'_jobs').exists());self.assertEqual(result['tool_calls'],1)
        self.assertIn('MEMORY FILE: agent_memory/README.md',provider.system)
        self.assertEqual(result['agent_memory']['memory_hash'],AgentMemoryLoader(self.repo).load('chief_researcher')['memory_hash'])

    def test_same_peer_review_task_cannot_run_twice_concurrently(self):
        service=PeerReviewService(self.root,self.root,self.repo);task=service.propose(str(uuid4()),self.spec(reviewers=['skeptic']))
        with service.store.lease(task['task_id']):
            with self.assertRaises(ModelError):
                service.run(task['task_id'],ModelConfig(model='base'),allow_send=True,provider_factory=lambda role,cfg,key:FakeRoleProvider(role,{}))

    def test_run_requires_host_send_consent_and_is_single_use(self):
        service=PeerReviewService(self.root,self.root,self.repo);task=service.propose(str(uuid4()),self.spec(reviewers=['skeptic']))
        with self.assertRaises(ModelError):service.run(task['task_id'],ModelConfig(model='base'),allow_send=False)
        service.run(task['task_id'],ModelConfig(model='base'),allow_send=True,
            provider_factory=lambda role,cfg,key:FakeRoleProvider(role,{}))
        with self.assertRaises(ModelError):service.run(task['task_id'],ModelConfig(model='base'),allow_send=True,
            provider_factory=lambda role,cfg,key:FakeRoleProvider(role,{}))


if __name__=='__main__':unittest.main()
