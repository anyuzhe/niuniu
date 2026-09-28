import json
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
import polars as pl
import test_published_daily_research as fixtures
from quantlab.execution.backtest import ExecutionConfig,OpenExecutionBacktester,cost_model_warnings
from quantlab.execution.virtual_qfq import blocked_reason,DISCLOSURE,validate_virtual_range
from quantlab.data.validation import ordered_bars
from quantlab.workbench.jobs import prepare,execute
from quantlab.storage.codec import digest

class VirtualLedgerTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.PublishedDailyTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.fx.export();self.bars=self.fx.read().bars
        self.cfg=ExecutionConfig(initial_cash=1_000_000,price_mode='virtual_qfq',statutory_fees=True,
            max_actual_exposure=.8,max_actual_position=.4,slippage_bps=5,max_volume_participation=.01)
        self.targets=self.bars.select('symbol','datetime','available_at',pl.lit(.2).alias('weight'))
    def test_explicit_mode_is_required_and_real_account_keeps_blocker(self):
        for mode in ('research','account'):
            with self.assertRaisesRegex(ValueError,'execution is forbidden'):
                OpenExecutionBacktester(replace(self.cfg,price_mode=mode)).run(self.targets,self.bars)
        with self.assertRaisesRegex(ValueError,'execution is forbidden'):ordered_bars(self.bars,for_execution=True)
    def test_virtual_units_balance_cash_fills_and_keep_source_unchanged(self):
        before=self.bars.clone();engine=OpenExecutionBacktester(replace(self.cfg,max_volume_participation=.5))
        curve,fills,rejects,summary=engine.run(self.targets,self.bars)
        self.assertTrue(before.equals(self.bars));self.assertNotIn('vendor_previous_close',self.bars.columns)
        self.assertEqual(curve.height,12);self.assertTrue(fills)
        self.assertTrue(all(abs(r['cash']+r['position_value']-r['equity'])<1e-6 for r in curve.iter_rows(named=True)))
        self.assertGreaterEqual(curve['cash'].min(),0)
        self.assertFalse(any(f['symbol']==self.fx.symbols[1] and f['side']=='buy' for f in fills))
        self.assertTrue(any(r['reason']=='virtual_st_buy_blocked' for r in rejects))
        self.assertFalse(any(f['symbol']==self.fx.symbols[0] and f['filled_at'].date()==date(2024,1,6) for f in fills))
        self.assertGreater(summary['commission'],0);self.assertGreater(summary['transfer_fee'],0)
    def test_t_plus_one_applies_to_virtual_units(self):
        with self.assertRaisesRegex(ValueError,r'T\+1'):replace(self.cfg,t_plus_one=False).validate_price_inputs()
        with self.assertRaisesRegex(ValueError,'ST'):replace(self.cfg,allow_st=True).validate_price_inputs()
    def test_no_real_rules_matcher_or_override(self):
        with self.assertRaisesRegex(ValueError,'market rules'):self.cfg.validate_price_inputs(object())
        with self.assertRaisesRegex(ValueError,'overrides'):replace(self.cfg,limit_pct=.1).validate_price_inputs()
        with self.assertRaisesRegex(ValueError,'virtual-unit'):OpenExecutionBacktester(self.cfg,matcher=object()).run(self.targets,self.bars)
    def test_unsupported_source_and_first_suspension_are_not_filled(self):
        with self.assertRaisesRegex(ValueError,'exact published'):ordered_bars(self.bars.filter(pl.col('bs_trade_status')==1).drop('input_contract'),for_execution=True,virtual_qfq=True)
        view=self.bars.filter(pl.col('datetime').dt.date()>=date(2024,1,6))
        with self.assertRaisesRegex(ValueError,'observed first'):OpenExecutionBacktester(self.cfg).run(self.targets,view)
    def test_modeled_board_limits_explicit_not_historical_certification(self):
        self.assertIsNotNone(blocked_reason('sh.600001',11,10,True,0))
        self.assertIsNone(blocked_reason('sz.300001',11,10,True,0))
        self.assertIsNotNone(blocked_reason('sh.688001',12,10,True,0))
        self.assertIsNotNone(blocked_reason('sh.600001',9.5,10,False,1))
        self.assertIsNone(blocked_reason('sz.300001',9.5,10,False,1))
        self.assertEqual(blocked_reason('sh.600001',10,10,True,1),'virtual_st_buy_blocked')
        self.assertTrue(any('不是官方' in s for s in DISCLOSURE['limitations']))
    def test_historical_and_exchange_range_are_bounded(self):
        with self.assertRaisesRegex(ValueError,'code family'):validate_virtual_range(self.bars.with_columns(pl.lit('bj.830000').alias('symbol')))
        with self.assertRaisesRegex(ValueError,'2020'):validate_virtual_range(self.bars.with_columns(pl.col('datetime').dt.offset_by('-5y')))
    def test_no_observable_source_is_modified_by_execution_study(self):
        before={str(p):p.read_bytes() for p in self.fx.out.rglob('*') if p.is_file()}
        spec={'question':'virtual cash simulation fixture','symbols':self.fx.symbols,'timeframe':'1d','start':'2024-01-01','end':'2024-01-12',
            'adjustment':'qfq','qualification':'research_only','factor':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':2},
            'horizons':[2],'quantiles':3,'replay':True,'mode':'execution',
            'execution':{'initial_cash':1_000_000,'price_mode':'virtual_qfq','statutory_fees':True,'exposure':.6,'top_n':3},
            'portfolio':{'max_position':.3,'max_exposure':.6}}
        result=execute(prepare(spec),self.fx.out,self.fx.root/'runs')
        record=json.loads((result.artifact_path/'experiment.json').read_text())
        self.assertEqual(record['simulation_contract']['format'],DISCLOSURE['format']);self.assertFalse(record['simulation_contract']['real_account'])
        self.assertTrue(any('虚拟' in x for x in record['limitations']))
        self.assertFalse(any('精细账户模式' in x for x in record['limitations']))
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.fx.out.rglob('*') if p.is_file()})
    def packaged(self):
        from dataclasses import asdict
        from quantlab.trading.strategy_package import compile_strategy,FORMAT,LIFECYCLE
        spec={'question':'virtual packaged fixture','symbols':self.fx.symbols,'timeframe':'1d','start':'2024-01-01','end':'2024-01-12',
            'adjustment':'qfq','qualification':'research_only','factor':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':2},
            'horizons':[2],'quantiles':3,'replay':True,'mode':'execution','execution_backend':'open','execution':asdict(self.cfg),
            'portfolio':{'weighting':'equal','max_position':.3,'max_exposure':.6,'max_turnover':None}}
        pkg={'format':FORMAT,'strategy_key':'virtual-fixture','name':'virtual fixture','version':'1','lifecycle':dict(LIFECYCLE),'spec':spec}
        return execute(prepare(compile_strategy(pkg)['spec']),self.fx.out,self.fx.root/'packaged-runs')
    def test_native_archive_read_keeps_virtual_denomination_and_does_not_reexecute(self):
        from quantlab.trading.strategy_run_catalog import get_strategy_run
        from quantlab.agent.catalog import ReadOnlyResearchAPI
        result=self.packaged();root=result.artifact_path.parent
        before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
        detail=get_strategy_run(root,result.run_id)
        self.assertEqual(detail['simulation_contract'],DISCLOSURE)
        api=ReadOnlyResearchAPI(root);response=api.call('get_strategy_run',{'run_id':result.run_id})
        self.assertTrue(response['ok'],response);self.assertFalse(response['data']['simulation_contract']['real_account'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})
    def test_archived_virtual_disclosure_cannot_be_removed_or_promoted(self):
        from quantlab.trading.strategy_run_catalog import get_strategy_run
        result=self.packaged();path=result.artifact_path/'experiment.json'
        original=json.loads(path.read_text())
        for value in (None,{**DISCLOSURE,'real_account':True}):
            record={**original,'simulation_contract':value};path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'disclosure'):get_strategy_run(path.parent.parent,result.run_id)
    def test_warnings_never_claim_missing_limits_or_precise_account(self):
        warnings=cost_model_warnings(self.cfg)
        self.assertFalse(any('未模拟涨跌停' in w for w in warnings));self.assertTrue(any('名义人民币' in w for w in warnings))

if __name__=='__main__':unittest.main()
