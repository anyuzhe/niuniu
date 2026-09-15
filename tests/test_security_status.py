import tempfile
import io,json
from contextlib import redirect_stdout
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.data.pit_evidence import archive_pit_evidence,normalize_statement,verify_pit_statements
from quantlab.data.security_status import SecurityStatusHistory,load_security_status,materialize_security_status
from quantlab.agent.security_status_cli import main as security_status_cli


class SecurityStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.doc=self.root/'official.pdf';self.doc.write_bytes(b'%PDF official status fixture')
        self.url='https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-03-27/example.PDF'
        self.available='2026-03-27T22:02:58+08:00'
        self.rows=[
            {'symbol':'sz.002538','effective_at':'2026-03-30T09:30:00+08:00','available_at':self.available,
             'tradable':False,'risk_warning':'NONE','source':self.url},
            {'symbol':'sz.002538','effective_at':'2026-03-31T09:30:00+08:00','available_at':self.available,
             'tradable':True,'risk_warning':'ST','source':self.url},
        ]

    def archive(self):
        return archive_pit_evidence(self.root,'security_status',self.rows,self.url,self.available,self.doc,
            confirm_publication_time=True)

    def test_verified_status_materializes_and_queries_without_price_limit_inference(self):
        result=self.archive();self.assertEqual(result['created'],2)
        self.assertTrue(verify_pit_statements(self.root,'security_status',self.rows)['verified'])
        built=materialize_security_status(self.root);self.assertEqual(built['rows'],2)
        frame,manifest=load_security_status(self.root);self.assertEqual(frame.height,2)
        self.assertNotIn('limit_rate',frame.columns);self.assertNotIn('price_limit',frame.columns)
        history=SecurityStatusHistory(self.rows);tz=ZoneInfo('Asia/Shanghai')
        before=history.at('sz.002538',datetime(2026,3,30,12,tzinfo=tz))
        after=history.at('sz.002538',datetime(2026,3,31,12,tzinfo=tz))
        self.assertFalse(before['tradable']);self.assertEqual(before['risk_warning'],'NONE')
        self.assertTrue(after['tradable']);self.assertEqual(after['risk_warning'],'ST')
        self.assertIn('no price-limit inference',manifest['scope'])

    def test_host_cli_materializes_and_reads_without_network(self):
        self.archive();stream=io.StringIO()
        with redirect_stdout(stream):code=security_status_cli(['--data-root',str(self.root),'--call','materialize'])
        self.assertEqual(code,0);payload=json.loads(stream.getvalue());self.assertEqual(payload['data']['rows'],2)
        stream=io.StringIO()
        with redirect_stdout(stream):code=security_status_cli(['--data-root',str(self.root),'--call','status'])
        self.assertEqual(code,0);payload=json.loads(stream.getvalue());self.assertTrue(payload['data']['configured'])
        self.assertEqual(payload['data']['symbols'],1)

    def test_future_known_and_risk_warning_contract_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'known no later'):
            normalize_statement('security_status',{**self.rows[0],
                'effective_at':'2026-03-27T21:00:00+08:00'})
        with self.assertRaisesRegex(ValueError,'NONE/ST/STAR_ST/UNKNOWN'):
            normalize_statement('security_status',{**self.rows[0],'risk_warning':'risk'})


if __name__=='__main__':unittest.main()
