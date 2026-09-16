import json
import tempfile
import unittest
from dataclasses import replace,asdict
from pathlib import Path
from threading import Event
from uuid import uuid4
from quantlab.agent.model_config import ModelConfig,ModelError,strict_json,save_model_config,load_model_config
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.conversations import ConversationStore


class FakeProvider:
    def __init__(self,actions=(),text='fixture answer'):
        self.actions=actions;self.text=text;self.called=False;self.tools=[]
    def complete(self,messages,tools,invoke,emit,stop):
        self.called=True;self.tools=[t['name'] for t in tools]
        emit('model',{'provider':'fixture','model':'fixture'})
        for name,args in self.actions:invoke(name,args)
        return {'text':self.text,'model':'fixture','provider':'fixture','usage':{}}


class ResearchChatTests(unittest.TestCase):
    def test_config_roundtrip_no_credentials_and_invalid_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=ModelConfig(model='custom-model-name',effort='high')
            save_model_config(tmp,config);self.assertEqual(load_model_config(tmp),config)
            self.assertNotIn('api_key',asdict(config))
            for changes in ({'base_url':'http://remote.test/v1'},{'base_url':'https://u:p@host/v1'},
                {'base_url':'https://host/v1?key=x'},{'max_tool_calls':True},{'provider':'unknown'}):
                with self.assertRaises(ValueError):replace(config,**changes)

    def test_strict_model_json(self):
        for text in ('{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}'):
            with self.assertRaises(ModelError):strict_json(text)
        self.assertEqual(strict_json('{"x":null}'),{'x':None})

    def test_actual_factor_tool_evidence_and_session_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=ChatRuntime(tmp);session=runtime.store.create('query')
            provider=FakeProvider([('describe_factor',{'factor_id':'BASE.MOMENTUM','version':'1.0.0'})])
            result=runtime.run(session,'查询动量',ModelConfig(),network_allowed=True,provider=provider)
            self.assertEqual(result['status'],'completed');self.assertEqual(result['tool_calls'],1)
            self.assertEqual(result['evidence'][0]['factor_id'],'BASE.MOMENTUM')
            self.assertNotIn('approve_experiment',provider.tools)
            restored=ConversationStore(tmp)
            self.assertEqual(restored.messages(session,2000)[-1]['content'],'fixture answer')
            events=restored.events(session)['events']
            actual=next(e for e in events if e['kind']=='tool_result')['payload']['result']
            self.assertEqual(actual['data']['defaults']['lookback'],20)
            self.assertFalse(list(Path(tmp).glob('*/experiment.json')))

    def test_no_implicit_network_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=ChatRuntime(tmp);session=runtime.store.create();provider=FakeProvider()
            with self.assertRaises(ModelError):runtime.run(session,'hello',ModelConfig(),provider=provider)
            self.assertFalse(provider.called)
            self.assertEqual(runtime.store.events(session)['total'],0)

    def test_repeated_proposal_idempotence_and_no_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=ChatRuntime(tmp,tmp);session=runtime.store.create()
            spec={'question':'fixture','symbols':['sh.600000','sh.600519','sz.000001'],
                'start':'2025-01-01','end':'2025-01-10','factor':'BASE.MOMENTUM',
                'parameters':{'lookback':2},'horizons':[1],'quantiles':3}
            args={'request_id':str(uuid4()),'spec_json':json.dumps(spec)}
            provider=FakeProvider([('propose_experiment',args),('propose_experiment',args)])
            result=runtime.run(session,'拟定提案',ModelConfig(),network_allowed=True,provider=provider)
            self.assertEqual(result['status'],'completed',result)
            self.assertEqual(len(runtime.api.proposals.store.list()),1)
            self.assertEqual(result['evidence'][0]['kind'],'proposal')
            self.assertFalse(list(Path(tmp).glob('_jobs/*.json')))
            self.assertFalse(list(Path(tmp).glob('*/experiment.json')))

    def test_unknown_approval_and_call_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=ChatRuntime(tmp);session=runtime.store.create()
            actions=[('approve_experiment',{}),('arbitrary_shell',{}),('delete_data',{})]
            result=runtime.run(session,'test',ModelConfig(),network_allowed=True,provider=FakeProvider(actions))
            self.assertEqual(result['status'],'completed');self.assertEqual(result['tool_calls'],3)
            session=runtime.store.create()
            actions=[('search_factors',{'query':str(i),'offset':0,'limit':1}) for i in range(3)]
            result=runtime.run(session,'test',ModelConfig(max_tool_calls=2),network_allowed=True,provider=FakeProvider(actions))
            self.assertEqual(result['status'],'failed');self.assertIn('次数',result['error'])
            events=runtime.store.events(session)['events']
            self.assertEqual(sum(e['kind']=='tool_result' for e in events),2)

    def test_stop_before_model_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=ChatRuntime(tmp);session=runtime.store.create();stop=Event();stop.set()
            provider=FakeProvider()
            result=runtime.run(session,'test',ModelConfig(),network_allowed=True,stop=stop,provider=provider)
            self.assertEqual(result['status'],'cancelled');self.assertFalse(provider.called)
            secret='fixture-secret-value';session=runtime.store.create()
            result=runtime.run(session,'never store '+secret,ModelConfig(),network_allowed=True,
                api_key=secret,provider=FakeProvider(text='echo '+secret))
            self.assertNotIn(secret,result['text'])
            for path in (Path(tmp)/'_assistant/conversations').rglob('*.json'):
                self.assertNotIn(secret,path.read_text())

    def test_context_guard_lock_and_immutable_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=ChatRuntime(tmp);session=runtime.store.create();provider=FakeProvider()
            runtime.store.append(session,'user',{'text':'x'*3000})
            with self.assertRaises(ModelError):
                runtime.run(session,'test',ModelConfig(max_context_chars=2000),network_allowed=True,provider=provider)
            self.assertFalse(provider.called)
            with runtime.store.turn_lock(session):
                with self.assertRaises(ModelError):
                    with runtime.store.turn_lock(session):pass
            path=runtime.store.folder(session)/'meta.json';before=path.read_bytes()
            with self.assertRaises(ModelError):runtime.store.write(path,{'changed':True})
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises((ValueError,ModelError)):runtime.store.folder('../escape')
