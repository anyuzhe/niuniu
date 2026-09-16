from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import hashlib,json
import polars as pl

from quantlab.trading.prep_scanner import (
    PrepScanError, build_prep_forward_payload, prep_market_snapshot_content,
    route_market_node, scan_prep_universe,
)
from quantlab.trading.market_snapshot import MarketSnapshotStore
from quantlab.execution.rules import MarketRules
from quantlab.data.daily_market_archive import DailyMarketArchive,EXPECTED_FIELDS
from quantlab.data.pit_evidence import archive_pit_evidence
from quantlab.data.pit_universe import archive_pit_universe
from quantlab.data.security_status import materialize_security_status


class _DailyResponse:
    error_code='0';error_msg='success'
    def __init__(self,rows):self.rows=rows;self.fields=list(EXPECTED_FIELDS);self.index=-1
    def next(self):self.index+=1;return self.index<len(self.rows)
    def get_row_data(self):return [self.rows[self.index][k] for k in self.fields]


class _DailySDK:
    __version__='0.9.3'
    def __init__(self,rows):self.rows=rows
    def login(self):return _DailyResponse([{'ok':'1'}])
    def logout(self):pass
    def query_daily_history_k_AStock(self,date=''):return _DailyResponse(self.rows)


def _daily_row(day,code,close,preclose):
    row={key:'1' for key in EXPECTED_FIELDS}
    row.update(date=day,code=code,open=str(close),high=str(close),low=str(close),close=str(close),
        preclose=str(preclose),volume='1000',amount='10000',adjustflag='3',turn='2',tradestatus='1',
        pctChg=str((close/preclose-1)*100),peTTM='12',pbMRQ='1',psTTM='2',pcfNcfTTM='3',isST='0')
    return row


class PrepScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'data';self.output=self.root/'out'
        self.output.mkdir();(self.data/'lake/bronze/provider=baostock/stock_kline_daily').mkdir(parents=True)
    def tearDown(self):self.tmp.cleanup()

    def write_symbol(self,symbol,closes,volumes=None):
        start=date(2026,9,7);volumes=volumes or [1000]*len(closes)
        rows=[]
        for i,(close,volume) in enumerate(zip(closes,volumes)):
            day=start+timedelta(days=i);rows.append({'date':day,'code':symbol,'open':close,'high':close,
                'low':close,'close':close,'volume':volume,'amount':float(volume)*close,'adjustflag':'3'})
        path=self.data/'lake/bronze/provider=baostock/stock_kline_daily'/(symbol.replace('.','_')+'.parquet')
        pl.DataFrame(rows).write_parquet(path);return path
    def rules_for(self,symbol,closes):
        start=date(2026,9,7);rules=[]
        for i,close in enumerate(closes):
            day=start+timedelta(days=i);previous=closes[i-1] if i else close/1.05
            rules.append({'symbol':symbol,'effective_at':f'{day}T00:00:00+08:00',
                'available_at':f'{day}T00:00:00+08:00','expires_at':f'{day}T23:59:59+08:00',
                'suspended':False,'st':False,'limit_up':round(previous*1.10+1e-9,2),
                'limit_down':round(previous*0.90+1e-9,2),'commission_bps':0.0,'minimum_commission':0.0,
                'sell_tax_bps':0.0,'transfer_bps':0.0,'source':'https://www.sse.com.cn/test'})
        return rules

    def archive_rules(self,rules):
        snapshot=MarketRules(rules).snapshot_id;research=self.data/'research';receipt_dir=research/'official_market_rules'
        receipt_dir.mkdir(parents=True);payload=b'official test evidence';sha=hashlib.sha256(payload).hexdigest()
        document=research/'official_rules'/(sha+'.bin');document.parent.mkdir();document.write_bytes(payload)
        receipt={'format':'official-market-rules-v2','rules_snapshot':snapshot,'rules':rules,'sources':[
            {'url':'https://www.sse.com.cn/test','path':'research/official_rules/'+sha+'.bin',
             'sha256':sha,'fetched_at':'2026-09-09T16:00:00+08:00',
             'published_at':'2026-09-06T16:00:00+08:00','publication_time_confirmed':True}]}
        (receipt_dir/(snapshot+'.json')).write_text(json.dumps(receipt));return snapshot

    def archive_universe(self,symbols,session='2026-09-10'):
        exchanges={'sh':'SSE','sz':'SZSE','bj':'BSE'};hosts={'SSE':'www.sse.com.cn','SZSE':'www.szse.cn','BSE':'www.bse.cn'}
        exchange=exchanges[symbols[0][:2]];self.assertTrue(all(exchanges[s[:2]]==exchange for s in symbols))
        document=self.root/('universe-'+exchange+'.json');document.write_text(json.dumps({'symbols':symbols}))
        source_id=exchange.lower()+'-a-share-list';plan={'format':'niuniu-pit-universe-plan-v1',
            'effective_session':session,'cutoff_at':session+'T09:15:00+08:00',
            'scope':{'market':'CN_A_SHARE','exchanges':[exchange],'instrument_types':['A_SHARE'],'completeness':'FULL_OFFICIAL_LIST'},
            'sources':[{'source_id':source_id,'exchange':exchange,'url':'https://'+hosts[exchange]+'/test/universe',
                'published_at':'2026-09-09T15:00:00+08:00','available_at':'2026-09-09T16:00:00+08:00',
                'document':str(document),'sha256':hashlib.sha256(document.read_bytes()).hexdigest()}],
            'members':[{'symbol':symbol,'source_id':source_id} for symbol in symbols]}
        return archive_pit_universe(self.data,plan,confirm_publication_times=True,
            confirm_semantic_mapping=True,confirm_complete_official_universe=True,
            now_fn=lambda:datetime.fromisoformat('2026-09-09T17:00:00+08:00'))['universe_snapshot']

    def archive_security_status(self,symbol,rows):
        document=self.root/'status-evidence.pdf';document.write_bytes(b'%PDF strict status fixture')
        url='https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-09-06/status.PDF'
        normalized=[{**row,'symbol':symbol,'source':url} for row in rows]
        archive_pit_evidence(self.data,'security_status',normalized,url,'2026-09-06T19:00:00+08:00',document,
            confirm_publication_time=True)
        return materialize_security_status(self.data)

    def test_router_is_conservative_and_can_no_trade(self):
        unknown=route_market_node({'breadth_up':100,'breadth_down':100,'limit_up_count':20,
            'limit_down_count':2,'max_limit_streak':5})
        self.assertEqual(unknown['action'],'UNKNOWN');self.assertIsNone(unknown['target_streak'])
        retreat=route_market_node({'breadth_up':100,'breadth_down':300,'limit_up_count':25,
            'limit_down_count':18,'max_limit_streak':4})
        self.assertEqual(retreat['action'],'SCAN_TARGET_STREAK');self.assertEqual(retreat['target_streak'],2)
        extreme=route_market_node({'breadth_up':50,'breadth_down':450,'limit_up_count':12,
            'limit_down_count':35,'max_limit_streak':3})
        self.assertEqual(extreme['action'],'NO_TRADE');self.assertIsNone(extreme['target_streak'])

    def test_missing_target_session_fails_fast_as_data_not_updated(self):
        self.write_symbol('sh.600001',[10.0,11.0,12.1])
        with self.assertRaises(PrepScanError) as ctx:
            scan_prep_universe(self.data,'2026-09-10',target_streak=2,
                universe_symbols=['sh.600001'],universe_pit_verified=False,lookback_sessions=3)
        self.assertEqual(ctx.exception.code,'DATA_NOT_UPDATED')
        self.assertIn('2026-09-09',str(ctx.exception))

    def test_legacy_mqc_scan_fails_closed_to_partial_retrospective(self):
        self.write_symbol('sh.600001',[10.0,11.0,12.1])
        self.write_symbol('sh.600002',[10.0,10.2,10.3])
        scan=scan_prep_universe(self.data,'2026-09-09',target_streak=2,
            universe_symbols=['sh.600001','sh.600002'],universe_pit_verified=False,lookback_sessions=3)
        self.assertEqual(scan['candidate_count'],1);self.assertEqual(scan['candidates'][0]['symbol'],'sh.600001')
        self.assertEqual(scan['completeness'],'PARTIAL');self.assertEqual(scan['pit_status'],'RETROSPECTIVE_REFERENCE')
        self.assertIn('official_market_rules_missing',scan['blockers'])
        self.assertIn('historical_st_tradestatus_missing',scan['blockers'])
        self.assertIn('pit_universe_not_certified',scan['blockers'])
    def test_explicit_rules_and_verified_universe_can_be_full_strict(self):
        closes1=[10.0,11.0,12.1];closes2=[10.0,10.2,10.3]
        self.write_symbol('sh.600001',closes1);self.write_symbol('sh.600002',closes2)
        rules=self.rules_for('sh.600001',closes1)+self.rules_for('sh.600002',closes2)
        self.archive_rules(rules);universe=self.archive_universe(['sh.600001','sh.600002'])
        scan=scan_prep_universe(self.data,'2026-09-09',target_streak=2,market_rules=rules,
            universe_snapshot=universe,universe_effective_session='2026-09-10',lookback_sessions=3)
        self.assertEqual(scan['completeness'],'FULL');self.assertEqual(scan['pit_status'],'STRICT_PIT')
        self.assertEqual(scan['quality'],'OFFICIAL_RULES');self.assertFalse(scan['blockers'])
        self.assertEqual([x['symbol'] for x in scan['candidates']],['sh.600001'])
        self.assertTrue(scan['rule_snapshot_id']);self.assertEqual(scan['universe_snapshot'],universe)
        self.assertEqual(scan['universe_mode'],'PIT_UNIVERSE_RECEIPT')
        self.assertIn('pit_universe:'+universe,scan['candidates'][0]['evidence_ids'])

    def test_pit_universe_session_and_full_membership_are_exact(self):
        self.write_symbol('sh.600001',[10.0,11.0,12.1]);self.write_symbol('sh.600002',[10.0,10.2,10.3])
        snapshot=self.archive_universe(['sh.600001','sh.600002'])
        with self.assertRaises(PrepScanError) as session:
            scan_prep_universe(self.data,'2026-09-09',target_streak=2,
                universe_snapshot=snapshot,universe_effective_session='2026-09-11',lookback_sessions=3)
        self.assertEqual(session.exception.code,'PIT_UNIVERSE_SESSION_MISMATCH')
        with self.assertRaises(PrepScanError) as subset:
            scan_prep_universe(self.data,'2026-09-09',target_streak=2,universe_symbols=['sh.600001'],
                universe_snapshot=snapshot,universe_effective_session='2026-09-10',lookback_sessions=3)
        self.assertEqual(subset.exception.code,'PIT_UNIVERSE_MEMBERSHIP_MISMATCH')

    def test_complete_rule_json_without_archived_official_receipt_is_not_strict(self):
        closes=[10.0,11.0,12.1];self.write_symbol('sh.600001',closes)
        rules=self.rules_for('sh.600001',closes)
        scan=scan_prep_universe(self.data,'2026-09-09',target_streak=2,market_rules=rules,
            universe_symbols=['sh.600001'],universe_pit_verified=True,lookback_sessions=3)
        self.assertEqual(scan['completeness'],'PARTIAL');self.assertEqual(scan['pit_status'],'RETROSPECTIVE_REFERENCE')
        self.assertEqual(scan['quality'],'EXPLICIT_RULES_UNVERIFIED')
        self.assertIn('official_rule_receipt_missing',scan['blockers'])
        self.assertIn('pit_universe_not_certified',scan['blockers'])
        self.assertTrue(scan['legacy_universe_pit_assertion_ignored'])
        self.assertFalse(scan['official_rules_verified'])

    def test_missing_rule_session_never_silently_infers_strict_limit(self):
        closes=[10.0,11.0,12.1];self.write_symbol('sh.600001',closes)
        rules=self.rules_for('sh.600001',closes)[:-1]
        scan=scan_prep_universe(self.data,'2026-09-09',target_streak=2,market_rules=rules,
            universe_symbols=['sh.600001'],universe_pit_verified=True,lookback_sessions=3)
        self.assertEqual(scan['completeness'],'PARTIAL');self.assertEqual(scan['pit_status'],'RETROSPECTIVE_REFERENCE')
        self.assertIn('official_market_rule_sessions_incomplete',scan['blockers'])
        self.assertEqual(scan['candidate_count'],0)

    def test_verified_security_status_fills_status_gap_without_certifying_inferred_limits(self):
        symbol='sz.000001';self.write_symbol(symbol,[10.0,11.0,11.55])
        self.archive_security_status(symbol,[
            {'effective_at':'2026-09-07T09:30:00+08:00','available_at':'2026-09-06T20:00:00+08:00',
             'tradable':True,'risk_warning':'NONE'},
            {'effective_at':'2026-09-08T09:30:00+08:00','available_at':'2026-09-06T20:00:00+08:00',
             'tradable':True,'risk_warning':'NONE'},
            {'effective_at':'2026-09-09T09:30:00+08:00','available_at':'2026-09-08T20:00:00+08:00',
             'tradable':True,'risk_warning':'ST'}])
        scan=scan_prep_universe(self.data,'2026-09-09',target_streak=2,
            universe_symbols=[symbol],universe_pit_verified=True,lookback_sessions=3)
        self.assertEqual(scan['candidate_count'],1);self.assertEqual(scan['candidates'][0]['symbol'],symbol)
        self.assertNotIn('historical_st_tradestatus_missing',scan['blockers'])
        self.assertIn('official_market_rules_missing',scan['blockers'])
        self.assertEqual(scan['quality'],'PIT_STATUS_WITH_INFERRED_LIMITS')
        self.assertEqual(scan['pit_status'],'RETROSPECTIVE_REFERENCE')
        self.assertEqual(scan['strict_security_status_rows'],1);self.assertEqual(scan['strict_security_status_observations'],3);self.assertTrue(scan['security_status_materialized'])
        feature=scan['candidates'][0]['features'];self.assertEqual(feature['risk_warning'],'ST')
        self.assertEqual(feature['status_quality'],'STRICT_PIT_EVIDENCE');self.assertTrue(feature['security_status_evidence_id'])
        self.assertIn(feature['security_status_evidence_id'],scan['candidates'][0]['evidence_ids'])

    def test_tampered_security_status_materialization_blocks_prep_before_fallback(self):
        symbol='sz.000001';self.write_symbol(symbol,[10.0,11.0,11.55])
        self.archive_security_status(symbol,[
            {'effective_at':'2026-09-07T09:30:00+08:00','available_at':'2026-09-06T20:00:00+08:00',
             'tradable':True,'risk_warning':'NONE'}])
        (self.data/'lake/silver/security_status/security_status.parquet').write_bytes(b'tampered')
        with self.assertRaises(PrepScanError) as ctx:
            scan_prep_universe(self.data,'2026-09-09',target_streak=2,universe_symbols=[symbol],
                universe_pit_verified=True,lookback_sessions=3)
        self.assertEqual(ctx.exception.code,'SECURITY_STATUS_INVALID')

    def test_prep_snapshot_and_forward_payload_preserve_quality_and_no_stock_pick(self):
        self.write_symbol('sh.600001',[10.0,11.0,12.1])
        scan=scan_prep_universe(self.data,'2026-09-09',target_streak=2,
            universe_symbols=['sh.600001'],universe_pit_verified=False,lookback_sessions=3)
        content=prep_market_snapshot_content(scan,'2026-09-10','2026-09-09T16:00:00+08:00',self.data)
        self.assertEqual(content['frame'],'PREP');self.assertEqual(content['completeness'],'PARTIAL')
        snapshot={**content,'snapshot_id':'00000000-0000-0000-0000-000000000001','strict_pit_eligible':False}
        definition={'definition_id':'00000000-0000-0000-0000-000000000002',
            'source_ids':['00000000-0000-0000-0000-000000000003']}
        payload=build_prep_forward_payload(scan,snapshot,definition)
        self.assertEqual(payload['prediction']['selected_symbols'],[])
        self.assertEqual(payload['candidate_set']['pit_status'],'RETROSPECTIVE_REFERENCE')
        self.assertEqual(payload['candidate_set']['completeness'],'PARTIAL')
        self.assertEqual(payload['market_snapshot_ids'],[snapshot['snapshot_id']])

    def test_unknown_router_without_host_override_blocks_candidate_freeze(self):
        self.write_symbol('sh.600001',[10.0,10.1,10.2])
        scan=scan_prep_universe(self.data,'2026-09-09',universe_symbols=['sh.600001'],
            universe_pit_verified=False,lookback_sessions=3)
        self.assertEqual(scan['route']['action'],'UNKNOWN');self.assertIsNone(scan['target_streak'])
        fake={**prep_market_snapshot_content(scan,'2026-09-10','2026-09-09T16:00:00+08:00',self.data),
            'snapshot_id':'00000000-0000-0000-0000-000000000001','strict_pit_eligible':False}
        definition={'definition_id':'00000000-0000-0000-0000-000000000002',
            'source_ids':['00000000-0000-0000-0000-000000000003']}
        with self.assertRaises(PrepScanError) as ctx:build_prep_forward_payload(scan,fake,definition)
        self.assertEqual(ctx.exception.code,'ROUTE_UNKNOWN')


    def test_daily_market_overlay_advances_stale_base_without_rewriting_lake(self):
        self.write_symbol('sh.600001',[10.0,10.0,10.0])
        self.write_symbol('sh.600002',[10.0,10.1,10.2])
        clock=lambda:datetime(2026,9,11,10,tzinfo=timezone.utc)
        archive=DailyMarketArchive(self.output,now_fn=clock)
        archive.capture('2026-09-10',sdk=_DailySDK([
            _daily_row('2026-09-10','sh.600001',11.0,10.0),_daily_row('2026-09-10','sh.600002',10.3,10.2)]))
        archive.capture('2026-09-11',sdk=_DailySDK([
            _daily_row('2026-09-11','sh.600001',12.1,11.0),_daily_row('2026-09-11','sh.600002',10.4,10.3)]))
        scan=scan_prep_universe(self.data,'2026-09-11',target_streak=2,
            universe_symbols=['sh.600001','sh.600002'],universe_pit_verified=False,
            lookback_sessions=5,daily_market_output=self.output)
        self.assertEqual(scan['latest_available_session'],'2026-09-11')
        self.assertEqual(scan['daily_market_days'],['2026-09-10','2026-09-11'])
        self.assertEqual([row['symbol'] for row in scan['candidates']],['sh.600001'])
        self.assertEqual(scan['pit_status'],'RETROSPECTIVE_REFERENCE')
        self.assertIn('official_market_rules_missing',scan['blockers'])

    def test_daily_market_overlap_revision_conflict_fails_closed(self):
        self.write_symbol('sh.600001',[10.0,10.0,10.0])
        archive=DailyMarketArchive(self.output,now_fn=lambda:datetime(2026,9,9,10,tzinfo=timezone.utc))
        archive.capture('2026-09-09',sdk=_DailySDK([_daily_row('2026-09-09','sh.600001',10.5,10.0)]))
        with self.assertRaises(PrepScanError) as ctx:
            scan_prep_universe(self.data,'2026-09-09',target_streak=1,
                universe_symbols=['sh.600001'],universe_pit_verified=False,
                lookback_sessions=3,daily_market_output=self.output)
        self.assertEqual(ctx.exception.code,'DATA_REVISION_CONFLICT')


if __name__=='__main__':unittest.main()
