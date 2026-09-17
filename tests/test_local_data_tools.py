"""Local data discovery is a product tool, not an injected research fixture."""
import hashlib
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import polars as pl
import test_core
from quantlab.agent.local_data_tools import LocalMarketDataTools, MAX_FILE_BYTES
from quantlab.agent.proposal_tools import ResearchProposalAPI

class LocalDataToolsTests(TestCase):
    def setUp(self):
        self.fixture=test_core.CoreTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.root
        self.tools=LocalMarketDataTools(self.root)
        self.inventory={'timeframe':'1d','adjustment':'qfq','offset':0,'limit':2}
        self.profile={'timeframe':'1d','adjustment':'qfq','symbols':' '.join(self.fixture.symbols),
                      'start':'2025-01-01','end':'2025-01-10'}
    def test_inventory_exact_bytes_pagination_and_no_writes(self):
        paths={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        result=self.tools.call('list_local_market_data',self.inventory)
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['data']['total'],5)
        self.assertEqual(result['data']['next_offset'],2)
        row=result['data']['records'][0]
        self.assertEqual((row['first_date'],row['last_date'],row['rows']),('2025-01-01','2025-01-10',10))
        self.assertEqual(row['source']['sha256'],paths[self.root/row['source']['relative_file']])
        self.assertEqual(paths,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()})
    def test_profile_loads_via_production_provider_and_counts_ic_cross_sections(self):
        result=self.tools.call('inspect_local_market_data',self.profile)
        self.assertTrue(result['ok'],result)
        self.assertTrue(result['data']['request_loadable'])
        self.assertEqual(result['data']['timestamps_with_at_least_3_bars'],10)
        self.assertFalse(result['data']['calendar_completeness_verified'])
        self.assertEqual(result['data']['records'][0]['normalized_rows'],10)
        two=self.tools.call('inspect_local_market_data',{**self.profile,'symbols':' '.join(self.fixture.symbols[:2])})
        self.assertEqual(two['data']['timestamps_with_at_least_3_bars'],0)
    def test_missing_quantity_is_reported_never_imputed_or_dropped(self):
        path=self.root/'lake/silver/qfq_kline_daily/sh_600000.parquet'
        frame=pl.read_parquet(path).with_columns(pl.when(pl.col('date')==self.fixture.start).then(None).otherwise(pl.col('volume')).alias('volume'))
        frame.write_parquet(path); before=path.read_bytes()
        result=self.tools.call('inspect_local_market_data',self.profile)
        self.assertTrue(result['ok'],result)
        self.assertFalse(result['data']['request_loadable'])
        row=result['data']['records'][0]
        self.assertEqual(row['rows'],10); self.assertEqual(row['null_counts']['volume'],1)
        self.assertFalse(row['loadable']); self.assertIn('Null in required',row['error'])
        self.assertEqual(path.read_bytes(),before)
    def test_bad_fields_missing_symbols_and_empty_interval(self):
        for name,args in [('list_local_market_data',{**self.inventory,'limit':True}),
                          ('list_local_market_data',{**self.inventory,'path':'/tmp'}),
                          ('list_local_market_data',{**self.inventory,'timeframe':'1m'}),
                          ('inspect_local_market_data',{**self.profile,'symbols':'../../secret'}),
                          ('inspect_local_market_data',{**self.profile,'end':'2024-01-01'})]:
            with self.subTest(args=args): self.assertFalse(self.tools.call(name,args)['ok'])
        result=self.tools.call('inspect_local_market_data',{**self.profile,'symbols':'sh.699999'})
        self.assertFalse(result['data']['request_loadable'])
        empty=self.tools.call('inspect_local_market_data',{**self.profile,'start':'2026-01-01','end':'2026-01-02'})
        self.assertFalse(empty['data']['request_loadable'])
        self.assertEqual(empty['data']['records'][0]['rows'],0)
    def test_symlink_file_and_parent_rejected(self):
        folder=self.root/'lake/silver/qfq_kline_daily'
        path=folder/'sh_699999.parquet'; path.symlink_to(folder/'sh_600000.parquet')
        result=self.tools.call('inspect_local_market_data',{**self.profile,'symbols':'sh.699999'})
        self.assertIn('SYMLINK_REJECTED',result['data']['records'][0]['error'])
        folder.rename(folder.with_name('original'))
        folder.symlink_to(folder.with_name('original'),target_is_directory=True)
        result=self.tools.call('list_local_market_data',self.inventory)
        self.assertFalse(result['ok']); self.assertIn('SYMLINK_REJECTED',result['error']['message'])
    def test_managed_marker_is_not_silently_treated_as_mqc(self):
        (self.root/'baostock-dataset.json').write_text('{bad json')
        result=self.tools.call('list_local_market_data',self.inventory)
        self.assertFalse(result['ok']); self.assertIn('MANAGED_DISCOVERY_UNSUPPORTED',result['error']['message'])
    def test_size_budget_and_missing_root(self):
        with patch('quantlab.agent.local_data_tools.MAX_FILE_BYTES',1):
            result=self.tools.call('list_local_market_data',self.inventory)
            self.assertTrue(all(r['status']=='unreadable' for r in result['data']['records']))
        self.assertFalse(LocalMarketDataTools(None).call('list_local_market_data',self.inventory)['ok'])
    def test_product_proposal_api_includes_tools_and_dsl_contract(self):
        output=self.root/'output'; output.mkdir()
        api=ResearchProposalAPI(output,self.root)
        names={t['name'] for t in api.schemas()}
        self.assertTrue({'list_local_market_data','inspect_local_market_data'}<=names)
        self.assertTrue(api.call('list_local_market_data',self.inventory)['ok'])
        contract=api.call('describe_factor',{'factor_id':'DSL.RESTRICTED','version':'1.0.0'})['data']['expression_contract']
        self.assertFalse(contract['temporal_nesting_allowed']); self.assertIn('volume',contract['fields'])
        self.assertNotIn('run_shell',names)
    def test_chat_local_mode_has_no_live_quote_or_keychain_access(self):
        from quantlab.agent.chat_cli import headless_chat_runtime
        from quantlab.agent.model_config import ModelConfig
        from test_agent_chat import FakeProvider
        output=self.root/'chat'; output.mkdir()
        with patch('quantlab.agent.fuyao_mcp.load_api_key',side_effect=AssertionError('keychain accessed')):
            with headless_chat_runtime(output,self.root,local_data_only=True) as runtime:
                names={t['name'] for t in runtime.api.schemas()}
                self.assertIn('list_local_market_data',names)
                self.assertNotIn('get_fuyao_stock_context',names)
                self.assertIsNone(runtime.live_quotes)
                model=FakeProvider([('list_local_market_data',self.inventory)])
                result=runtime.send(runtime.store.create(),'检查sh.600000的本地资料',ModelConfig(),allow_send=True,provider=model)
                self.assertEqual(result['host_live_quote_queries'],0)
                self.assertTrue(model.results[0]['ok'])

    def test_native_spec_error_explains_wrong_version_key_without_accepting_it(self):
        from quantlab.workbench.jobs import prepare
        spec={'symbols':list(self.fixture.symbols),'start':'2025-01-01','end':'2025-01-10',
              'factor':'BASE.MOMENTUM','factor_version':'1.0.0','parameters':{'lookback':2}}
        with self.assertRaisesRegex(ValueError,'factor/version'):
            prepare(spec)
        spec['version']=spec.pop('factor_version')
        self.assertEqual(prepare(spec).config.factor_version,'1.0.0')
    def test_native_cli_forwards_local_only_and_rejects_visible_gui(self):
        import contextlib,io
        from quantlab.agent.chat_cli import main
        from quantlab.agent.model_config import ModelConfig
        with patch('quantlab.agent.chat_cli.ChatRuntime') as runtime, patch('quantlab.agent.chat_cli.load_model_config',return_value=ModelConfig()):
            runtime.return_value.store.create.return_value='test'
            runtime.return_value.send.return_value={'text':'fixture'}
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--output',str(self.root),'--data-root',str(self.root),'--ask','本地检查','--local-data-only','--accept-model-service']),0)
            self.assertTrue(runtime.call_args.kwargs['local_data_only'])
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            main(['--output',str(self.root),'--gui','--local-data-only'])
    def test_real_five_minute_profile_does_not_substitute_daily(self):
        result=self.tools.call('inspect_local_market_data',{**self.profile,'timeframe':'5m','adjustment':'raw'})
        self.assertTrue(result['ok'],result)
        self.assertTrue(result['data']['request_loadable'])
        self.assertTrue(all('/stock_kline_min5/' in r['source']['relative_file'] for r in result['data']['records']))
