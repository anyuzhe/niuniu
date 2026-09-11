import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch
from quantlab.agent.model_config import ModelConfig,ModelError
from quantlab.agent.codex_options import codex_command
from quantlab.agent.codex_provider import CodexProvider


class TransportFixture:
    def __init__(self,events):
        self.events=iter(events);self.requests=[];self.sent=[];self.warnings=[]
        self.directory=type('Directory',(),{'name':'/fixture'})()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def rpc(self,method,params):
        self.requests.append((method,params))
        if method=='account/read':return {'account':{'type':'chatgpt'}}
        if method=='model/list':return {'data':[{'model':'actual-default','isDefault':True}]}
        if method=='thread/start':return {'thread':{'id':'thread'},'model':'actual-default'}
        if method=='turn/start':return {'turn':{'id':'turn'}}
        raise AssertionError(method)
    def send(self,value):self.sent.append(value)
    def event(self):return next(self.events)


class CodexProviderTests(unittest.TestCase):
    def test_dynamic_tool_roundtrip_uses_default_model(self):
        events=[{'id':100,'method':'item/tool/call','params':{'threadId':'thread','turnId':'turn',
            'tool':'get_capabilities','arguments':{}}},
            {'method':'item/agentMessage/delta','params':{'itemId':'message','delta':'done'}},
            {'method':'item/completed','params':{'item':{'id':'message','type':'agentMessage','phase':'final_answer','text':'done'}}},
            {'method':'turn/completed','params':{'turn':{'id':'turn','status':'completed'}}}]
        transport=TransportFixture(events);called=[]
        def invoke(name,args):called.append((name,args));return {'ok':True,'data':{}}
        with patch('quantlab.agent.codex_provider.CodexTransport',return_value=transport):
            result=CodexProvider(ModelConfig()).complete([{'role':'system','content':'fixture'}],[],invoke,lambda *_:None,Event())
        self.assertEqual(result['text'],'done');self.assertEqual(result['model'],'actual-default')
        self.assertEqual(called,[('get_capabilities',{})])
        self.assertTrue(transport.sent[0]['result']['success'])
        start=next(params for name,params in transport.requests if name=='thread/start')
        self.assertEqual(start['sandbox'],'read-only');self.assertEqual(start['approvalPolicy'],'untrusted')
        self.assertTrue(start['ephemeral'])

    def test_approval_requests_and_foreign_turns_fail_closed(self):
        for event in ({'id':99,'method':'item/commandExecution/requestApproval','params':{}},
            {'id':99,'method':'item/tool/call','params':{'threadId':'other','turnId':'turn','tool':'x','arguments':{}}}):
            transport=TransportFixture([event]);called=[]
            with patch('quantlab.agent.codex_provider.CodexTransport',return_value=transport):
                with self.assertRaises(ModelError):
                    CodexProvider(ModelConfig()).complete([{'role':'system','content':'x'}],[],lambda *x:called.append(x),lambda *_:None,Event())
            self.assertEqual(called,[])
            if transport.sent:self.assertIn('error',transport.sent[0])

    def test_process_overrides_preserve_global_file_and_disable_other_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'config.toml'
            content='[agents]\nenabled=true\ndefault_subagent_model="legacy"\n[mcp_servers.test-server]\ncommand="fixture"\n'
            source.write_text(content)
            with patch.dict('os.environ',{'CODEX_HOME':tmp}),patch.object(ModelConfig,'executable',return_value='/fixture/codex'):
                command,warnings=codex_command(ModelConfig())
            self.assertIn('agents.enabled={}',command)
            self.assertIn('agents.default_subagent_model={}',command)
            self.assertIn('mcp_servers.test-server.enabled=false',command)
            self.assertIn('features.shell_tool=false',command)
            self.assertIn('features.multi_agent=false',command)
            self.assertEqual(command[-3:],['app-server','--listen','stdio://'])
            self.assertEqual(source.read_text(),content);self.assertEqual(len(warnings),2)

    def test_missing_auth_and_unsupported_side_effect_stop(self):
        transport=TransportFixture([{'method':'item/started','params':{'item':{'type':'commandExecution'}}}])
        with patch('quantlab.agent.codex_provider.CodexTransport',return_value=transport):
            with self.assertRaisesRegex(ModelError,'能力'):
                CodexProvider(ModelConfig()).complete([{'role':'system','content':'x'}],[],lambda *_:None,lambda *_:None,Event())
