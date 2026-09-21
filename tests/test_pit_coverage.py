import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

import polars as pl

from quantlab.data.pit_coverage import strict_pit_coverage
from quantlab.data.pit_evidence import archive_pit_evidence


class StrictPITCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'artifacts';self.output.mkdir()

    def document(self):
        path=self.root/'official.html';path.write_text('official historical disclosure fixture')
        return path

    def test_empty_root_is_gap_inventory_not_fake_percentage(self):
        value=strict_pit_coverage(self.root)
        self.assertEqual(value['status'],'NO_STRICT_EVIDENCE')
        self.assertIsNone(value['overall_strict_pit_coverage_ratio'])
        self.assertFalse(value['dataset_strict_pit_certified'])
        self.assertEqual(value['strict_evidence']['verified_records'],0)
        codes={r['code'] for r in value['gaps']}
        self.assertEqual(codes & {'NO_VERIFIED_UNIVERSE_ELIGIBILITY','NO_VERIFIED_SECURITY_STATUS',
            'NO_VERIFIED_INDUSTRY_MEMBERSHIP','NO_VERIFIED_DAILY_MARKET_CAP'},
            {'NO_VERIFIED_UNIVERSE_ELIGIBILITY','NO_VERIFIED_SECURITY_STATUS','NO_VERIFIED_INDUSTRY_MEMBERSHIP','NO_VERIFIED_DAILY_MARKET_CAP'})
        self.assertIn('NO_VERIFIED_PIT_UNIVERSE_RECEIPTS',codes)
        self.assertIn('NO_COMPLETE_DAILY_SECURITY_STATUS_RECEIPTS',codes)
        self.assertEqual(value['strict_evidence']['security_status_coverage_archive']['verified_receipts'],0)

    def seed_retrospective(self):
        bars=self.root/'lake/bronze/provider=baostock/stock_kline_daily';bars.mkdir(parents=True)
        for symbol in ('sh.600000','sz.000001'):
            pl.DataFrame({'date':[date(2025,1,2),date(2025,1,3)],'code':[symbol,symbol],
                'open':[10.,10.1],'high':[10.2,10.3],'low':[9.9,10.0],'close':[10.1,10.2],
                'volume':[1000.,1100.],'amount':[10000.,11100.],'adjustflag':['3','3'],
                'fetch_ts':['2026-09-04T21:00:00']*2}).write_parquet(bars/(symbol.replace('.','_')+'.parquet'))
        basic=self.root/'lake/bronze/provider=baostock/stock_basic';basic.mkdir(parents=True)
        pl.DataFrame({'code':['sh.600000','sz.000001'],'code_name':['浦发银行','平安银行'],
            'ipoDate':['1999-11-10','1991-04-03'],'outDate':['',''],'type':['1','1'],'status':['1','1']}).write_parquet(basic/'stock_basic.parquet')
        industry=self.root/'lake/bronze/provider=baostock/industry';industry.mkdir(parents=True)
        pl.DataFrame({'updateDate':['2026-08-31']*2,'code':['sh.600000','sz.000001'],
            'code_name':['浦发银行','平安银行'],'industry':['J66货币金融服务']*2,
            'industryClassification':['证监会行业分类']*2}).write_parquet(industry/'industry.parquet')

    def test_retrospective_sources_are_visible_but_never_strict(self):
        self.seed_retrospective();value=strict_pit_coverage(self.root)
        self.assertEqual(value['retrospective_inventory']['bars']['rows'],4)
        self.assertEqual(value['retrospective_inventory']['bars']['files_with_isST'],0)
        self.assertEqual(value['retrospective_inventory']['industry']['snapshot_dates'],['2026-08-31'])
        self.assertEqual(value['status'],'NO_STRICT_EVIDENCE')
        codes={r['code'] for r in value['gaps']}
        self.assertIn('HISTORICAL_STATUS_FIELDS_NOT_IN_BAR_LAKE',codes)
        self.assertIn('INDUSTRY_SOURCE_IS_SNAPSHOT_ONLY',codes)

    def test_inventory_ignores_catalog_view_bound_to_other_data_root(self):
        import duckdb
        self.seed_retrospective()
        with tempfile.TemporaryDirectory() as outside:
            foreign=Path(outside)/'foreign.parquet'
            pl.DataFrame({'date':[date(2001,1,1)],'code':['sh.600999'],
                'fetch_ts':['2001-01-02']}).write_parquet(foreign)
            catalog=self.root/'catalog/mqc.duckdb';catalog.parent.mkdir()
            with duckdb.connect(str(catalog)) as con:
                con.execute("CREATE VIEW bronze_stock_kline_daily AS SELECT * FROM read_parquet('"+
                    str(foreign).replace("'","''")+"')")
            before=catalog.read_bytes()
            value=strict_pit_coverage(self.root)['retrospective_inventory']['bars']
            self.assertEqual(value['rows'],4)
            self.assertEqual(value['date_range'],{'min':'2025-01-02','max':'2025-01-03'})
            self.assertEqual(value['symbols'],2)
            self.assertEqual(catalog.read_bytes(),before)

    def test_inventory_does_not_open_broken_or_locked_catalog(self):
        self.seed_retrospective()
        catalog=self.root/'catalog/mqc.duckdb';catalog.parent.mkdir();catalog.write_bytes(b'not a database')
        value=strict_pit_coverage(self.root)['retrospective_inventory']['bars']
        self.assertEqual(value['rows'],4)
        self.assertEqual(value['inventory_source'],'root_bound_parquet_scan')
        self.assertEqual(catalog.read_bytes(),b'not a database')

    def test_inventory_rejects_symlinked_daily_file(self):
        from quantlab.data.pit_coverage import _bars_inventory
        self.seed_retrospective()
        folder=self.root/'lake/bronze/provider=baostock/stock_kline_daily'
        with tempfile.TemporaryDirectory() as outside:
            foreign=Path(outside)/'foreign.parquet'
            pl.DataFrame({'date':[date(2001,1,1)],'code':['sh.600999']}).write_parquet(foreign)
            (folder/'sh_600999.parquet').symlink_to(foreign)
            with self.assertRaisesRegex(ValueError,'symlink'):
                _bars_inventory(self.root)

    def test_inventory_missing_fetch_timestamp_is_explicit_not_error(self):
        from quantlab.data.pit_coverage import _bars_inventory
        folder=self.root/'lake/bronze/provider=baostock/stock_kline_daily';folder.mkdir(parents=True)
        pl.DataFrame({'date':[date(2025,1,2)],'code':['sh.600000']}).write_parquet(folder/'sh_600000.parquet')
        value=_bars_inventory(self.root)
        self.assertEqual(value['rows'],1)
        self.assertEqual(value['files_with_fetch_ts'],0)
        self.assertEqual(value['fetch_ts_range'],{'min':None,'max':None})
        self.assertFalse(value['strict_pit_certified'])

    def test_small_inventory_rejects_symlinked_ancestor(self):
        from quantlab.data.pit_coverage import _small_table
        with tempfile.TemporaryDirectory() as outside:
            foreign=Path(outside);(foreign/'stock_basic.parquet').write_bytes(b'not read')
            provider=self.root/'lake/bronze/provider=baostock';provider.mkdir(parents=True)
            (provider/'stock_basic').symlink_to(foreign,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'symlink'):
                _small_table(self.root,'lake/bronze/provider=baostock/stock_basic/stock_basic.parquet','stock_basic')

    def test_silver_inventory_rejects_symlinked_folder_and_file(self):
        from quantlab.data.pit_coverage import _silver_inventory
        with tempfile.TemporaryDirectory() as outside:
            foreign=Path(outside);pl.DataFrame({'symbol':['sh.600999']}).write_parquet(foreign/'rows.parquet')
            silver=self.root/'lake/silver';silver.mkdir(parents=True)
            linked=silver/'security_status';linked.symlink_to(foreign,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'symlink'):_silver_inventory(self.root)
            linked.unlink();linked.mkdir()
            (linked/'rows.parquet').symlink_to(foreign/'rows.parquet')
            with self.assertRaisesRegex(ValueError,'symlink'):_silver_inventory(self.root)

    def test_silver_inventory_counts_nested_local_files_without_writes(self):
        from quantlab.data.pit_coverage import _silver_inventory
        folder=self.root/'lake/silver/security_status/year=2025';folder.mkdir(parents=True)
        pl.DataFrame({'symbol':['sh.600000','sz.000001']}).write_parquet(folder/'rows.parquet')
        before=sorted(str(p) for p in self.root.rglob('*'))
        result=_silver_inventory(self.root)
        self.assertEqual(result['security_status'],{'files':1,'present':True,'rows':2})
        self.assertEqual(before,sorted(str(p) for p in self.root.rglob('*')))

    def archive_all_kinds(self):
        doc=self.document();url='https://www.cninfo.com.cn/new/disclosure/detail?stockCode=600000'
        archive_pit_evidence(self.root,'universe_eligibility',[
            {'symbol':'sh.600000','effective_at':'2024-12-31T15:00:00+08:00','available_at':'2025-01-02T09:00:00+08:00','eligible':True},
            {'symbol':'sh.600000','effective_at':'2025-06-01T15:00:00+08:00','available_at':'2025-06-02T09:00:00+08:00','eligible':False}],
            url,'2024-12-31T10:00:00+08:00',doc,confirm_publication_time=True)
        archive_pit_evidence(self.root,'security_status',[{
            'symbol':'sh.600000','effective_at':'2025-01-03T09:30:00+08:00','available_at':'2025-01-02T20:00:00+08:00',
            'tradable':True,'risk_warning':'ST','source':url}],url,'2025-01-02T19:00:00+08:00',doc,
            confirm_publication_time=True)
        archive_pit_evidence(self.root,'industry_membership',[{
            'symbol':'sh.600000','sector':'J66货币金融服务','effective_at':'2025-01-01T00:00:00+08:00',
            'available_at':'2025-01-02T09:00:00+08:00','source':url}],url,'2024-12-31T10:00:00+08:00',doc,
            confirm_publication_time=True)
        archive_pit_evidence(self.root,'daily_market_cap',[{
            'symbol':'sh.600000','market_cap':1.2e11,'effective_at':'2025-01-02T15:00:00+08:00',
            'available_at':'2025-01-02T15:30:00+08:00','expires_at':'2025-01-03T15:30:00+08:00','source':url}],
            url,'2025-01-02T15:10:00+08:00',doc,confirm_publication_time=True)

    def test_verified_receipts_are_grouped_by_year_symbol_and_scope(self):
        self.archive_all_kinds()
        value=strict_pit_coverage(self.root,symbols=['sh.600000','sz.000001'],start='2025-01-01',end='2025-12-31')
        self.assertEqual(value['status'],'PARTIAL_EVIDENCE')
        gap_codes={row['code'] for row in value['gaps']}
        self.assertIn('NO_VERIFIED_PIT_UNIVERSE_RECEIPTS',gap_codes)
        self.assertIn('NO_COMPLETE_DAILY_SECURITY_STATUS_RECEIPTS',gap_codes)
        by=value['strict_evidence']['by_kind']
        self.assertEqual(by['universe_eligibility']['verified_statements'],1)
        self.assertEqual(by['security_status']['verified_statements'],1)
        self.assertEqual(by['industry_membership']['years'][0]['year'],2025)
        self.assertEqual(by['daily_market_cap']['unique_symbols'],1)
        self.assertEqual(by['universe_eligibility']['requested_symbols_with_evidence'],['sh.600000'])
        self.assertEqual(by['universe_eligibility']['requested_symbols_missing_evidence'],['sz.000001'])
        self.assertFalse(value['dataset_strict_pit_certified'])

    def test_tampered_document_is_invalid_not_covered(self):
        self.archive_all_kinds()
        docs=list((self.root/'research/pit_evidence/documents').glob('*.bin'))
        self.assertEqual(len(docs),1);docs[0].write_bytes(b'tampered')
        value=strict_pit_coverage(self.root)
        self.assertEqual(value['strict_evidence']['invalid_records'],5)
        self.assertEqual(value['strict_evidence']['verified_records'],0)
        self.assertIn('INVALID_PIT_EVIDENCE_RECEIPTS',{r['code'] for r in value['gaps']})

    def test_cli_and_model_tool_are_read_only(self):
        from quantlab.agent.pit_coverage_cli import main
        from quantlab.agent.market_data_tools import MarketDataResearchAPI
        before=list(self.root.rglob('*'))
        stream=io.StringIO()
        with redirect_stdout(stream):code=main(['--data-root',str(self.root),'--start','2025-01-01','--end','2025-12-31'])
        self.assertEqual(code,0);self.assertIn('NO_STRICT_EVIDENCE',stream.getvalue())
        api=MarketDataResearchAPI(self.output,self.root);names={t['name'] for t in api.schemas()}
        self.assertIn('get_strict_pit_coverage',names)
        self.assertFalse(any(name in names for name in ('archive_pit_evidence','download_pit_evidence','certify_strict_pit')))
        result=api.call('get_strict_pit_coverage',{'symbols':'sh.600000','start':'2025-01-01','end':'2025-12-31','detail_limit':20})
        self.assertTrue(result['ok'],result);self.assertFalse(result['data']['dataset_strict_pit_certified'])
        from quantlab.agent.system_health import SystemHealthService
        health=SystemHealthService(self.output,self.root).build()['components']['pit_playbook']
        self.assertTrue(health['evidence']['pit_coverage']['available'])
        self.assertEqual(health['evidence']['pit_coverage']['claim'],'evidence_presence_only_not_dataset_certificate')
        self.assertEqual([p for p in self.root.rglob('*') if p not in before],[])


if __name__=='__main__':unittest.main()
