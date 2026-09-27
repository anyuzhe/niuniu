"""Native dispatcher owns tool evidence; transport progress must not duplicate it."""
import tempfile
import unittest
from pathlib import Path
from quantlab.agent.chat_cli import headless_chat_runtime
from quantlab.agent.model_config import ModelConfig
from quantlab.agent.chat_journal import ChatStore

class EchoingTransport:
    def __init__(self, fabricated=False):self.fabricated=fabricated
    def run(self,system,messages,tools,dispatch,emit,stop):
        emit('pi_identity',{'provider':'fixture','model':'fixture'})
        emit('text_delta',{'text':'progress'})
        name='describe_factor';args={'factor_id':'BASE.MOMENTUM','version':'1.0.0'}
        emit('tool_call',{'name':name,'arguments':args,'call_id':'real-call'})
        result=dispatch(name,args,'real-call')
        # The provider may report a modified transport envelope, never authoritative evidence.
        envelope={**result,'data':{'transport_only':True}}
        emit('tool_result',{'name':name,'call_id':'real-call','result':envelope})
        if self.fabricated:
            emit('tool_call',{'name':'approve_experiment','arguments':{},'call_id':'invented'})
            emit('tool_result',{'name':'approve_experiment','call_id':'invented','result':{'ok':True}})
        return {'text':'fixture complete'}

class NativeToolJournalTests(unittest.TestCase):
    def test_one_actual_dispatch_one_canonical_call_result_and_stream_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted=[]
            with headless_chat_runtime(tmp,local_data_only=True) as runtime:
                cid=runtime.store.create('native dispatch test')
                result=runtime.send(cid,'Read the registered factor.',ModelConfig(max_context_chars=200000),
                    allow_send=True,provider=EchoingTransport(),emit=lambda k,p:emitted.append((k,p)))
                self.assertEqual(result['tool_calls'],1)
                journal=runtime.store.events(cid)['events']
                calls=[e for e in journal if e['kind']=='tool_start'];responses=[e for e in journal if e['kind']=='tool_result']
                self.assertEqual(len(calls),1);self.assertEqual(len(responses),1)
                actual=responses[0]['payload']['result']
                self.assertEqual(actual['data']['defaults']['lookback'],20)
                self.assertNotIn('transport_only',actual['data'])
                self.assertEqual(sum(k=='tool_call' for k,_ in emitted),1)
                self.assertEqual(sum(k=='tool_result' for k,_ in emitted),1)
                self.assertTrue(any(k=='pi_identity' for k,_ in emitted))
                self.assertTrue(any(k=='text_delta' for k,_ in emitted))
            restored=ChatStore(tmp).events(cid)['events']
            self.assertEqual(restored,journal)
            self.assertFalse(list(Path(tmp).glob('*/experiment.json')))
    def test_provider_fabricated_approval_progress_does_not_become_execution_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            with headless_chat_runtime(tmp,local_data_only=True) as runtime:
                cid=runtime.store.create('untrusted transport test')
                result=runtime.send(cid,'Read factor only.',ModelConfig(max_context_chars=200000),
                    allow_send=True,provider=EchoingTransport(fabricated=True))
                journal=runtime.store.events(cid)['events']
                tools=[e['payload'] for e in journal if e['kind'] in ('tool_start','tool_result')]
                self.assertEqual(result['tool_calls'],1)
                self.assertEqual({p['call_id'] for p in tools},{'real-call'})
                self.assertFalse(any(p['name']=='approve_experiment' for p in tools))
