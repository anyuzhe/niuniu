from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json,tempfile,unittest

from quantlab.data.official_rule_reference import (
    archive_official_rule_references,audit_official_rule_references)
from quantlab.data.pit_evidence import archive_pit_evidence
from quantlab.experiments.campaign_state import read_checked


class OfficialRuleReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.session='2025-01-03';self.symbol='sz.000001'
        self.announcement_url='https://disc.static.szse.cn/download/disc/example.PDF'
        announcement=self.root/'announcement.pdf';announcement.write_bytes(b'%PDF official ST announcement')
        statement={'symbol':self.symbol,'effective_at':self.session+'T09:30:00+08:00',
            'available_at':'2025-01-02T18:00:00+08:00','tradable':True,'risk_warning':'ST',
            'source':self.announcement_url}
        archived=archive_pit_evidence(self.root,'security_status',[statement],self.announcement_url,
            '2025-01-02T18:00:00+08:00',announcement,confirm_publication_time=True)
        self.evidence_id=archived['evidence_ids'][0]
        self.formula_url='https://www.szse.cn/lawrules/rule/repeal/rules/rules.pdf'
        formula=self.root/'rules.pdf';formula.write_bytes(b'%PDF official formula fixture')
        notice=self.root/'notice.json';notice.write_text(json.dumps({'data':{'pubTime':1676563200000,
            'content':'<a href="'+self.formula_url.replace('https://','http://')+'">rules</a>'}}))
        self.quote=self.root/'quote.json';self.quote.write_text(json.dumps([{'metadata':{'tabkey':'tab1','cols':{
            'jyrq':'交易日期','zqdm':'证券代码','zqjc':'证券简称','qss':'前收','ks':'开盘',
            'zg':'最高','zd':'最低','ss':'今收'}},'data':[{'jyrq':self.session,'zqdm':'000001',
            'zqjc':'ST测试','qss':'10.00','ks':'9.50','zg':'9.50','zd':'9.50','ss':'9.50','sdf':'-5.00'}],
            'error':None}],ensure_ascii=False))
        self.headers=self.root/'quote.headers';self.headers.write_text(
            'HTTP/1.1 200 OK\nDate: Tue, 15 Sep 2026 15:39:00 GMT\nContent-Type: application/json\n')
        self.plan={'formula':{'title':'深圳证券交易所交易规则（2023年修订）','source_url':self.formula_url,
            'notice_metadata_url':'https://www.szse.cn/lawrules/rule/repeal/rules/notice.json',
            'published_at':'2023-02-17T00:00:00+08:00','document':str(formula),'notice_document':str(notice),
            'clauses':{'price_tick':'3.3.11','formula':'3.3.14','rounding':'3.3.19'}},'cases':[{
            'symbol':self.symbol,'session':self.session,'announcement_evidence_id':self.evidence_id,
            'limit_rate':'0.05','quote_source_url':'https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=1815_stock&TABKEY=tab1&PAGENO=1&txtDMorJC=000001&txtBeginDate=2025-01-03',
            'quote_document':str(self.quote),'quote_headers_document':str(self.headers)}]}

    def archive(self):
        return archive_official_rule_references(self.root,self.plan,confirm_retrospective_only=True,
            now_fn=lambda:datetime(2026,9,15,23,45,tzinfo=ZoneInfo('Asia/Shanghai')))

    def test_archive_is_idempotent_audited_and_never_creates_market_rules(self):
        with self.assertRaisesRegex(ValueError,'retrospective reference only'):
            archive_official_rule_references(self.root,self.plan)
        first=self.archive();second=self.archive()
        self.assertTrue(first['created']);self.assertFalse(second['created'])
        receipt=read_checked(Path(first['path']));row=receipt['records'][0]
        self.assertEqual(row['derived_limit_up'],'10.50');self.assertEqual(row['derived_limit_down'],'9.50')
        self.assertFalse(row['historical_reference_publication_verified_before_open'])
        self.assertFalse(row['market_rules_eligible']);self.assertFalse(receipt['strict_pit_eligible'])
        self.assertFalse(receipt['market_rules_snapshot_appended'])
        self.assertFalse((self.root/'research/official_market_rules').exists())
        audit=audit_official_rule_references(self.root)
        self.assertEqual(audit['verified_receipts'],1);self.assertEqual(audit['invalid_receipts'],0)
        self.assertEqual(audit['reference_records'],1);self.assertEqual(audit['strict_pit_eligible_records'],0)

    def test_changed_quote_or_noncorroborating_low_fails_closed(self):
        result=self.archive();receipt=read_checked(Path(result['path']))
        document=self.root/receipt['records'][0]['historical_quote_document']['path'];original=document.read_bytes()
        document.write_bytes(b'tampered')
        audit=audit_official_rule_references(self.root)
        self.assertEqual(audit['verified_receipts'],0);self.assertEqual(audit['invalid_receipts'],1)
        document.write_bytes(original)
        value=json.loads(self.quote.read_text());value[0]['data'][0]['zd']='9.51'
        self.quote.write_text(json.dumps(value,ensure_ascii=False))
        with self.assertRaisesRegex(ValueError,'does not corroborate'):self.archive()


if __name__=='__main__':unittest.main()
