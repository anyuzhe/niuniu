import json,tempfile,unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path

from quantlab.agent.pit_evidence_cli import main as pit_cli
from quantlab.data.pit_evidence import archive_pit_evidence,list_pit_evidence,verify_pit_statements


class PITEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'artifacts';self.data=self.root/'data'
        self.output.mkdir();self.data.mkdir();self.document=self.root/'official.html';self.document.write_text('official PIT fixture bytes')
        self.source='https://www.cninfo.com.cn/new/disclosure/stock?stockCode=600000'
        self.industry={'symbol':'sh.600000','sector':'银行','effective_at':'2025-01-01T15:00:00+08:00',
            'available_at':'2025-01-02T09:00:00+08:00','source':self.source}

    def test_archive_is_idempotent_and_verifies_document_bytes(self):
        first=archive_pit_evidence(self.data,'industry_membership',[self.industry],self.source,
            '2025-01-02T08:00:00+08:00',self.document,confirm_publication_time=True)
        second=archive_pit_evidence(self.data,'industry_membership',[self.industry],self.source,
            '2025-01-02T08:00:00+08:00',self.document,confirm_publication_time=True)
        self.assertEqual(first['created'],1);self.assertEqual(second['created'],0)
        self.assertEqual(list_pit_evidence(self.data)['records'],1)
        self.assertTrue(verify_pit_statements(self.data,'industry_membership',[self.industry])['verified'])

    def test_tampered_document_and_receipt_fail_closed(self):
        result=archive_pit_evidence(self.data,'industry_membership',[self.industry],self.source,
            '2025-01-02T08:00:00+08:00',self.document,confirm_publication_time=True)
        saved=self.data/'research/pit_evidence/documents'/(result['document_sha256']+'.bin')
        saved.write_bytes(b'tampered')
        check=verify_pit_statements(self.data,'industry_membership',[self.industry])
        self.assertFalse(check['verified']);self.assertEqual(check['verified_statements'],0)
        # Restore document then corrupt the checksummed receipt itself.
        saved.write_text('official PIT fixture bytes')
        receipt=self.data/'research/pit_evidence/receipts.json';value=json.loads(receipt.read_text())
        value['records'][0]['published_at']='2024-01-01T00:00:00+08:00';receipt.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'checksum'):list_pit_evidence(self.data)

    def test_source_publication_and_confirmation_are_hard_gates(self):
        with self.assertRaisesRegex(ValueError,'confirm'):
            archive_pit_evidence(self.data,'industry_membership',[self.industry],self.source,
                '2025-01-02T08:00:00+08:00',self.document)
        with self.assertRaisesRegex(ValueError,'authoritative'):
            archive_pit_evidence(self.data,'industry_membership',[{**self.industry,'source':'https://example.com/x'}],
                'https://example.com/x','2025-01-02T08:00:00+08:00',self.document,confirm_publication_time=True)
        with self.assertRaisesRegex(ValueError,'precede'):
            archive_pit_evidence(self.data,'industry_membership',[self.industry],self.source,
                '2025-01-03T08:00:00+08:00',self.document,confirm_publication_time=True)

    def test_cli_archive_verify_list_and_system_health_are_host_readable(self):
        statement=self.root/'statement.json';statement.write_text(json.dumps({
            'symbol':'sh.600000','effective_at':'2025-01-01T15:00:00+08:00',
            'available_at':'2025-01-02T09:00:00+08:00','eligible':True}))
        args=['--data-root',str(self.data),'--call','archive','--kind','universe_eligibility','--statements',str(statement),
            '--source-url','https://www.sse.com.cn/assortment/stock/list/share/','--published-at','2025-01-02T08:00:00+08:00',
            '--document',str(self.document)]
        out=StringIO()
        with redirect_stdout(out):code=pit_cli(args)
        self.assertEqual(code,2);self.assertFalse(json.loads(out.getvalue())['ok'])
        out=StringIO()
        with redirect_stdout(out):code=pit_cli([*args,'--confirm-publication-time'])
        self.assertEqual(code,0);self.assertEqual(json.loads(out.getvalue())['data']['created'],1)
        out=StringIO()
        with redirect_stdout(out):code=pit_cli(['--data-root',str(self.data),'--call','list'])
        self.assertEqual(code,0);self.assertEqual(json.loads(out.getvalue())['data']['counts']['universe_eligibility'],1)
        from quantlab.agent.system_health import SystemHealthService
        health=SystemHealthService(self.output,self.data,now_fn=lambda:datetime.fromisoformat('2026-09-15T06:30:00+00:00')).build()
        pit=health['components']['pit_playbook']['evidence']['pit_evidence']
        self.assertEqual(pit['records'],1);self.assertEqual(pit['counts']['universe_eligibility'],1)


if __name__=='__main__':unittest.main()
