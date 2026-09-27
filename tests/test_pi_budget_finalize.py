"""End-to-end hard-budget/finalization checks with Node and a fake Pi ModelRuntime."""
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from quantlab.agent.model_config import ModelConfig, ModelError
from quantlab.devstudio.pi_provider import PiBudgetStopped, PiProvider

FIXTURE=Path(__file__).parent/'fixtures'/'pi_fake_runtime.mjs'
TOOL={'name':'echo','description':'echo','parameters':{'type':'object','properties':{'value':{'type':'string'}},'required':['value'],'additionalProperties':False}}

class PiBudgetFinalizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from quantlab.devstudio.pi_provider import resolve_pi
        import shutil
        cls.node=shutil.which('node')
        if not cls.node:
            try:cls.node=resolve_pi()[0]
            except ModelError:pass
        if not cls.node: raise unittest.SkipTest('Node required for bridge tests')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.trace_path=Path(self.tmp.name)/'trace.jsonl';self.events=[];self.calls=[]
        self.patcher=patch('quantlab.devstudio.pi_provider.resolve_pi',return_value=(self.node,str(FIXTURE)))
        self.patcher.start();self.addCleanup(self.patcher.stop)
    def run_pi(self,scenario='normal',rounds=3,tool_budget=4,context_budget=20000,host_result=None):
        cfg=ModelConfig(provider='pi_sdk',model='fake/unit',timeout_seconds=10,max_rounds=rounds,
                        max_tool_calls=tool_budget,max_context_chars=context_budget)
        def dispatch(name,args,call_id):
            self.calls.append((name,args,call_id))
            if host_result:return host_result
            if scenario=='context_overflow':return {'ok':True,'data':'z'*10000}
            return {'ok':True,'data':args['value']}
        with patch.dict('os.environ',{'PI_FAKE_TRACE':str(self.trace_path)}):
            return PiProvider(cfg).run('SCENARIO:'+scenario,[{'role':'user','content':'review existing work'}],
                [TOOL],dispatch,lambda k,v:self.events.append((k,v)),Event())
    def stopped(self,*args,**kwargs):
        with self.assertRaises(PiBudgetStopped) as caught:self.run_pi(*args,**kwargs)
        error=caught.exception
        self.assertEqual(error.termination,'budget_stopped')
        self.assertTrue(error.needs_followup)
        self.assertTrue(error.reason)
        self.assertTrue(error.result['text'].strip())
        if error.reason in ('no_final_answer','model_requested_tools_during_finalization','context_budget_exhausted','round_budget_exhausted'):
            self.assertIn('[Pi budget stop:',error.result['text'])
        self.assertIn(('pi_budget_stop',{'termination':'budget_stopped','needs_followup':True,'reason':error.reason}),self.events)
        return error.result
    def trace(self):return [json.loads(x) for x in self.trace_path.read_text().splitlines()]
    def test_max_rounds_one_allows_final_answer_without_tools(self):
        result=self.stopped(rounds=1)
        self.assertEqual(result['reason'],'round_budget_finalization');self.assertEqual(result['tool_calls'],0)
        self.assertEqual(self.trace()[0]['tools'],0)
        self.assertEqual(result['usage'],{'input':2,'output':3,'totalTokens':5})
    def test_tool_then_exact_last_round_finalization(self):
        with self.assertRaises(PiBudgetStopped) as caught:self.run_pi('once',rounds=2,tool_budget=1)
        result=caught.exception.result
        self.assertEqual(result['termination'],'budget_stopped');self.assertEqual(result['reason'],'tool_budget_exhausted');self.assertEqual(len(self.calls),1)
        self.assertEqual([row['tools'] for row in self.trace()],[1,0])
        self.assertEqual(result['usage'],{'input':4,'output':6,'totalTokens':10})
    def test_multi_action_over_budget_pairs_blocked_call_without_dispatch(self):
        with self.assertRaises(PiBudgetStopped) as caught:self.run_pi('multi',rounds=3,tool_budget=1)
        result=caught.exception.result
        self.assertEqual(result['termination'],'budget_stopped');self.assertEqual(len(self.calls),1)
        rows=self.trace();last=rows[-1]
        self.assertEqual(last['tools'],0)
        self.assertTrue(any(m.get('toolCallId')=='two' and 'PI_TOOL_BUDGET_BLOCKED' in m['content'][0]['text'] for m in last['messages']))
        self.assertEqual(result['reason'],'tool_budget_exhausted')
    def test_model_ignoring_no_tools_is_blocked_and_stops(self):
        result=self.stopped('ignore',rounds=1)
        self.assertEqual(len(self.calls),0)
        self.assertEqual(result['reason'],'model_requested_tools_during_finalization')
    def test_empty_finalization_returns_deterministic_recovery_status(self):
        result=self.stopped('empty',rounds=1)
        self.assertEqual(result['reason'],'no_final_answer')
    def test_host_context_budget_transitions_to_no_tools_finalization(self):
        result=self.stopped('host_context',rounds=3,host_result={'ok':False,'error':{'code':'TOOL_CONTEXT_BUDGET_EXHAUSTED','message':'bounded'}})
        self.assertEqual(len(self.calls),1)
        self.assertEqual([row['tools'] for row in self.trace()],[1,0])
        self.assertEqual(result['reason'],'tool_context_budget_exhausted')
    def test_host_failure_limit_transitions_to_no_tools_finalization(self):
        result=self.stopped('host_failure',rounds=3,host_result={'ok':False,'error':{'code':'TOOL_FAILURE_LIMIT','message':'bounded'}})
        self.assertEqual([row['tools'] for row in self.trace()],[1,0])
        self.assertEqual(result['reason'],'tool_failure_limit')
    def test_context_exhaustion_returns_recoverable_budget_stop(self):
        result=self.stopped('context_overflow',rounds=3,context_budget=5000)
        self.assertEqual(result['reason'],'context_budget_exhausted')
        self.assertEqual(len(self.calls),1)
    def test_host_stop_blocks_remaining_actions_in_same_batch(self):
        for code in ('TOOL_CONTEXT_BUDGET_EXHAUSTED','TOOL_FAILURE_LIMIT','TOOL_BUDGET_EXHAUSTED'):
            self.calls=[];self.events=[]
            result=self.stopped('multi',rounds=3,tool_budget=4,host_result={'ok':False,'error':{'code':code}})
            self.assertEqual(len(self.calls),1)
            self.assertEqual(result['reason'],code.lower())
            self.assertEqual(self.trace()[-1]['tools'],0)
            self.assertTrue(any(m.get('toolCallId')=='two' and 'PI_TOOL_BUDGET_BLOCKED' in m['content'][0]['text'] for m in self.trace()[-1]['messages']))
    def test_forced_last_round_is_partial_even_with_remaining_tool_allowance(self):
        result=self.stopped('once',rounds=2,tool_budget=4)
        self.assertEqual(result['reason'],'round_budget_finalization');self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.trace()),2)
    def test_normal_completion_metadata(self):
        result=self.run_pi()
        self.assertEqual(result['termination'],'completed');self.assertFalse(result['needs_followup'])
        self.assertIsNone(result['reason']);self.assertIn('completed normally',result['text'])
    def test_non_budget_protocol_failure_stays_fail_closed(self):
        # Unknown calls and same-batch duplicate IDs must not be treated as budget fallback.
        with self.assertRaisesRegex(ModelError,'Unknown or duplicate'):self.run_pi('unknown',rounds=2)
        self.assertEqual(self.calls,[])
        with self.assertRaisesRegex(ModelError,'Unknown or duplicate'):self.run_pi('duplicate_batch',rounds=2)
        self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()
