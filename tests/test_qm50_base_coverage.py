"""QM50 base layer: existing verifier reuse, exact sessions, missing facts and no upgrades."""
import copy,hashlib,io,json,tempfile,unittest
from datetime import date,datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import polars as pl
from quantlab.agent.qm50_base_coverage import inspect_base_coverage,_exact_rule
from quantlab.trading.qm50_base_contract import run_base_guards,previous_height,fixture,classify_day
from quantlab.data.pit_universe import archive_pit_universe
from quantlab.data.security_status_coverage import archive_security_status_coverage
from quantlab.data.pit_evidence import archive_pit_evidence
from quantlab.data.official_rule_archive import archive_official_rules
from quantlab.execution.rules import MarketRules
from quantlab.agent.research_specs import ResearchSpecStore
from quantlab.agent.research_spec_tools import ResearchSpecAPI
from quantlab.agent.spec_test_service import SpecTestService
from test_research_spec_fidelity import synthetic_pair

DAY='2026-09-10'
SYMBOL='sh.600001'

class QM50BaseCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);base=self.root/'lake/bronze/provider=baostock'
        (base/'trade_calendar').mkdir(parents=True);(base/'stock_kline_daily').mkdir()
        days=[date(2026,8,1)+timedelta(days=i) for i in range(60)]
        self.calendar=base/'trade_calendar/calendar.parquet'
        pl.DataFrame({'calendar_date':[str(d) for d in days],'is_trading_day':['1']*len(days)}).write_parquet(self.calendar)
        self.raw=base/'stock_kline_daily/sh_600001.parquet'
        pl.DataFrame({'date':days,'code':[SYMBOL]*len(days),'open':[10.]*len(days),'high':[11.]*len(days),'low':[9.]*len(days),
            'close':[11.]*len(days),'volume':[100.]*len(days),'amount':[1000.]*len(days),'adjustflag':['3']*len(days),
            'fetch_ts':['2026-09-30T20:00:00']*len(days)}).write_parquet(self.raw)
        self.doc=self.root/'source.bin';self.doc.write_bytes(b'EXPLICIT SYNTHETIC EXCHANGE FIXTURE; not real data')
    def inspect(self,symbols=SYMBOL,day=DAY):return inspect_base_coverage(self.root,symbols,day,day)
    def state(self):return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
    def universe(self,day=DAY):
        source={'source_id':'sse','exchange':'SSE','url':'https://www.sse.com.cn/fixture','published_at':day+'T07:00:00+08:00',
            'available_at':day+'T07:01:00+08:00','document':str(self.doc),'sha256':hashlib.sha256(self.doc.read_bytes()).hexdigest()}
        plan={'format':'niuniu-pit-universe-plan-v1','effective_session':day,'cutoff_at':day+'T09:15:00+08:00',
            'scope':{'market':'CN_A_SHARE','exchanges':['SSE'],'instrument_types':['A_SHARE'],'completeness':'FULL_OFFICIAL_LIST'},
            'sources':[source],'members':[{'symbol':SYMBOL,'source_id':'sse'}]}
        return archive_pit_universe(self.root,plan,confirm_publication_times=True,confirm_semantic_mapping=True,
            confirm_complete_official_universe=True,now_fn=lambda:datetime.fromisoformat(day+'T08:00:00+08:00'))
    def status(self,uid,warning='NONE'):
        day=DAY;source={'source_id':'status','exchange':'SSE','coverage':['TRADABILITY','RISK_WARNING'],
            'url':'https://www.sse.com.cn/fixture','published_at':day+'T07:00:00+08:00','available_at':day+'T07:01:00+08:00',
            'document':str(self.doc),'sha256':hashlib.sha256(self.doc.read_bytes()).hexdigest()}
        plan={'format':'niuniu-security-status-coverage-plan-v2','effective_session':day,'cutoff_at':day+'T09:15:00+08:00',
            'universe_snapshot':uid,'previous_status_snapshot':None,'sources':[source],
            'records':[{'symbol':SYMBOL,'tradable':True,'risk_warning':warning,'source_ids':['status']}]}
        return archive_security_status_coverage(self.root,plan,confirm_publication_times=True,confirm_semantic_mapping=True,
            confirm_complete_daily_status=True,now_fn=lambda:datetime.fromisoformat(day+'T08:10:00+08:00'))
    def rule(self,day=DAY,**changes):
        return {'symbol':SYMBOL,'effective_at':day+'T09:30:00+08:00','available_at':day+'T08:00:00+08:00',
            'expires_at':day+'T15:30:00+08:00','suspended':False,'st':False,'limit_up':11.,'limit_down':9.,
            'commission_bps':2.,'minimum_commission':5.,'sell_tax_bps':5.,'transfer_bps':.1,'source':'https://www.sse.com.cn/fixture',**changes}
    def archive_rule(self,record):
        payload=self.doc.read_bytes();url=record['source']
        return archive_official_rules(self.root,[record],[url],{url:'2026-08-01T07:00:00+08:00'},confirm_publication_time=True,
            opener=lambda *a,**kw:SimpleNamespace(geturl=lambda:url,read=lambda n:payload),
            now_fn=lambda:datetime.fromisoformat('2026-09-30T20:00:00+08:00'))
    def test_empty_formal_archive_not_normal_state_and_no_writes(self):
        before=self.state();rows,summary=self.inspect()
        self.assertEqual(summary['requested_status'],'BLOCKED');self.assertEqual(summary['global_archives']['pit_universe']['verified_receipts'],0)
        self.assertIsNone(rows[0]['candidate_for_D']);self.assertIsNone(rows[0]['prev_limitup_height'])
        self.assertIn('D:UNIVERSE_MISSING',rows[0]['reason_codes']);self.assertEqual(before,self.state())
    def test_valid_global_receipt_for_wrong_session_does_not_cover_request(self):
        self.universe('2026-09-01');rows,summary=self.inspect()
        self.assertEqual(summary['global_archives']['pit_universe']['verified_receipts'],1)
        self.assertEqual(rows[0]['session_checks'][0]['universe'],'MISSING')
    def test_exact_universe_and_status_still_need_rules_bar_vintage_and_fields(self):
        u=self.universe();self.status(u['universe_snapshot']);self.archive_rule(self.rule())
        rows,s=self.inspect();now=rows[0]['session_checks'][0]
        self.assertEqual(now['universe'],'VERIFIED_EXACT_SESSION');self.assertEqual(now['status_coverage'],'VERIFIED_EXACT_SESSION')
        self.assertEqual(now['limit_up'],11.);self.assertIsNone(rows[0]['candidate_for_D'])
        self.assertIn('reference_price',s['missing_source_contract_fields']);self.assertIn('tick_size',s['missing_source_contract_fields'])
        self.assertIn('BAR_AVAILABLE_AT_UNVERIFIED',rows[0]['reason_codes'])
    def test_exchange_scope_and_member_not_assumed(self):
        self.universe();rows,_=self.inspect('sh.600002 sz.000001')
        self.assertFalse(rows[0]['session_checks'][0]['member']);self.assertEqual(rows[1]['session_checks'][0]['universe'],'MISSING')
    def test_sparse_statement_not_full_status_nor_cross_day_carried(self):
        url='https://www.sse.com.cn/fixture'
        archive_pit_evidence(self.root,'security_status',[{'symbol':SYMBOL,'effective_at':'2026-09-09T09:30:00+08:00',
            'available_at':'2026-09-08T20:00:00+08:00','tradable':True,'risk_warning':'ST','source':url}],
            url,'2026-09-08T19:00:00+08:00',self.doc,confirm_publication_time=True)
        rows,s=self.inspect();details=rows[0]['session_checks']
        self.assertEqual(s['global_archives']['pit_statements']['verified_records'],1)
        self.assertEqual(details[0]['sparse_status_statements_exact_session'],0)
        self.assertEqual(details[1]['sparse_status_statements_exact_session'],1)
        self.assertEqual(details[1]['status_coverage'],'MISSING_UNIVERSE_BINDING')
    def test_unknown_daily_status_is_not_verified_normal(self):
        u=self.universe();self.status(u['universe_snapshot'],'UNKNOWN')
        rows,s=self.inspect();self.assertEqual(rows[0]['session_checks'][0]['status_coverage'],'UNKNOWN_STATUS_IN_UNIVERSE')
        self.assertEqual(s['global_archives']['daily_security_status']['strict_pit_eligible_receipts'],0)
    def test_corrupt_receipt_or_document_stays_visible_invalid(self):
        u=self.universe();document=next((self.root/'research/pit_universe/documents').glob('*.bin'));document.write_bytes(b'tampered')
        rows,s=self.inspect();self.assertEqual(s['global_archives']['pit_universe']['invalid_receipts'],1)
        self.assertEqual(s['global_archives']['pit_universe']['verified_receipts'],0);self.assertIsNone(rows[0]['candidate_for_D'])
    def test_suspended_rule_without_bounds_not_infinite_tradability(self):
        self.archive_rule(self.rule(suspended=True,limit_up=None,limit_down=None))
        rows,s=self.inspect();self.assertIn('D:SUSPENDED_RULE_NO_PRICE_BOUNDS_REQUIRED',rows[0]['reason_codes'])
        self.assertEqual(s['global_archives']['official_rules']['rule_records'],1)
    def test_conflicting_rule_and_expired_replacement_do_not_fallback(self):
        a=MarketRules([self.rule()]).records[0];b=MarketRules([self.rule(limit_up=12.)]).records[0]
        rows=[{'record':r,'snapshot':str(i)} for i,r in enumerate((a,b))]
        self.assertEqual(_exact_rule(rows,SYMBOL,DAY)[1],'AMBIGUOUS')
        b={**a,'available_at':datetime.fromisoformat(DAY+'T09:00:00+08:00'),'expires_at':datetime.fromisoformat(DAY+'T09:30:00+08:00')}
        self.assertEqual(_exact_rule([{'record':a,'snapshot':'a'},{'record':b,'snapshot':'b'}],SYMBOL,DAY)[1],'EXPIRED_NO_OLDER_FALLBACK')
    def test_calendar_missing_day_fails_no_implied_holiday(self):
        cal=pl.read_parquet(self.calendar);cal.filter(pl.col('calendar_date')!='2026-09-06').write_parquet(self.calendar)
        with self.assertRaisesRegex(ValueError,'日历缺日'):self.inspect()
    def test_calendar_predecessors_are_trading_days_not_calendar_days(self):
        cal=pl.read_parquet(self.calendar).with_columns(pl.when(pl.col('calendar_date').is_in(['2026-09-08','2026-09-09'])).then(pl.lit('0')).otherwise(pl.col('is_trading_day')).alias('is_trading_day'))
        cal.write_parquet(self.calendar);rows,_=self.inspect();self.assertEqual(rows[0]['previous_session'],'2026-09-07')
    def test_symlink_archive_and_invalid_request_fail_before_audit(self):
        (self.root/'research').symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):self.inspect()
        with self.assertRaises(ValueError):inspect_base_coverage(self.root,'../secret',DAY,DAY)
        with self.assertRaises(ValueError):inspect_base_coverage(self.root,SYMBOL,'2026-01-01',DAY)
    def test_25_p01_and_asof_components(self):
        result=run_base_guards();self.assertEqual(result['passed'],25);self.assertEqual(result['failed'],0,result)
        self.assertFalse(result['real_market_backtest'])
    def test_exact_explicit_limits_no_rounding_to_ten_percent(self):
        row=fixture(reference_price='9.10',upper_limit_price='10.01',lower_limit_price='8.19',open='9.10',low='9.10',high='10.01',close='10.01')
        self.assertTrue(classify_day(row,'2024-01-03T09:15:00+08:00')['close_is_upper_limit'])
        with self.assertRaises(ValueError):previous_height([row,row],['2024-01-02'],'2024-01-03T09:15:00+08:00')
    def test_bound_native_api_exposes_only_safe_existing_coverage_and_new_probe(self):
        out=self.root/'workspace';out.mkdir();md,js=synthetic_pair(self.root);store=ResearchSpecStore(out)
        m=store.import_pair(md,js,confirmed=True);sid=m['spec_id']
        inner=SimpleNamespace(schemas=lambda:[{'name':'get_strict_pit_coverage'},{'name':'qualify_research_data'},{'name':'submit_granted_experiment'}])
        api=ResearchSpecAPI(inner,out,self.root,active_spec=sid,allow_tests=True);names={t['name'] for t in api.schemas()}
        self.assertIn('get_strict_pit_coverage',names);self.assertIn('qualify_research_data',names)
        self.assertIn('inspect_qm50_base_rules_coverage',names);self.assertNotIn('submit_granted_experiment',names)
        self.assertEqual(api.call('archive_pit_universe',{})['error']['code'],'SPEC_SUBSTITUTION_REJECTED')
        with patch('quantlab.agent.spec_test_service.SUPPORTED_HASHES',m['files']):
            args={'spec_id':sid,'kind':'BASE_RULES_COVERAGE','symbols':SYMBOL,'start':DAY,'end':DAY}
            result=api.call('run_research_spec_test',args)
            self.assertTrue(result['ok'],result);record=result['data'];self.assertEqual(record['status'],'AUDIT_COMPLETED_INPUTS_BLOCKED')
            restored=SpecTestService(out,self.root).get(sid,record['test_id']);self.assertEqual(restored['coverage_sha256'],record['coverage_sha256'])
            (out/'_research_spec_tests'/record['test_id']/'coverage.parquet').write_bytes(b'corruption')
            with self.assertRaises(ValueError):SpecTestService(out,self.root).get(sid,record['test_id'])

    def test_actual_runtime_not_mock_inner_has_pit_coverage_tool(self):
        from quantlab.agent.chat_cli import headless_chat_runtime
        out=self.root/'native';out.mkdir();md,js=synthetic_pair(self.root)
        m=ResearchSpecStore(out).import_pair(md,js,confirmed=True)
        with headless_chat_runtime(out,self.root,research_spec=m['spec_id'],local_data_only=True) as runtime:
            names=[s['name'] for s in runtime.api.schemas()]
            self.assertEqual(names.count('get_strict_pit_coverage'),1)
            self.assertNotIn('submit_granted_experiment',names)
            before=self.state()
            result=runtime.api.call('get_strict_pit_coverage',{'symbols':SYMBOL,'start':DAY,'end':DAY,'detail_limit':10})
            self.assertTrue(result['ok'],result)
            self.assertFalse(result['data']['dataset_strict_pit_certified'])
            self.assertEqual(result['data']['global_official_rules']['verified_receipts'],0)
            self.assertEqual(before,self.state())
    def test_regime_and_instrument_must_be_explicit_not_inferred(self):
        from quantlab.trading.qm50_base_contract import candidate_for_day
        row=fixture('2024-01-03');decision='2024-01-03T09:15:00+08:00'
        for key in ('instrument_type','normal_price_limit_regime','new_listing_no_limit_flag'):
            bad={k:v for k,v in row.items() if k!=key}
            self.assertIsNone(candidate_for_day(1,bad,complete_universe=True,decision_time=decision)['candidate'])
