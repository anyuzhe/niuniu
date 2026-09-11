import json
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Event,Thread
from quantlab.agent.model_config import ModelConfig,ModelError
from quantlab.agent.http_provider import HTTPProvider


class HTTPProviderTests(unittest.TestCase):
    def server(self,replies):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path,body,self.headers.get('Authorization')))
                value=replies.pop(0)
                if value=='redirect':
                    self.send_response(307);self.send_header('Location','http://127.0.0.1:9/forbidden');self.end_headers();return
                payload=json.dumps(value).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        def close():server.shutdown();server.server_close();thread.join()
        self.addCleanup(close)
        return f'http://127.0.0.1:{server.server_port}/v1',received

    def test_chat_completions_tool_roundtrip(self):
        first={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':'call1','type':'function','function':{'name':'get_capabilities','arguments':'{}'}}]}}]}
        second={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'complete'}}]}
        url,received=self.server([first,second]);config=ModelConfig(provider='chat_completions',model='custom',effort='',base_url=url)
        calls=[]
        def invoke(name,args):calls.append((name,args));return {'ok':True,'data':{'fixture':1}}
        tools=[{'name':'get_capabilities','description':'fixture','parameters':{'type':'object','properties':{}}}]
        result=HTTPProvider(config,'fixture-key').complete([{'role':'user','content':'query'}],tools,invoke,lambda *_:None,Event())
        self.assertEqual(result['text'],'complete');self.assertEqual(calls,[('get_capabilities',{})])
        self.assertEqual(received[0][0],'/v1/chat/completions')
        self.assertEqual(received[0][2],'Bearer fixture-key')
        self.assertNotIn('fixture-key',json.dumps(received[0][1]))
        self.assertEqual(received[1][1]['messages'][-1]['tool_call_id'],'call1')
        self.assertNotIn('reasoning_effort',received[0][1])

    def test_responses_tool_roundtrip(self):
        first={'status':'completed','output':[{'type':'function_call','name':'get_capabilities',
            'call_id':'call1','arguments':'{}'}]}
        second={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'done'}]}]}
        url,received=self.server([first,second])
        config=ModelConfig(provider='responses',model='custom',effort='low',base_url=url)
        result=HTTPProvider(config).complete([{'role':'user','content':'query'}],[],lambda *_:{'ok':True},lambda *_:None,Event())
        self.assertEqual(result['text'],'done');self.assertEqual(received[0][0],'/v1/responses')
        self.assertFalse(received[0][1]['store'])
        self.assertEqual(received[1][1]['input'][-1]['type'],'function_call_output')

    def test_redirect_is_rejected_and_round_limit_applies(self):
        url,received=self.server(['redirect'])
        config=ModelConfig(provider='responses',model='custom',base_url=url)
        with self.assertRaises(ModelError):
            HTTPProvider(config,'fixture-key').complete([{'role':'user','content':'query'}],[],lambda *_:None,lambda *_:None,Event())
        self.assertEqual(len(received),1)
        repeated={'status':'completed','output':[{'type':'function_call','name':'x','call_id':'c','arguments':'{}'}]}
        url,received=self.server([repeated])
        config=ModelConfig(provider='responses',model='custom',base_url=url,max_rounds=1)
        with self.assertRaisesRegex(ModelError,'轮数'):
            HTTPProvider(config).complete([{'role':'user','content':'query'}],[],lambda *_:{'ok':True},lambda *_:None,Event())

    def test_nonfinite_tool_json_rejected_before_call(self):
        value={'status':'completed','output':[{'type':'function_call','name':'x','call_id':'c','arguments':'{"x":NaN}'}]}
        url,_=self.server([value]);calls=[]
        config=ModelConfig(provider='responses',model='custom',base_url=url)
        with self.assertRaises(ModelError):
            HTTPProvider(config).complete([{'role':'user','content':'query'}],[],lambda *v:calls.append(v),lambda *_:None,Event())
        self.assertEqual(calls,[])
