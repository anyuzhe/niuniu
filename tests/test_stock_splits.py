import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from copy import deepcopy
import polars as pl
import test_stock_distributions
from quantlab.execution.backtest import OpenExecutionBacktester
from quantlab.execution.corporate_actions import StockSplits,CashDividends
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account

class StockSplitTests(unittest.TestCase):
    def fixture(self,n=2,d=1):
        bars,targets,rules,cfg=test_stock_distributions.StockDistributionTests().account()
        dates=bars['datetime'].to_list();price=10*d/n
        bars=bars.with_columns(*[pl.when(pl.col('datetime')>=dates[2]).then(price).otherwise(10.).alias(c) for c in ('open','close')],pl.lit(max(11.,price+1)).alias('high'),pl.lit(min(1.,price/2)).alias('low'))
        targets=targets.with_columns(pl.Series('weight',[.5,.5,0.,0.,0.]))
        split={'action_id':'split-1','symbol':'sh.600000','effective_at':dates[2].replace(hour=9,minute=30),'available_at':dates[0],
            'numerator':n,'denominator':d,'fractional_policy':'reject','source':'synthetic ratio and prices; not official action'}
        return bars,targets,rules,replace(cfg,corporate_actions=None,stock_splits=[split])

    def test_split_and_reverse_split_native_restore_and_independent_audit(self):
        from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
        from quantlab.adapters.vnpy import compare_backends
        for n,d in ((2,1),(1,2)):
            bars,targets,rules,cfg=self.fixture(n,d)
            expected=OpenExecutionBacktester(cfg,rules).run(targets,bars)
            self.assertEqual(expected[0]['equity'].to_list(),[10000.]*5)
            self.assertEqual(expected[3]['split_ledger'][0]['after_quantity'],500*n//d)
            self.assertEqual(compare_backends(expected,VnpyRulesBacktester(cfg,rules).run(targets,bars))['status'],'matched')
            with TemporaryDirectory() as tmp:
                path=Path(tmp)/'account.json';account=PaperAccount(path)
                account.advance(bars.head(2),targets.head(2),rules,cfg,'vnpy_rules')
                account.advance(bars,targets,rules,cfg,'vnpy_rules')
                check=reconcile_account(path);self.assertEqual(check['status'],'matched');self.assertEqual(check['checked_stock_splits'],1)
                state=account.read();self.assertEqual(state,account.advance(bars,targets,rules,cfg,'vnpy_rules'))
                altered=deepcopy(state);altered['summary']['split_ledger'][0]['after_quantity']+=1
                with patch('quantlab.execution.reconcile.PaperAccount.read',return_value=altered):
                    self.assertIn('split_conversion_mismatch',[e.get('reason') for e in reconcile_account(path)['errors']])

    def test_lot_dates_fractional_availability_and_overlap(self):
        bars,targets,rules,cfg=self.fixture();r=cfg.stock_splits[0];at=r['effective_at'];day=at.date()
        lots={r['symbol']:[[day-timedelta(days=1),100],[day,100]]}
        split=StockSplits([r]);split.advance(at,bars['datetime'][2],lots,{r['symbol']:5.},{},{},CashDividends())
        self.assertEqual(lots[r['symbol']],[[day-timedelta(days=1),200],[day,200]])
        bars,targets,rules,cfg=self.fixture(1,3)
        with self.assertRaisesRegex(ValueError,'Fractional'):OpenExecutionBacktester(cfg,rules).run(targets,bars)
        with self.assertRaisesRegex(ValueError,'availability'):
            OpenExecutionBacktester(replace(cfg,stock_splits=[{**cfg.stock_splits[0],'available_at':bars['datetime'][-1]}]),rules).run(targets,bars)
        market,targets,rules,divcfg=test_stock_distributions.StockDistributionTests().account()
        with self.assertRaisesRegex(ValueError,'overlapping'):
            OpenExecutionBacktester(replace(divcfg,stock_splits=[r]),rules).run(targets,market)

    def test_invalid_ratio_and_missing_exact_bar(self):
        bars,targets,rules,cfg=self.fixture();r=cfg.stock_splits[0]
        for changes in ({'numerator':True},{'denominator':0},{'fractional_policy':'floor'}):
            with self.assertRaises(ValueError):StockSplits([{**r,**changes}])
        with self.assertRaisesRegex(ValueError,'effective-time'):
            OpenExecutionBacktester(replace(cfg,stock_splits=[{**r,'effective_at':r['effective_at']-timedelta(minutes=1)}]),rules).run(targets,bars)

    def test_old_native_backend_rejects_split_and_unheld_symbol_audit(self):
        from quantlab.adapters.vnpy import validate_config
        bars,targets,rules,cfg=self.fixture()
        with self.assertRaisesRegex(ValueError,'stock splits'):validate_config(cfg)
        split={**cfg.stock_splits[0],'symbol':'sz.000001'}
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'account.json';PaperAccount(path).advance(bars,targets,rules,replace(cfg,stock_splits=[split]),'open')
            self.assertEqual(reconcile_account(path)['status'],'matched')

    def test_lagged_volume_uses_post_split_share_units(self):
        bars,targets,rules,cfg=self.fixture()
        targets=targets.with_columns(pl.lit(.5).alias('weight'))
        cfg=replace(cfg,max_volume_participation=.1)
        bars=bars.with_columns(pl.lit(1000.).alias('volume'))
        # Day 2 buys 100 old shares; day 3 can buy 200 new shares after 2:1 split.
        result=OpenExecutionBacktester(cfg,rules).run(targets,bars)
        self.assertEqual(result[1][0]['quantity'],100)
        self.assertEqual(result[1][1]['quantity'],200)
