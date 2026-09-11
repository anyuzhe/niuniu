import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch
from quantlab.agent.model_config import ModelConfig,ModelError,ChatStopped,strict_json,save_model_config,load_model_config
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.codex_options import codex_command,DISABLED
from quantlab.agent.http_provider import HTTPProvider

SPEC={'question':'fixture','symbols':['sh.600000','sh.600519','sz.000001'],
    'start':'2024-01-01','end':'2024-06-30','factor':'BASE.MOMENTUM',
    'parameters':{'lookback':20},'mode':'single','horizons':[1,5],'quantiles':3}


class FakeProvider:
    def __init__(self,actions=(),text='研究结果'):self.actions=actions;self.text=text;self.messages=None;self.results=[]
    def run(self,system,messages,tools,dispatch,emit,stop):
        self.messages=messages
        for i,(name,args) in enumerate(self.actions):self.results.append(dispatch(name,args,str(i)))
        return {'text':self.text,'model':'fixture','provider':'fixture','tool_calls':len(self.actions),'usage':{}}


class ChatTests(unittest.TestCase):
    def test_config_roundtrip_and_secret_not_in_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=ModelConfig(model='user-custom-model',effort='high')
            save_model_config(tmp,cfg);self.assertEqual(load_model_config(tmp),cfg)
            self.assertNotIn('api_key"',(Path(tmp)/'_assistant/model.json').read_text())
        for kw in ({'provider':'other'},{'timeout_seconds':True},{'max_tool_calls':0},
            {'base_url':'http://remote.example/v1'},{'base_url':'https://key:secret@example.test/v1'},
            {'provider':'responses','model':''}):
            with self.assertRaises(ValueError):ModelConfig(**kw)
    def test_json_rejects_duplicates_and_nonfinite(self):
        for value in ('{"a":1,"a":2}','{"n":NaN}','{"n":Infinity}'):
            with self.assertRaises(ModelError):strict_json(value)
    def test_codex_process_overrides_preserve_global_config(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'CODEX_HOME':tmp}):
            path=Path(tmp)/'config.toml';source='[agents]\nenabled = true\ndefault_subagent_model="old"\n[mcp_servers.demo]\ncommand="unused"\n'
            path.write_text(source);command,warnings=codex_command(ModelConfig(codex_path=sys.executable))
            self.assertEqual(path.read_text(),source);self.assertIn('agents.enabled={}',command)
            self.assertIn('mcp_servers.demo.enabled=false',command)
            self.assertTrue(all('features.'+name+'=false' in command for name in DISABLED))
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',command)
    def test_consent_required_before_provider_and_turn_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=ChatRuntime(tmp);cid=r.store.create();p=FakeProvider()
            with self.assertRaises(ModelError):r.send(cid,'hello',ModelConfig(),provider=p)
            self.assertIsNone(p.messages);self.assertEqual(r.store.turns(cid),[])
    def test_real_tool_evidence_persists_and_history_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=ChatRuntime(tmp);cid=r.store.create()
            result=r.send(cid,'查动量',ModelConfig(),allow_send=True,
                provider=FakeProvider([('search_factors',{'query':'MOMENTUM','offset':0,'limit':5})]))
            self.assertTrue(result['evidence']);self.assertEqual(r.store.turns(cid)[0]['status'],'completed')
            new=ChatRuntime(tmp);p=FakeProvider()
            new.send(cid,'继续讨论',ModelConfig(),allow_send=True,provider=p)
            self.assertEqual([m['role'] for m in p.messages],['user','assistant','user'])
            self.assertEqual(len(new.store.turns(cid)),2)
    def test_proposals_have_host_ids_and_do_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=ChatRuntime(tmp,tmp);cid=r.store.create();args={'request_id':'model-made-id','spec_json':json.dumps(SPEC)}
            p=FakeProvider([('propose_experiment',args),('propose_experiment',{**args,'request_id':'another'})])
            result=r.send(cid,'生成提案',ModelConfig(),allow_send=True,provider=p)
            self.assertTrue(all(v['ok'] for v in p.results))
            self.assertEqual(p.results[0]['data']['proposal_id'],p.results[1]['data']['proposal_id'])
            self.assertEqual(len(r.api.proposals.store.list()),1)
            self.assertFalse((Path(tmp)/'_jobs').exists());self.assertEqual(result['tool_calls'],2)
    def test_unknown_approval_and_budget_never_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=ChatRuntime(tmp,tmp);cid=r.store.create();p=FakeProvider([('approve_proposal',{})])
            r.send(cid,'approve',ModelConfig(),allow_send=True,provider=p)
            self.assertFalse(p.results[0]['ok']);self.assertFalse((Path(tmp)/'_jobs').exists())
            p=FakeProvider([('get_capabilities',{}),('get_capabilities',{})])
            with self.assertRaises(ModelError):r.send(cid,'budget',ModelConfig(max_tool_calls=1),allow_send=True,provider=p)
    def test_stop_lock_and_key_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=ChatRuntime(tmp);cid=r.store.create();stop=Event();stop.set()
            with self.assertRaises(ChatStopped):r.send(cid,'stop',ModelConfig(),allow_send=True,stop=stop,provider=FakeProvider())
            self.assertEqual(r.store.turns(cid)[-1]['status'],'stopped')
            with r.store.lease(cid),self.assertRaises(ModelError):
                r.send(cid,'busy',ModelConfig(),allow_send=True,provider=FakeProvider())
            value=r.send(cid,'hello',ModelConfig(),api_key='my-secret-fixture',allow_send=True,
                provider=FakeProvider(text='my-secret-fixture'))
            self.assertNotIn('my-secret-fixture',json.dumps(value))
            self.assertNotIn('my-secret-fixture',json.dumps(r.store.turns(cid)))
    def test_http_protocols_preserve_tool_result_ids(self):
        for protocol in ('responses','chat_completions'):
            with self.subTest(protocol=protocol):
                p=HTTPProvider(ModelConfig(provider=protocol,model='custom',effort=''))
                if protocol=='responses':
                    replies=[{'status':'completed','output':[{'type':'function_call','call_id':'abc','name':'test','arguments':'{}'}]},
                        {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'done'}]}]}]
                else:
                    replies=[{'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[
                        {'id':'abc','type':'function','function':{'name':'test','arguments':'{}'}}]}}]},
                        {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'done'}}]}]
                calls=[]
                with patch.object(p,'request',side_effect=replies) as request:
                    result=p.run('system',[{'role':'user','content':'go'}],[],
                        lambda *a:calls.append(a) or {'ok':True},lambda *_:None,Event())
                self.assertEqual(result['text'],'done');self.assertEqual(calls,[('test',{},'abc')])
                body=request.call_args.args[1];wire=body['input' if protocol=='responses' else 'messages']
                self.assertTrue(any(v.get('call_id',v.get('tool_call_id'))=='abc' and
                    v.get('type',v.get('role')) in ('function_call_output','tool') for v in wire))
    def test_http_stop_after_response_prevents_tool_execution(self):
        p=HTTPProvider(ModelConfig(provider='responses',model='custom'));stop=Event();calls=[]
        def response(*_):stop.set();return {'output':[],'status':'completed'}
        with patch.object(p,'request',side_effect=response),self.assertRaises(ChatStopped):
            p.run('system',[],[],lambda *a:calls.append(a),lambda *_:None,stop)
        self.assertEqual(calls,[])
    def test_http_round_budget_and_duplicate_call_rejected(self):
        p=HTTPProvider(ModelConfig(provider='responses',model='custom',max_rounds=1))
        reply={'output':[{'type':'function_call','call_id':'a','name':'x','arguments':'{}'}]}
        with patch.object(p,'request',return_value=reply),self.assertRaises(ModelError):
            p.run('system',[],[],lambda *_:{'ok':True},lambda *_:None,Event())
