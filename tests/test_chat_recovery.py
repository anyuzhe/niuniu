import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.chat_journal import ChatStore
from quantlab.agent.chat_recovery import recovery_snapshot, RECOVERY_TOOLS
from quantlab.agent.chat_cli import main
from quantlab.agent.model_config import ModelConfig, ModelError
from quantlab.agent.memory_tools import MEMORY_TOOLS
from quantlab.agent.research_memory import text_field
from quantlab.agent.memory_store import MemoryError


class Transport:
    def __init__(self, actions=(), *, partial=False, fail=False):
        self.actions=actions;self.partial=partial;self.fail=fail;self.results=[];self.called=False
    def run(self, system, messages, tools, dispatch, emit, stop):
        self.called=True;self.system=system;self.tools={t['name'] for t in tools};self.messages=messages
        for i,(name,args) in enumerate(self.actions):
            self.results.append(dispatch(name,args,str(i)))
        if self.fail:raise ModelError('fixture interruption')
        return {'text':'已有证据需复核；未启动新研究。','model':'fixture','provider':'fixture',
                'needs_followup':self.partial,'usage':{}}


class ChatRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.runtime=ChatRuntime(self.root,self.root,lambda:self.fail('queue acquired'),local_data_only=True)
        self.cid=self.runtime.store.create('recovery fixture')
        self.config=ModelConfig(max_context_chars=200000)
    def seed(self, status='failed', refs=None):
        tid=self.runtime.store.begin(self.cid,'原始研究问题',{})
        refs=refs or [{'kind':'job','job_id':str(uuid4())}]
        for _ in range(2):
            self.runtime.store.event(tid,'tool_result',{'name':'get_job','call_id':'old-echo',
                'result':{'ok':True,'data':{'value':'unverified secret-looking external text'},'evidence':refs}})
        self.runtime.store.finish(tid,status,'尚未完成',{'error':'interrupted','evidence':refs,'needs_followup':True})
        return refs
    def test_snapshot_deduplicates_historical_ids_without_numbers_or_external_text(self):
        refs=self.seed()
        snap=recovery_snapshot(self.runtime.store,self.cid)
        self.assertEqual(snap['references'],refs);self.assertTrue(snap['needs_followup'])
        self.assertNotIn('external text',json.dumps(snap));self.assertEqual(snap['previous_status'],'failed')
        self.assertEqual(ChatStore(self.root).events(self.cid),self.runtime.store.events(self.cid))
    def test_recovery_filters_tools_before_dispatch_and_never_acquires_queue(self):
        refs=self.seed();provider=Transport([('submit_granted_experiment',{}),('record_hypothesis',{}),('get_research_session_grant',{})])
        before=len(list(self.root.glob('*/experiment.json')))
        result=self.runtime.send(self.cid,'整理已有结果',self.config,allow_send=True,provider=provider,recovery_only=True)
        self.assertTrue(provider.tools <= RECOVERY_TOOLS)
        self.assertFalse(provider.results[0]['ok']);self.assertFalse(provider.results[1]['ok'])
        self.assertTrue(provider.results[2]['ok']);self.assertTrue(result['recovery_only'])
        self.assertIn(refs[0]['job_id'],provider.system)
        self.assertFalse((self.root/'_jobs').exists());self.assertEqual(before,len(list(self.root.glob('*/experiment.json'))))
        self.assertIn('submit_granted_experiment',{t['name'] for t in self.runtime.api.schemas()})
    def test_ordinary_followup_receives_failed_turn_ids_and_failure_text_is_retained(self):
        ref={'kind':'job','job_id':str(uuid4())};self.seed(refs=[ref])
        provider=Transport(fail=True)
        with self.assertRaises(ModelError):
            self.runtime.send(self.cid,'继续',self.config,allow_send=True,provider=provider)
        self.assertIn(ref['job_id'],provider.system)
        last=self.runtime.store.turns(self.cid)[-1]
        self.assertEqual(last['status'],'failed');self.assertIn('本轮未完成',last['assistant_text'])
        self.assertTrue(last['metadata']['needs_followup'])
        self.assertTrue(recovery_snapshot(ChatStore(self.root),self.cid)['references'])
    def test_partial_is_not_completed_and_survives_new_store(self):
        self.seed()
        result=self.runtime.send(self.cid,'整理',self.config,allow_send=True,provider=Transport(partial=True),recovery_only=True)
        self.assertEqual(result['status'],'partial')
        restored=ChatStore(self.root);self.assertEqual(restored.turns(self.cid)[-1]['status'],'partial')
        self.assertIn('历史未完成答复',restored.messages(self.cid,200000)[-1]['content'])
        self.assertTrue(recovery_snapshot(restored,self.cid)['needs_followup'])
    def test_pi_budget_exception_preserves_partial_text_usage_and_host_count(self):
        from quantlab.devstudio.pi_provider import PiBudgetStopped
        class BudgetTransport:
            def run(inner,system,messages,tools,dispatch,emit,stop):
                dispatch('get_research_session_grant',{},'budget-call')
                raise PiBudgetStopped({'text':'预算收尾：尚未保存结论。','termination':'budget_stopped',
                    'reason':'round_budget_finalization','needs_followup':True,'tool_calls':999,
                    'usage':{'totalTokens':7},'model':'fixture','provider':'fixture'})
        result=self.runtime.send(self.cid,'读取授权',self.config,allow_send=True,provider=BudgetTransport())
        self.assertEqual(result['status'],'partial');self.assertEqual(result['tool_calls'],1)
        self.assertEqual(result['usage']['totalTokens'],7);self.assertIn('尚未保存',result['text'])
        self.assertEqual(ChatStore(self.root).turns(self.cid)[-1]['status'],'partial')
        self.assertEqual(len([e for e in self.runtime.store.events(self.cid)['events'] if e['kind']=='tool_result']),1)
    def test_stop_wins_over_budget_summary(self):
        from threading import Event
        from quantlab.agent.model_config import ChatStopped
        from quantlab.devstudio.pi_provider import PiBudgetStopped
        stop=Event()
        class BudgetTransport:
            def run(inner,*args):
                stop.set()
                raise PiBudgetStopped({'text':'不要展示为完成','needs_followup':True,'reason':'budget'})
        with self.assertRaises(ChatStopped):
            self.runtime.send(self.cid,'test',self.config,allow_send=True,stop=stop,provider=BudgetTransport())
        self.assertEqual(self.runtime.store.turns(self.cid)[-1]['status'],'stopped')
    def test_no_implicit_consent_or_empty_session_recovery(self):
        provider=Transport()
        with self.assertRaises(ModelError):self.runtime.send(self.cid,'整理',self.config,provider=provider,recovery_only=True)
        with self.assertRaises(ModelError):self.runtime.send(self.cid,'整理',self.config,allow_send=True,provider=provider,recovery_only=True)
        self.assertFalse(provider.called)
        with self.assertRaises(ValueError):self.runtime.send(self.cid,'整理',self.config,allow_send=True,provider=provider,recovery_only='yes')
    def test_snapshot_bound_is_explicit_and_invalid_references_are_not_links(self):
        refs=[{'kind':'experiment','run_id':str(uuid4())} for _ in range(40)]
        refs += [{'kind':'experiment','run_id':'../escape'},{'kind':'external','url':'https://example.test'},{'kind':[]}]
        self.seed(refs=refs)
        snap=recovery_snapshot(self.runtime.store,self.cid,limit=5)
        self.assertEqual(len(snap['references']),5);self.assertEqual(snap['omitted_references'],35)
        self.assertTrue(snap['incomplete'])
    def test_cli_recovery_uses_explicit_mode_and_supports_pi_transport(self):
        self.seed();provider=Transport();output=io.StringIO()
        with patch('quantlab.agent.chat_runtime.provider_for',return_value=provider), redirect_stdout(output):
            code=main(['--output',str(self.root),'--session',self.cid,'--recover-results',
                       '--provider','pi_sdk','--model','openai-codex/gpt-6-luna','--accept-model-service'])
        self.assertEqual(code,0,output.getvalue());self.assertTrue(json.loads(output.getvalue())['data']['recovery_only'])
        self.assertTrue(provider.tools <= RECOVERY_TOOLS)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['--output',str(self.root),'--session',self.cid,'--recover-results','--allow-granted-research'])
    def test_root_hypothesis_exposes_exact_finding_parent_without_rewriting_lineage(self):
        from test_research_memory import hypothesis,finding
        from test_context_experiments import ContextProvider,context_config,runner
        from dataclasses import replace
        api=self.runtime.api
        saved=api.call('record_hypothesis',{'request_id':str(uuid4()),'hypothesis_json':json.dumps(hypothesis())})
        self.assertTrue(saved['ok'],saved)
        hid=saved['data']['record']['memory_id']
        self.assertIsNone(saved['data']['record']['hypothesis_id'])
        self.assertEqual(saved['data']['finding_parent_id'],hid)
        read=api.call('get_research_memory',{'memory_id':hid})
        self.assertEqual(read['data']['finding_parent_id'],hid)
        source=runner(ContextProvider(),self.root).run(replace(context_config(),context=None,replay=True))
        written=api.call('record_finding',{'request_id':str(uuid4()),'finding_json':json.dumps(finding(read['data']['finding_parent_id'],source.run_id))})
        self.assertTrue(written['ok'],written)
        self.assertEqual(written['data']['finding_parent_id'],hid)
        root=api.call('get_research_memory',{'memory_id':hid})
        self.assertIsNone(root['data']['record']['hypothesis_id'])
        self.assertNotEqual(written['data']['record']['memory_id'],hid)
    def test_memory_text_contract_is_explicit_without_relaxing_validation(self):
        description=next(t['description'] for t in MEMORY_TOOLS if t['name']=='record_finding')
        self.assertIn('limitations',description);self.assertIn('4000',description);self.assertIn('不是数组',description)
        for value in ([],{},'',None,'x'*4001):
            with self.assertRaisesRegex(MemoryError,'string.*4000'):
                text_field(value,'适用范围与局限')
        text_field('第一项\n第二项','适用范围与局限')


if __name__=='__main__':unittest.main()
