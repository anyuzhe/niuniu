"""Regression for the native archived-input bridge; no network or real model."""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import contextlib,io,json
import polars as pl
from test_retro_daily import FakeSDK,bar
from test_research_spec_fidelity import synthetic_pair
from quantlab.data.retro_daily import RetroDailyStore
from quantlab.agent.qm50_archived_inputs import ArchivedDailyBridge,materialize,replay,VERSION
from quantlab.agent.research_specs import ResearchSpecStore,sha
from quantlab.agent.spec_test_service import SpecTestService
from quantlab.agent.research_spec_tools import ResearchSpecAPI

class ArchivedQM50Tests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.source.mkdir();self.output=self.root/'output';self.output.mkdir()
        self.days=[date(2026,7,1)+timedelta(days=i) for i in range(60)]
        calendar=[(d.isoformat(),'1' if d.weekday()<5 else '0') for d in self.days]
        self.sessions=[d for d in self.days if d.weekday()<5]
        basic=[('sh.600000','name','2000-01-01','','1','1'),('sz.000001','name','2000-01-01','','1','1')]
        bars={s:[bar(d.isoformat(),s,10.+i/10,10.+max(0,i-1)/10,st='1' if i==26 else '0') for i,d in enumerate(self.sessions)] for s in ('sh.600000','sz.000001')}
        bars['sz.000001'][25]=bar(self.sessions[25].isoformat(),'sz.000001',0,12.4,tradestatus='0')
        sdk=FakeSDK(basic=basic,calendar=calendar,bars=bars)
        self.retro=RetroDailyStore(self.source,today_fn=lambda:date(2026,9,17),now_fn=lambda:datetime(2026,9,17,tzinfo=timezone.utc))
        self.cap=self.retro.create_plan(self.days[0].isoformat(),self.days[-1].isoformat(),sdk=sdk)['capture_id']
        self.retro.fetch(self.cap,sdk=sdk)
        self.bridge=ArchivedDailyBridge(self.source)
        self.start,self.end=self.sessions[24].isoformat(),self.sessions[29].isoformat()
        self.md,self.js=synthetic_pair(self.root)
        self.store=ResearchSpecStore(self.output);self.m=self.store.import_pair(self.md,self.js,confirmed=True);self.sid=self.m['spec_id']
    def make(self,name='run',symbols='sh.600000 sz.000001'):
        folder=self.output/name;folder.mkdir()
        return folder,materialize(self.bridge,self.cap,symbols,self.start,self.end,folder)
    def test_original_response_matches_typed_data_and_real_fields_exposed(self):
        result=self.bridge.inspect(self.cap,'sh.600000 sz.000001',self.start,self.end)
        self.assertTrue(result['raw_and_typed_bytes_verified']);self.assertFalse(result['strict_pit_qualified'])
        rows=result['symbols'];self.assertEqual(rows[0]['st_rows'],1);self.assertEqual(rows[1]['suspended_rows'],1)
        self.assertIn('preclose',rows[0]['null_counts']);self.assertIn('turn',rows[0]['null_counts'])
    def test_provider_dates_state_and_percent_are_not_current_state_or_amount(self):
        folder,detail=self.make();frame=pl.read_parquet(folder/'observations.parquet')
        row=frame.filter((pl.col('symbol')=='sz.000001')&(pl.col('decision_date')==self.sessions[26].isoformat())).row(0,named=True)
        self.assertEqual(row['previous_vendor_trade_status'],0);self.assertEqual(row['previous_provider_state'],'SUSPENDED')
        self.assertIsNone(row['candidate_for_D']);self.assertIsNone(row['P01'])
        row=frame.filter((pl.col('symbol')=='sh.600000')&(pl.col('decision_date')==self.sessions[27].isoformat())).row(0,named=True)
        self.assertEqual(row['previous_vendor_is_st'],1);self.assertEqual(row['previous_provider_state'],'ST')
        self.assertEqual(row['previous_vendor_turnover_percent'],1.5);self.assertIsNone(row['P06']);self.assertIsNone(row['reference_price'])
        self.assertTrue(frame['historical_available_at'].is_null().all());self.assertFalse(detail['candidate_rows_generated'])
    def test_p07_median_lag_and_no_suspension_missing_fill(self):
        folder,_=self.make();frame=pl.read_parquet(folder/'observations.parquet')
        row=frame.filter((pl.col('symbol')=='sh.600000')&(pl.col('decision_date')==self.sessions[24].isoformat())).row(0,named=True)
        self.assertAlmostEqual(row['P07_raw'],12300/((10300+12200)/2))
        suspended=frame.filter((pl.col('symbol')=='sz.000001')&(pl.col('decision_date')==self.sessions[26].isoformat())).row(0,named=True)
        self.assertIsNone(suspended['P07_raw']);self.assertEqual(suspended['P07_status'],'MISSING_SOURCE')
    def test_pack_and_original_directory_read_identically(self):
        folder1,detail1=self.make('original')
        self.retro.consolidate(self.cap,confirmed=True,remove_originals=True)
        self.bridge=ArchivedDailyBridge(self.source)
        folder2,detail2=self.make('packed')
        self.assertTrue(detail2['source_evidence']['packed'])
        self.assertTrue(pl.read_parquet(folder1/'observations.parquet').equals(pl.read_parquet(folder2/'observations.parquet')))
        self.assertEqual(detail1['source_evidence']['symbols'],detail2['source_evidence']['symbols'])
    def test_replay_independent_of_external_source(self):
        folder,detail=self.make();self.source.rename(self.root/'offline')
        result=replay(folder,detail);self.assertTrue(result['equal']);self.assertFalse(result['external_source_required'])
    def test_frozen_bytes_tampering_fails_replay(self):
        folder,detail=self.make();(folder/'inputs/plan.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Frozen input changed'):replay(folder,detail)
    def test_unknown_dates_symbols_budgets_rejected_without_download(self):
        for symbols,start,end in [('sh.699999',self.start,self.end),('sh.600000 sh.600000',self.start,self.end),('sh.600000','2020-01-01',self.end),('sh.600000',self.end,self.start)]:
            with self.subTest(symbols=symbols,start=start),self.assertRaises(ValueError):self.bridge.load(self.cap,symbols,start,end)
        with patch('quantlab.agent.qm50_archived_inputs.MAX_INPUT_BYTES',10),self.assertRaises(ValueError):self.bridge.load(self.cap,'sh.600000',self.start,self.end)
    def test_requested_missing_archive_not_silently_dropped(self):
        directory=self.retro._symbol_dir(self.cap,'sz.000001');directory.rename(directory.with_name('not-visible'))
        with self.assertRaises(ValueError):self.make()
    def test_read_source_never_modified(self):
        before={str(p.relative_to(self.source)):sha(p.read_bytes()) for p in self.source.rglob('*') if p.is_file()}
        self.bridge.list_sources();self.make()
        after={str(p.relative_to(self.source)):sha(p.read_bytes()) for p in self.source.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
    def test_symlink_source_rejected(self):
        link=self.root/'linked';link.symlink_to(self.source,target_is_directory=True)
        with self.assertRaises(ValueError):ArchivedDailyBridge(link)
        path=self.retro._symbol_dir(self.cap,'sh.600000')/'daily.parquet';saved=path.with_name('saved');path.rename(saved);path.symlink_to(saved)
        with self.assertRaises(ValueError):self.bridge.load(self.cap,'sh.600000',self.start,self.end)
    def test_metadata_filters_only_for_diagnostics(self):
        result=self.bridge.inspect_symbols(self.cap,0,20,'has_suspension')
        self.assertEqual([r['symbol'] for r in result['records']],['sz.000001'])
        self.assertFalse(result['data_bytes_verified'])
        self.assertIn('never a historical candidate',result['note'])
    def test_native_runtime_reads_host_source_not_empty_test_output(self):
        from quantlab.agent.chat_cli import headless_chat_runtime
        with headless_chat_runtime(self.output,local_data_only=True,research_spec=self.sid,spec_source_workspace=self.source) as runtime:
            names={t['name'] for t in runtime.api.schemas()}
            self.assertIn('list_qm50_archived_sources',names);self.assertNotIn('run_qm50_archived_inputs',names)
            result=runtime.api.call('list_qm50_archived_sources',{})
            self.assertTrue(result['ok']);self.assertEqual(result['data']['captures'][0]['capture_id'],self.cap)
            denied=runtime.api.call('run_qm50_archived_inputs',{'spec_id':self.sid,'capture_id':self.cap,'symbols':'sh.600000','start':self.start,'end':self.end})
            self.assertEqual(denied['error']['code'],'SPEC_TEST_NOT_AUTHORIZED')
    def test_service_run_and_replay_with_explicit_test_permission(self):
        service=SpecTestService(self.output)
        with patch('quantlab.agent.spec_test_service.SUPPORTED_HASHES',self.m['files']):
            result=service.run_archived(self.sid,{'capture_id':self.cap,'symbols':'sh.600000','start':self.start,'end':self.end},self.source)
        self.assertEqual(result['status'],'MATERIALIZED_RETROSPECTIVE_INPUTS',result)
        self.assertTrue(service.replay_archived(self.sid,result['test_id'])['equal'])
        self.assertFalse(result['full_model_backtest']);self.assertFalse(result['alpha_verified'])
        self.assertTrue(service.audit(self.sid)['archived_daily_input_adapter']['implemented'])
        self.assertEqual(service.audit(self.sid)['full_backtest_status'],'BLOCKED')
    def test_cli_cannot_implicitly_read_another_workspace(self):
        from quantlab.agent.chat_cli import main
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(['--output',str(self.output),'--spec-source-workspace',str(self.source),'--ask','read'])

    def test_replay_preserves_unsorted_requested_symbols_after_json_canonicalization(self):
        folder,detail=self.make('reverse',symbols='sz.000001 sh.600000')
        self.assertTrue(replay(folder,json.loads(json.dumps(detail,sort_keys=True)))['equal'])
        stored=pl.read_parquet(folder/'observations.parquet')
        self.assertEqual(stored['symbol'].unique(maintain_order=True).to_list(),['sz.000001','sh.600000'])
    def test_comma_delimited_request_replays_with_exact_symbol_list(self):
        folder,detail=self.make('commas',symbols='sz.000001,sh.600000')
        self.assertEqual(detail['symbols'],['sz.000001','sh.600000'])
        self.assertTrue(replay(folder,detail)['equal'])
