import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from uuid import uuid4

from quantlab.trading.decision_store import DecisionStore
from quantlab.workbench.server import make_server


class MobileWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.symbol='sh.600000'
        self.decision=DecisionStore(self.root).create(str(uuid4()),{'symbol':self.symbol,'trading_day':'2026-09-15',
            'frame':'R1','action':'WATCH','role_id':'human','theme':'银行','theme_role':'观察','ai_thesis':'移动端读取'})
        self.server=make_server(self.root,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def get(self,path,**kwargs):return urlopen(Request(self.url+path,**kwargs),timeout=5)
    def files(self):return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file())

    def test_mobile_static_and_json_share_decision_state_without_writes(self):
        before=self.files()
        for path in ('/mobile','/mobile.js','/mobile.css'):
            with self.get(path) as response:self.assertEqual(response.status,200);self.assertTrue(response.read())
        with self.get('/api/mobile/brief?trading_day=2026-09-15&symbol=sh.600000') as response:brief=json.load(response)
        with self.get('/api/mobile/stock?symbol=sh.600000') as response:stock=json.load(response)
        with self.get('/api/mobile/decisions?symbol=sh.600000&limit=10') as response:decisions=json.load(response)
        with self.get('/api/mobile/system-health') as response:health=json.load(response)
        after=self.files();self.assertEqual(before,after)
        self.assertEqual(brief['stock']['current_decision']['decision_id'],self.decision['decision_id'])
        self.assertEqual(stock['current_decision']['decision_id'],self.decision['decision_id'])
        self.assertEqual(decisions['records'][0]['decision_id'],self.decision['decision_id'])
        self.assertIsNone(brief['policy']['mobile_state_store']);self.assertFalse(brief['policy']['automatic_execution'])
        self.assertFalse(health['summary']['automatic_actions']);self.assertFalse((self.root/'_mobile').exists())

    def test_mobile_routes_are_loopback_only_and_have_no_write_endpoint(self):
        with self.assertRaises(HTTPError) as bad_host:self.get('/api/mobile/brief',headers={'Host':'evil.test'})
        self.assertEqual(bad_host.exception.code,403);bad_host.exception.close()
        origin=f'http://127.0.0.1:{self.server.server_port}'
        with self.assertRaises(HTTPError) as post:self.get('/api/mobile/brief',method='POST',headers={'Origin':origin})
        self.assertEqual(post.exception.code,404);post.exception.close()
        with self.assertRaises(HTTPError) as bad_symbol:self.get('/api/mobile/stock?symbol=600000')
        self.assertEqual(bad_symbol.exception.code,400);bad_symbol.exception.close()


if __name__=='__main__':unittest.main()
