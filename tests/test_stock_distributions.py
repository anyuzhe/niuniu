import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import polars as pl
import test_pipeline_dividends
from quantlab.execution.backtest import OpenExecutionBacktester
from quantlab.execution.corporate_actions import CashDividends
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account
from _optional import requires_vnpy


class StockDistributionTests(unittest.TestCase):
    def account(self):
        market,targets,rules,cfg=test_pipeline_dividends.DividendTests().setup_account()
        dates=market['datetime'].to_list()
        # 500 original shares at 10 -> 500 originals + 500 pending at 5: unchanged equity.
        market=market.with_columns(pl.when(pl.col('datetime')>=dates[2]).then(5.).otherwise(10.).alias('open'),
            pl.when(pl.col('datetime')>=dates[2]).then(5.).otherwise(10.).alias('close'),pl.lit(11.).alias('high'),pl.lit(4.).alias('low'))
        action={**cfg.corporate_actions[0],'cash_per_share':0.,'stock_per_share':1.,'list_at':dates[3].replace(hour=9,minute=30),'fractional_policy':'reject'}
        return market,targets,rules,replace(cfg,corporate_actions=[action])

    @requires_vnpy
    def test_pending_valuation_no_early_sale_native_and_restart(self):
        from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
        from quantlab.adapters.vnpy import compare_backends
        market,targets,rules,cfg=self.account()
        ref=OpenExecutionBacktester(cfg,rules).run(targets,market)
        curve,fills,rejects,summary=ref
        self.assertEqual(curve['equity'].to_list(),[10000.]*5)
        self.assertEqual(curve['pending_stock_value'].to_list(),[0.,0.,2500.,0.,0.])
        self.assertEqual([f['quantity'] for f in fills],[500,500,500])
        self.assertIn('pending_stock_or_t_plus_one',[r['reason'] for r in rejects])
        self.assertEqual(summary['pending_stock_positions'],{})
        self.assertEqual(compare_backends(ref,VnpyRulesBacktester(cfg,rules).run(targets,market))['status'],'matched')
        with TemporaryDirectory() as directory:
            path=Path(directory)/'paper.json'
            partial=PaperAccount(path).advance(market.head(3),targets.head(3),rules,cfg,'vnpy_rules')
            self.assertEqual(partial['summary']['pending_stock_positions'],{'sh.600000':500})
            self.assertEqual(reconcile_account(path)['status'],'matched')
            final=PaperAccount(path).advance(market,targets,rules,cfg,'vnpy_rules')
            self.assertEqual(final,PaperAccount(path).advance(market,targets,rules,cfg,'vnpy_rules'))
            self.assertEqual(reconcile_account(path)['status'],'matched')

    def test_no_duplicate_purchase_and_cash_payment_before_listing(self):
        market,targets,rules,cfg=self.account()
        targets=targets.with_columns(pl.lit(.5).alias('weight'))
        ref=OpenExecutionBacktester(cfg,rules).run(targets,market)
        self.assertEqual([f['side'] for f in ref[1]],['buy'])
        self.assertEqual(ref[3]['ending_positions'],{'sh.600000':1000})
        action={**cfg.corporate_actions[0],'cash_per_share':1.,'pay_at':market['datetime'][2]}
        result=OpenExecutionBacktester(replace(cfg,corporate_actions=[action]),rules).run(targets,market)
        ledger=result[3]['corporate_action_ledger']
        self.assertEqual(sum(e['cash_delta'] for e in ledger),500.)
        self.assertEqual(sum(e.get('position_delta',0) for e in ledger),500)

    def test_fractional_policy_and_late_source(self):
        market,targets,rules,cfg=self.account()
        action={**cfg.corporate_actions[0],'stock_per_share':.001}
        with self.assertRaisesRegex(ValueError,'Fractional'):OpenExecutionBacktester(replace(cfg,corporate_actions=[action]),rules).run(targets,market)
        action['fractional_policy']='floor'
        result=OpenExecutionBacktester(replace(cfg,corporate_actions=[action]),rules).run(targets,market)
        self.assertEqual(next(e for e in result[3]['corporate_action_ledger'] if e['kind']=='stock_accrual')['fractional_discarded'],.5)
        action['available_at']=market['datetime'][-1]
        with self.assertRaisesRegex(ValueError,'availability'):OpenExecutionBacktester(replace(cfg,corporate_actions=[action]),rules).run(targets,market)
