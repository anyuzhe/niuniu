from datetime import datetime,date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import hashlib,json,tempfile,unittest
import polars as pl
import test_baostock_data as fixture
from quantlab.data.base import DataBatch,DataSnapshot
from quantlab.data.qualification import qualify_research,qualify_spec
from quantlab.execution.rules import MarketRules
from quantlab.agent.proposals import ProposalService
from quantlab.agent.planning import ProposalError
from quantlab.data.pit_evidence import archive_pit_evidence
from quantlab.workbench.jobs import JobQueue


class DataQualificationTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.BaostockDataTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.fx.imported();self.data=self.fx.directory/'dataset';self.output=self.fx.root
        self.base={'question':'qualification fixture','symbols':fixture.plan()['symbols'],
            'start':'2025-01-01','end':'2025-01-10','factor':'BASE.MOMENTUM',
            'parameters':{'lookback':2},'horizons':[1],'quantiles':3,'replay':True}

    def test_retrospective_reference_qualifies_but_reports_strict_blockers(self):
        spec={**self.base,'qualification':'retrospective_reference'}
        result=qualify_research(self.data,spec)
        self.assertTrue(result['qualified']);self.assertEqual(result['status'],'qualified_retrospective_reference')
        self.assertIn('historical_bar_vintage_not_certified',result['strict_pit_blockers'])
        self.assertIn('adjusted_price_historical_availability_unverified',result['strict_pit_blockers'])

    def test_baostock_ratio_never_silently_becomes_strict_pit(self):
        spec={**self.base,'factor':'BAO.PE_TTM','parameters':{'lag_bars':1},
            'qualification':'strict_pit'}
        result=qualify_research(self.data,spec)
        self.assertFalse(result['qualified'])
        self.assertIn('factor_first_publication_or_revision_history_unverified',result['blockers'])
        self.assertIn('historical_bar_vintage_not_certified',result['blockers'])
        with self.assertRaisesRegex(ProposalError,'资格级别未满足'):
            ProposalService(self.output,self.data).preview(spec)

    def test_strict_requirement_is_enforced_again_by_job_queue(self):
        spec={**self.base,'qualification':'strict_pit'}
        queue=JobQueue(self.output,self.data)
        try:
            with self.assertRaisesRegex(ValueError,'DATA_QUALIFICATION_BLOCKED'):
                queue.submit(str(uuid4()),spec)
            self.assertEqual(queue.list(),[])
        finally:queue.close()

    def trusted_batch(self,root):
        zone='Asia/Shanghai';stamp=lambda y,m,d:datetime(y,m,d,15,tzinfo=__import__('zoneinfo').ZoneInfo(zone))
        bars=pl.DataFrame({'symbol':['sh.600000','sh.600000'],'datetime':[stamp(2025,1,2),stamp(2025,1,3)],
            'available_at':[stamp(2025,1,2),stamp(2025,1,3)],'timeframe':['1d','1d'],
            'open':[10.,10.2],'high':[10.5,10.7],'low':[9.8,10.0],'close':[10.2,10.4],
            'volume':[1000.,1200.],'turnover':[10000.,13000.],'adj_factor':[1.,1.]})
        source=root/'trusted-bars.parquet';bars.write_parquet(source);payload=source.read_bytes()
        snap=DataSnapshot('trusted-snapshot','pit_test_provider','raw',({'path':str(source),
            'sha256':hashlib.sha256(payload).hexdigest(),'historical_available_at_verified':True},))
        return DataBatch(bars,snap)

    def test_synthetic_verified_vintage_can_pass_strict_pit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);batch=self.trusted_batch(root)
            spec={'question':'trusted raw fixture','symbols':['sh.600000'],'start':'2025-01-02','end':'2025-01-03',
                'adjustment':'raw','factor':'BASE.MOMENTUM','parameters':{'lookback':1},
                'horizons':[1],'quantiles':2,'replay':True,'qualification':'strict_pit'}
            with patch('quantlab.data.provider.local_data_provider',return_value=type('P',(),{'load':lambda _s,_r:batch})()):
                result=qualify_research(root,spec)
            self.assertTrue(result['qualified'],result);self.assertEqual(result['status'],'qualified_strict_pit')
            self.assertEqual(result['components']['bars']['status'],'strict_pit')

    def test_official_rule_covered_requires_hashed_official_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);batch=self.trusted_batch(root);(root/'research/rules').mkdir(parents=True)
            url='https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml'
            rules=[{'symbol':'sh.600000','effective_at':'2025-01-01T00:00:00+08:00','available_at':'2025-01-01T00:00:00+08:00',
                'expires_at':'2025-01-04T23:00:00+08:00','suspended':False,'st':False,'limit_up':11.0,'limit_down':9.0,
                'commission_bps':3,'minimum_commission':5,'sell_tax_bps':0,'transfer_bps':0,'source':url}]
            spec={'question':'official rule fixture','symbols':['sh.600000'],'start':'2025-01-02','end':'2025-01-03',
                'adjustment':'raw','factor':'BASE.MOMENTUM','parameters':{'lookback':1},'horizons':[1],'quantiles':2,
                'replay':True,'mode':'execution','execution':{'top_n':1,'price_mode':'account'},
                'market_rules':rules,'qualification':'official_rule_covered'}
            provider=type('P',(),{'load':lambda _s,_r:batch})()
            with patch('quantlab.data.provider.local_data_provider',return_value=provider):first=qualify_research(root,spec)
            self.assertFalse(first['qualified']);self.assertIn('official_rule_receipt_missing',first['blockers'])
            document=root/'research/rules/sse-rule.html';document.write_text('official fixture bytes')
            receipt={'format':'official-market-rules-v1','rules_snapshot':MarketRules(rules).snapshot_id,'sources':[{
                'url':url,'path':'research/rules/sse-rule.html','sha256':hashlib.sha256(document.read_bytes()).hexdigest(),
                'fetched_at':'2026-09-12T10:00:00+00:00'}]}
            (root/'research/official_market_rules.json').write_text(json.dumps(receipt))
            with patch('quantlab.data.provider.local_data_provider',return_value=provider):second=qualify_research(root,spec)
            self.assertTrue(second['qualified'],second);self.assertEqual(second['components']['official_rules']['status'],'official_rule_covered')

    def test_official_rule_archive_downloads_only_exchange_urls_and_is_idempotent(self):
        from quantlab.data.official_rule_archive import archive_official_rules
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);url='https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml'
            rules=[{'symbol':'sh.600000','effective_at':'2025-01-01T00:00:00+08:00','available_at':'2025-01-01T00:00:00+08:00',
                'expires_at':'2025-01-04T23:00:00+08:00','suspended':False,'st':False,'limit_up':11.0,'limit_down':9.0,
                'commission_bps':3,'minimum_commission':5,'sell_tax_bps':0,'transfer_bps':0,'source':url}]
            class Response:
                def geturl(self):return url
                def read(self,_n):return b'official exchange document fixture'
            opener=lambda *_a,**_k:Response()
            first=archive_official_rules(root,rules,[url],opener=opener)
            second=archive_official_rules(root,rules,[url],opener=opener)
            self.assertTrue(first['created']);self.assertFalse(second['created'])
            self.assertTrue((root/'research/official_market_rules.json').is_file())
            bad=[{**rules[0],'source':'https://example.com/rule'}]
            with self.assertRaisesRegex(ValueError,'上交所'):
                archive_official_rules(root,bad,['https://example.com/rule'],opener=opener)


    def test_pit_universe_requires_archived_authoritative_publication_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);batch=self.trusted_batch(root);provider=type('P',(),{'load':lambda _s,_r:batch})()
            research=root/'research';research.mkdir();stamp=datetime(2025,1,1,15,tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Shanghai'))
            event={'symbol':'sh.600000','effective_at':stamp,'available_at':stamp,'eligible':True}
            pl.DataFrame([event]).write_parquet(research/'universe_events.parquet')
            spec={'question':'PIT universe receipt fixture','symbols':['sh.600000'],'start':'2025-01-02','end':'2025-01-03',
                'adjustment':'raw','factor':'BASE.MOMENTUM','parameters':{'lookback':1},'horizons':[1],'quantiles':2,
                'replay':True,'qualification':'strict_pit','universe':{'mode':'pit'}}
            with patch('quantlab.data.provider.local_data_provider',return_value=provider):missing=qualify_research(root,spec)
            self.assertIn('pit_universe_timing_present_but_provenance_not_certified',missing['blockers'])
            source='https://www.sse.com.cn/assortment/stock/list/share/'
            document=root/'sse-universe.html';document.write_text('official eligibility publication fixture')
            archive_pit_evidence(root,'universe_eligibility',[event],source,'2025-01-01T14:00:00+08:00',document,confirm_publication_time=True)
            with patch('quantlab.data.provider.local_data_provider',return_value=provider):good=qualify_research(root,spec)
            self.assertTrue(good['qualified'],good);self.assertTrue(good['components']['universe']['evidence'][0]['historical_publication_verified'])

    def test_legacy_research_only_job_can_migrate_on_explicit_resume(self):
        from quantlab.storage.codec import encode
        spec={**self.base,'qualification':'research_only'};job_id=str(uuid4())
        queue=JobQueue(self.output,self.data)
        try:queue.submit(job_id,spec)
        finally:queue.close()
        path=self.output/'_jobs'/(job_id+'.json');record=json.loads(path.read_text())
        record.pop('qualification',None);record['resolved'].pop('qualification',None)
        record.update(status='interrupted',error='legacy fixture',finished_at='2025-01-01T00:00:00+00:00')
        path.write_text(encode(record))
        reopened=JobQueue(self.output,self.data)
        try:
            resumed=reopened.resume(job_id);self.assertEqual(resumed['attempt'],2)
            self.assertEqual(resumed['qualification']['required_level'],'research_only')
            self.assertEqual(resumed['resolved']['qualification'],'research_only')
        finally:reopened.close()

    def test_neutralization_requires_authoritative_complete_pit_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);batch=self.trusted_batch(root);provider=type('P',(),{'load':lambda _s,_r:batch})()
            base={'question':'neutralization PIT fixture','symbols':['sh.600000'],'start':'2025-01-02','end':'2025-01-03',
                'adjustment':'raw','factor':'BASE.MOMENTUM','parameters':{'lookback':1},'horizons':[1],'quantiles':2,
                'replay':True,'qualification':'strict_pit'}
            event={'symbol':'sh.600000','market_cap':1e9,'effective_at':'2025-01-01T15:00:00+08:00',
                'available_at':'2025-01-01T15:00:00+08:00','expires_at':'2025-01-04T16:00:00+08:00','source':'https://example.com/cap'}
            spec={**base,'processor':{'steps':[{'method':'size_neutralization'}],'size_events':[event]}}
            with patch('quantlab.data.provider.local_data_provider',return_value=provider):bad=qualify_research(root,spec)
            self.assertIn('market_cap_source_not_authoritative',bad['blockers'])
            event['source']='https://www.cninfo.com.cn/new/disclosure/stock?stockCode=600000'
            spec={**base,'processor':{'steps':[{'method':'size_neutralization'}],'size_events':[event]}}
            with patch('quantlab.data.provider.local_data_provider',return_value=provider):unarchived=qualify_research(root,spec)
            self.assertIn('market_cap_publication_evidence_unverified',unarchived['blockers'])
            document=root/'cninfo-cap.html';document.write_text('official market-cap publication fixture')
            archive_pit_evidence(root,'daily_market_cap',[event],event['source'],'2025-01-01T14:00:00+08:00',document,confirm_publication_time=True)
            with patch('quantlab.data.provider.local_data_provider',return_value=provider):good=qualify_research(root,spec)
            self.assertTrue(good['qualified'],good);self.assertEqual(good['components']['daily_market_cap']['status'],'strict_pit')
