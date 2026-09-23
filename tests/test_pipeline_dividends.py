import unittest
from dataclasses import replace
from datetime import date,timedelta
from tempfile import TemporaryDirectory
from pathlib import Path
import polars as pl
from polars.testing import assert_frame_equal
from test_holdout import Provider
import test_holdout
from test_market_paper import fixture
from quantlab.processing.pipeline import PipelineConfig,FactorPipeline
from quantlab.execution.backtest import OpenExecutionBacktester
from quantlab.execution.rules import MarketRules
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account
from quantlab.storage.experiments import load_record
from _optional import requires_vnpy


class PipelineTests(unittest.TestCase):
    def test_training_freeze_and_holdout_wiring(self):
        helper=test_holdout.HoldoutTests();helper.setUp()
        cfg=replace(helper.cfg,processor=PipelineConfig([{'method':'replace_inf'},{'method':'fill_na'},
            {'method':'winsorize'},{'method':'robust_zscore'}]))
        with TemporaryDirectory() as tmp:
            first=helper.runner(Provider(),Path(tmp)).run(cfg,helper.split)
            changed=helper.runner(Provider(100),Path(tmp)).run(cfg,helper.split)
            states=[]
            for period in first.periods:
                record=load_record(Path(period['artifact_path'])/'experiment.json')
                states.append(record['manifest']['processor']['state_hash'])
            self.assertEqual(len(set(states)),1)
            for a,b in zip(first.periods[:2],changed.periods[:2]):
                assert_frame_equal(pl.read_parquet(Path(a['artifact_path'])/'observations.parquet'),
                    pl.read_parquet(Path(b['artifact_path'])/'observations.parquet'))
            valid=pl.read_parquet(Path(first.periods[1]['artifact_path'])/'observations.parquet')
            self.assertTrue(valid['value'].is_not_null().all())

    def test_inf_missing_and_prefit_availability(self):
        market=Provider().load(None).bars
        values=market.select('symbol','datetime','available_at').with_columns(pl.Series('value',[1.,float('inf'),None,3.,5.,6.,7.,8.,9.,10.,11.,12.]))
        mask=values.select('symbol','datetime').with_columns(pl.lit(True).alias('eligible'))
        cfg=PipelineConfig([{'method':'replace_inf'},{'method':'fill_na'},{'method':'robust_zscore'}],date(2025,1,1),date(2025,1,4))
        pipeline=FactorPipeline(cfg).fit(values,mask);result=pipeline.transform(values,mask)
        self.assertTrue(result['value'].drop_nulls().is_finite().all())
        self.assertEqual(pipeline.states[1]['value'],2.)
        self.assertIsNone(result['value'][0])
        self.assertEqual(result['available_at'][0],values['available_at'][0])
        with self.assertRaises(ValueError):FactorPipeline(PipelineConfig([{'method':'clip','lower':0,'upper':1}])).fit(values,mask)


class DividendTests(unittest.TestCase):
    def setup_account(self):
        market,targets,rules,cfg=fixture()
        market=market.with_columns(pl.lit(10.).alias('open'),pl.lit(10.).alias('close'),pl.lit(11.).alias('high'),pl.lit(9.).alias('low'))
        dates=market['datetime'].to_list()
        market=market.with_columns(pl.when(pl.col('datetime')>=dates[2]).then(9.).otherwise(pl.col('open')).alias('open'),
            pl.when(pl.col('datetime')>=dates[2]).then(9.).otherwise(pl.col('close')).alias('close'))
        targets=targets.with_columns(pl.Series('weight',[.5,0.,0.,0.,0.]))
        action={'action_id':'cash-1','symbol':'sh.600000','record_at':dates[1], 'ex_at':dates[2].replace(hour=9,minute=30),
            'pay_at':dates[3].replace(hour=9,minute=30),'available_at':dates[0], 'cash_per_share':1.,'tax_rate':0.,'source':'synthetic accounting fixture'}
        cfg=replace(cfg,initial_cash=10000,slippage_bps=0,commission_bps=0,minimum_commission=0,corporate_actions=[action])
        for r in rules:
            r.update(commission_bps=0.,minimum_commission=0.,sell_tax_bps=0.,transfer_bps=0.)
        return market,targets,MarketRules(rules),cfg

    @requires_vnpy
    def test_record_ownership_receivable_payment_native_and_restart(self):
        from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
        from quantlab.adapters.vnpy import compare_backends
        market,targets,rules,cfg=self.setup_account()
        ref=OpenExecutionBacktester(cfg,rules).run(targets,market)
        curve,_,_,summary=ref
        self.assertEqual(curve['equity'].to_list(),[10000.]*5)
        self.assertEqual(curve['dividend_receivable'].to_list(),[0.,0.,500.,0.,0.])
        self.assertEqual(summary['dividend_cash'],500.)
        self.assertEqual(compare_backends(ref,VnpyRulesBacktester(cfg,rules).run(targets,market))['status'],'matched')
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'account.json'
            first=PaperAccount(path).advance(market.head(3),targets.head(3),rules,cfg)
            self.assertEqual(first['summary']['dividend_receivable'],500.)
            final=PaperAccount(path).advance(market,targets,rules,cfg)
            self.assertEqual(PaperAccount(path).advance(market,targets,rules,cfg),final)
            self.assertEqual(reconcile_account(path)['status'],'matched')

    def test_late_availability_and_missing_record_date_fail_closed(self):
        market,targets,rules,cfg=self.setup_account()
        action={**cfg.corporate_actions[0],'available_at':market['datetime'][-1]}
        with self.assertRaisesRegex(ValueError,'availability'):OpenExecutionBacktester(replace(cfg,corporate_actions=[action]),rules).run(targets,market)
        result=OpenExecutionBacktester(replace(cfg,corporate_actions=[action],corporate_action_mode='retrospective'),rules).run(targets,market)
        self.assertEqual(result[3]['corporate_action_mode'],'retrospective')
        with self.assertRaisesRegex(ValueError,'record-date'):OpenExecutionBacktester(cfg,rules).run(targets,market.filter(pl.col('datetime')!=market['datetime'][1]))


class RulesAuditTests(unittest.TestCase):
    def test_suspended_session_without_price_bounds_is_not_called_unbounded(self):
        from quantlab.execution.rules_audit import audit_market_rules
        market,_,records,_=fixture();record={**records[0],'suspended':True,'limit_up':None,'limit_down':None}
        result=audit_market_rules(MarketRules([record]),[record['symbol']],[market['datetime'][0].date()])
        self.assertEqual(result['status'],'covered');self.assertEqual(result['suspended_sessions'],1)
        self.assertEqual(result['suspended_sessions_without_price_bounds'],1)
        self.assertEqual(result['explicitly_unbounded_sessions'],0)

    def test_no_order_sessions_and_late_rules_are_counted(self):
        from quantlab.execution.rules_audit import audit_market_rules
        market,_,records,_=fixture()
        records[1]['available_at']=records[1]['expires_at']
        dates=market['datetime'].dt.date().to_list()
        result=audit_market_rules(MarketRules(records),['sh.600000','sz.000001'],dates)
        self.assertEqual(result['expected_symbol_sessions'],10)
        self.assertEqual(result['covered_symbol_sessions'],4)
        self.assertEqual(result['late_available_sessions'],1)
        self.assertEqual(result['status'],'incomplete')
