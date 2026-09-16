import json
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from quantlab.agent.codex_provider import CodexProvider
from quantlab.agent.model_config import ModelConfig,ModelError,strict_json


class Connection:
    def __init__(self,events):self.events=list(events);self.sent=[];self.requests=[];self.closed=False;self.warnings=[];self.directory=SimpleNamespace(name='/fixture')
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def rpc(self,method,params):
        self.requests.append((method,params))
        if method=='account/read':return {'account':{'type':'chatgpt'}}
        if method=='thread/start':return {'thread':{'id':'t'},'model':'configured'}
        if method=='turn/start':return {'turn':{'id':'u'}}
        raise AssertionError(method)
    def event(self):return self.events.pop(0)
    def send(self,value):self.sent.append(value)


def tool(call_id='one',method='item/tool/call'):
    return {'id':77,'method':method,'params':{'threadId':'t','turnId':'u','callId':call_id,'tool':'get_capabilities','arguments':{}}}
FINAL=[{'method':'item/completed','params':{'item':{'type':'agentMessage','text':'done'}}},
    {'method':'turn/completed','params':{'turn':{'id':'u','status':'completed'}}}]


class CodexProtocolTests(unittest.TestCase):
    def run_with(self,connection,calls,**kw):
        cfg=ModelConfig(model='configured',**kw)
        with patch('quantlab.agent.codex_provider.CodexTransport',return_value=connection):
            return CodexProvider(cfg).run('system',[],[],lambda *a:calls.append(a) or {'ok':True},lambda *_:None,Event())
    def test_dynamic_tool_and_readonly_thread(self):
        connection=Connection([tool(),*FINAL]);calls=[]
        result=self.run_with(connection,calls)
        self.assertEqual(result['text'],'done');self.assertTrue(connection.closed)
        self.assertEqual(calls,[('get_capabilities',{},'one')])
        params=next(v for k,v in connection.requests if k=='thread/start')
        self.assertEqual(params['sandbox'],'read-only');self.assertEqual(params['approvalPolicy'],'untrusted')
        self.assertTrue(params['ephemeral']);self.assertEqual(params['model'],'configured')
        self.assertEqual(connection.sent[0]['result']['contentItems'][0]['type'],'inputText')
    def test_nonresearch_request_is_not_approved(self):
        c=Connection([tool(method='item/commandExecution/requestApproval')]);calls=[]
        with self.assertRaises(ModelError):self.run_with(c,calls)
        self.assertEqual(calls,[]);self.assertIn('error',c.sent[0]);self.assertTrue(c.closed)
    def test_duplicate_call_is_rejected(self):
        c=Connection([tool(),tool()]);calls=[]
        with self.assertRaises(ModelError):self.run_with(c,calls)
        self.assertEqual(len(calls),1);self.assertTrue(c.closed)
    def test_tool_budget_refusal_still_allows_final_answer(self):
        c=Connection([tool(),tool('two'),*FINAL]);calls=[]
        result=self.run_with(c,calls,max_tool_calls=1)
        self.assertEqual(result['text'],'done');self.assertEqual(len(calls),1);self.assertTrue(c.closed)
        blocked=json.loads(c.sent[1]['result']['contentItems'][0]['text'])
        self.assertFalse(c.sent[1]['result']['success'])
        self.assertEqual(blocked['error']['code'],'TOOL_BUDGET_EXHAUSTED')
    def test_json_overflow_rejected(self):
        with self.assertRaises(ModelError):strict_json('{"value":1e999}')
