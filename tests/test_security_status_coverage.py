import hashlib,io,json,tempfile,unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.agent.security_status_coverage_cli import main as coverage_cli
from quantlab.data.pit_coverage import strict_pit_coverage
from quantlab.data.pit_evidence import archive_pit_evidence
from quantlab.data.pit_universe import PLAN_FORMAT as UNIVERSE_PLAN,archive_pit_universe
from quantlab.data.security_status import load_security_status,materialize_security_status
from quantlab.data.security_status_coverage import (PLAN_FORMAT,SecurityStatusCoverageError,
    archive_security_status_coverage,audit_security_status_coverage,security_status_chain)
from quantlab.experiments.campaign_state import read_checked

TZ=ZoneInfo('Asia/Shanghai')


class SecurityStatusCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.members=[{'symbol':'sh.600000','source_id':'sse'},
            {'symbol':'sz.000001','source_id':'szse'}]

    def _doc(self,name,payload):
        path=self.root/name;path.write_bytes(payload);return path

    def _universe(self,day):
        sources=[]
        for sid,exchange,url in (('sse','SSE','https://www.sse.com.cn/assortment/stock/list/share/'),
                ('szse','SZSE','https://www.szse.cn/market/product/stock/list/index.html')):
            path=self._doc(f'{day}-{sid}.bin',(day+sid).encode());sources.append({'source_id':sid,'exchange':exchange,
                'url':url,'published_at':day+'T08:00:00+08:00','available_at':day+'T08:10:00+08:00',
                'document':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        plan={'format':UNIVERSE_PLAN,'effective_session':day,'cutoff_at':day+'T09:10:00+08:00',
            'scope':{'market':'CN_A_SHARE','exchanges':['SSE','SZSE'],'instrument_types':['A_SHARE'],
                'completeness':'FULL_OFFICIAL_LIST'},'sources':sources,'members':self.members}
        return archive_pit_universe(self.root,plan,confirm_publication_times=True,
            confirm_semantic_mapping=True,confirm_complete_official_universe=True,
            now_fn=lambda:datetime.fromisoformat(day+'T08:20:00+08:00'))['universe_snapshot']

    def _plan(self,day,universe,states,previous=None):
        sources=[]
        for sid,exchange,url in (('sse-status','SSE','https://www.sse.com.cn/market/status/list/'),
                ('szse-status','SZSE','https://www.szse.cn/market/status/list/')):
            path=self._doc(f'{day}-{sid}.bin',(day+sid+'status').encode());sources.append({'source_id':sid,
                'exchange':exchange,'url':url,'coverage':['TRADABILITY','RISK_WARNING'],
                'published_at':day+'T08:30:00+08:00','available_at':day+'T08:35:00+08:00',
                'document':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        records=[]
        for symbol,tradable,warning in states:
            records.append({'symbol':symbol,'tradable':tradable,'risk_warning':warning,
                'source_ids':['sse-status' if symbol.startswith('sh.') else 'szse-status']})
        return {'format':PLAN_FORMAT,'effective_session':day,'cutoff_at':day+'T09:10:00+08:00',
            'universe_snapshot':universe,'previous_status_snapshot':previous,'sources':sources,'records':records}

    def _archive(self,plan,continuity=False,at=None):
        day=plan['effective_session'];return archive_security_status_coverage(self.root,plan,
            confirm_publication_times=True,confirm_semantic_mapping=True,confirm_complete_daily_status=True,
            confirm_previous_session_continuity=continuity,
            now_fn=lambda:datetime.fromisoformat(at or day+'T08:45:00+08:00'))

    def _chain(self):
        states=[('2099-01-05',[('sh.600000',True,'NONE'),('sz.000001',False,'ST')]),
            ('2099-01-06',[('sh.600000',False,'ST'),('sz.000001',True,'NONE')]),
            ('2099-01-07',[('sh.600000',False,'ST'),('sz.000001',True,'NONE')]),
            ('2099-01-08',[('sh.600000',True,'NONE'),('sz.000001',True,'NONE')])]
        receipts=[];previous=None
        for day,rows in states:
            universe=self._universe(day);receipt=self._archive(self._plan(day,universe,rows,previous),previous is not None)
            receipts.append(receipt);previous=receipt['status_snapshot']
        return receipts

    def test_complete_daily_receipts_form_explicit_enter_continue_clear_chain(self):
        receipts=self._chain();audit=audit_security_status_coverage(self.root)
        self.assertEqual(audit['verified_receipts'],4);self.assertEqual(audit['invalid_receipts'],0)
        self.assertEqual(audit['continuous_links'],3);self.assertEqual(audit['strict_continuous_links'],3)
        self.assertEqual(audit['chain_roots'],1)
        self.assertGreaterEqual(audit['transition_counts']['SUSPENSION_ENTERED'],1)
        self.assertGreaterEqual(audit['transition_counts']['SUSPENSION_CONTINUED'],1)
        self.assertGreaterEqual(audit['transition_counts']['SUSPENSION_CLEARED'],1)
        self.assertGreaterEqual(audit['transition_counts']['RISK_WARNING_ENTERED'],1)
        self.assertGreaterEqual(audit['transition_counts']['RISK_WARNING_CONTINUED'],1)
        self.assertGreaterEqual(audit['transition_counts']['RISK_WARNING_CLEARED'],1)
        chain=security_status_chain(self.root,'sh.600000');self.assertEqual(chain['observations'],4)
        self.assertEqual(chain['records'][0]['risk_warning_transition'],'INITIAL_RISK_WARNING')
        self.assertFalse(chain['records'][0]['transition_strict_pit_eligible'])
        self.assertEqual(chain['records'][1]['risk_warning_transition'],'RISK_WARNING_ENTERED')
        self.assertTrue(chain['records'][1]['transition_strict_pit_eligible'])
        self.assertEqual(chain['records'][1]['tradability_transition'],'SUSPENSION_ENTERED')
        self.assertEqual(chain['records'][1]['previous_status_snapshot'],receipts[0]['status_snapshot'])
        self.assertEqual(chain['records'][2]['risk_warning_transition'],'RISK_WARNING_CONTINUED')
        self.assertEqual(chain['records'][2]['tradability_transition'],'SUSPENSION_CONTINUED')
        self.assertEqual(chain['records'][3]['risk_warning_transition'],'RISK_WARNING_CLEARED')
        self.assertEqual(chain['records'][3]['tradability_transition'],'SUSPENSION_CLEARED')
        coverage=strict_pit_coverage(self.root)
        inventory=coverage['strict_evidence']['security_status_coverage_archive']
        self.assertEqual(inventory['verified_receipts'],4)
        self.assertNotIn('NO_COMPLETE_DAILY_SECURITY_STATUS_RECEIPTS',{row['code'] for row in coverage['gaps']})

    def test_materialization_marks_complete_rows_and_is_bound_to_receipts(self):
        self._chain();result=materialize_security_status(self.root);self.assertEqual(result['rows'],8)
        self.assertEqual(result['daily_coverage_snapshots'],4)
        frame,manifest=load_security_status(self.root);self.assertTrue(frame['coverage_complete'].all())
        self.assertEqual(frame['status_snapshot'].n_unique(),4);self.assertEqual(manifest['daily_coverage_snapshots'],4)
        self.assertTrue(all(value.startswith('security_status_coverage:') for value in manifest['evidence_ids']))

    def test_sparse_statement_merges_only_at_same_effective_time_and_conflicts_fail(self):
        day='2099-01-20';universe=self._universe(day)
        self._archive(self._plan(day,universe,[('sh.600000',True,'NONE'),('sz.000001',True,'NONE')]))
        document=self._doc('sparse-status.pdf',b'%PDF sparse official status');url='https://www.sse.com.cn/test/status.pdf'
        base={'symbol':'sh.600000','effective_at':day+'T09:30:00+08:00',
            'available_at':day+'T08:40:00+08:00','tradable':True,'risk_warning':'NONE','source':url}
        archive_pit_evidence(self.root,'security_status',[base],url,day+'T08:30:00+08:00',document,
            confirm_publication_time=True)
        built=materialize_security_status(self.root);self.assertEqual(built['rows'],2)
        frame,manifest=load_security_status(self.root);self.assertEqual(frame.height,2);self.assertEqual(len(manifest['evidence_ids']),2)
        conflict={**base,'available_at':day+'T08:41:00+08:00','risk_warning':'ST'}
        archive_pit_evidence(self.root,'security_status',[conflict],url,day+'T08:31:00+08:00',document,
            confirm_publication_time=True)
        with self.assertRaisesRegex(ValueError,'conflicts with verified sparse statement'):
            materialize_security_status(self.root)

    def test_confirmation_source_scope_and_document_hash_fail_closed(self):
        day='2099-01-25';universe=self._universe(day)
        plan=self._plan(day,universe,[('sh.600000',True,'NONE'),('sz.000001',True,'NONE')])
        with self.assertRaisesRegex(SecurityStatusCoverageError,'confirm every publication'):
            archive_security_status_coverage(self.root,plan)
        wrong_host=json.loads(json.dumps(plan));wrong_host['sources'][0]['url']='https://www.szse.cn/wrong/source'
        with self.assertRaisesRegex(SecurityStatusCoverageError,'host must match'):
            self._archive(wrong_host)
        incomplete=json.loads(json.dumps(plan));incomplete['sources'][0]['coverage']=['TRADABILITY']
        with self.assertRaisesRegex(SecurityStatusCoverageError,'complete tradability and risk-warning'):
            self._archive(incomplete)
        Path(plan['sources'][0]['document']).write_bytes(b'tampered after plan')
        with self.assertRaisesRegex(SecurityStatusCoverageError,'does not match plan sha256'):
            self._archive(plan)

    def test_missing_member_broken_link_and_late_archive_fail_closed(self):
        day='2099-02-01';universe=self._universe(day)
        plan=self._plan(day,universe,[('sh.600000',True,'NONE')])
        with self.assertRaisesRegex(SecurityStatusCoverageError,'exactly match Universe members'):
            self._archive(plan)
        complete=self._plan(day,universe,[('sh.600000',True,'NONE'),('sz.000001',True,'NONE')])
        with self.assertRaisesRegex(SecurityStatusCoverageError,'no later than cutoff'):
            self._archive(complete,at=day+'T09:11:00+08:00')
        complete['previous_status_snapshot']='0'*64
        with self.assertRaisesRegex(SecurityStatusCoverageError,'missing, invalid'):
            self._archive(complete,continuity=True)

    def test_branching_adjacent_session_claim_is_rejected_and_legacy_branch_is_reported(self):
        day='2099-02-10';universe=self._universe(day)
        first=self._archive(self._plan(day,universe,[('sh.600000',True,'NONE'),('sz.000001',True,'NONE')]))
        next_universe=self._universe('2099-02-11');successor=self._archive(self._plan('2099-02-11',next_universe,
            [('sh.600000',True,'NONE'),('sz.000001',True,'NONE')],first['status_snapshot']),True)
        third_universe=self._universe('2099-02-12');third_plan=self._plan('2099-02-12',third_universe,
            [('sh.600000',True,'NONE'),('sz.000001',True,'NONE')],first['status_snapshot'])
        with self.assertRaisesRegex(SecurityStatusCoverageError,'already has a different confirmed successor'):
            self._archive(third_plan,True)
        successor_path=Path(successor['path']);hidden=self.root/'hidden-successor.json';successor_path.replace(hidden)
        self._archive(third_plan,True);hidden.replace(successor_path)
        audit=audit_security_status_coverage(self.root)
        self.assertEqual(audit['branching_previous_snapshots'],[first['status_snapshot']])
        with self.assertRaisesRegex(ValueError,'branching previous-session'):
            materialize_security_status(self.root)
        with self.assertRaisesRegex(SecurityStatusCoverageError,'ambiguous session or branching'):
            security_status_chain(self.root,'sh.600000')

    def test_unknown_is_covered_but_not_strict_and_receipt_tamper_is_detected(self):
        day='2099-03-01';universe=self._universe(day)
        result=self._archive(self._plan(day,universe,[('sh.600000',True,'UNKNOWN'),('sz.000001',True,'NONE')]))
        self.assertFalse(result['strict_pit_eligible'])
        audit=audit_security_status_coverage(self.root);self.assertEqual(audit['strict_pit_eligible_receipts'],0)
        coverage=strict_pit_coverage(self.root)
        self.assertIn('NON_STRICT_SECURITY_STATUS_COVERAGE_RECEIPTS',{row['code'] for row in coverage['gaps']})
        path=Path(result['path']);receipt=read_checked(path);document=self.root/receipt['sources'][0]['document']['path']
        original=document.read_bytes();document.write_bytes(b'tampered archived document')
        audit=audit_security_status_coverage(self.root);self.assertEqual(audit['invalid_receipts'],1)
        document.write_bytes(original);self.assertEqual(audit_security_status_coverage(self.root)['verified_receipts'],1)
        value=json.loads(path.read_text());value['checksum']='0'*64;path.write_text(json.dumps(value))
        audit=audit_security_status_coverage(self.root);self.assertEqual(audit['verified_receipts'],0);self.assertEqual(audit['invalid_receipts'],1)

    def test_idempotent_archive_and_read_only_cli_audit(self):
        day='2099-04-01';universe=self._universe(day)
        plan=self._plan(day,universe,[('sh.600000',True,'NONE'),('sz.000001',True,'NONE')])
        first=self._archive(plan);second=self._archive(plan,at=day+'T09:30:00+08:00')
        self.assertTrue(first['created']);self.assertFalse(second['created'])
        alternative=self._plan(day,universe,[('sh.600000',False,'ST'),('sz.000001',True,'NONE')])
        with self.assertRaisesRegex(SecurityStatusCoverageError,'different status snapshot already exists'):
            self._archive(alternative)
        stream=io.StringIO()
        with redirect_stdout(stream):code=coverage_cli(['--data-root',str(self.root),'--call','audit'])
        self.assertEqual(code,0);payload=json.loads(stream.getvalue());self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['verified_receipts'],1)


if __name__=='__main__':unittest.main()
