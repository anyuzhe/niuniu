import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from copy import deepcopy
import polars as pl
import test_stock_distributions
from quantlab.execution.backtest import OpenExecutionBacktester
from quantlab.execution.corporate_actions import RightsIssues
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account

class RightsIssueTests(unittest.TestCase):
    def fixture(self):
        bars,targets,rules,cfg=test_stock_distributions.StockDistributionTests().account()
        dates=bars['datetime'].to_list()
        # 500 old shares at 10 + 500 subscribed at 2 -> 1000 shares at 6.
        bars=bars.with_columns(*[pl.when(pl.col('datetime')>=dates[3]).then(6.).otherwise(10.).alias(c) for c in ('open','close')],pl.lit(11.).alias('high'),pl.lit(1.).alias('low'))
        targets=targets.with_columns(pl.Series('weight',[.5,.5,.5,0.,0.]))
        issue={'action_id':'rights-1','symbol':'sh.600000','record_at':dates[1],'subscribe_at':dates[2].replace(hour=9,minute=30),
            'ex_at':dates[3].replace(hour=9,minute=30),'list_at':dates[4].replace(hour=9,minute=30),'available_at':dates[0],
            'numerator':1,'denominator':1,'subscription_price':2.,'subscription_shares':500,'insufficient_cash':'error','fractional_policy':'reject','source':'synthetic explicit instruction'}
        return bars,targets,rules,replace(cfg,corporate_actions=None,rights_issues=[issue])

    def test_paid_pending_listed_native_and_paper_reconciliation(self):
        from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
        from quantlab.adapters.vnpy import compare_backends
        bars,targets,rules,cfg=self.fixture();ref=OpenExecutionBacktester(cfg,rules).run(targets,bars)
        self.assertEqual(ref[0]['equity'].to_list(),[10000.]*5)
        self.assertEqual(ref[0]['subscription_receivable'].to_list(),[0.,0.,1000.,0.,0.])
        self.assertEqual(ref[0]['pending_stock_value'].to_list(),[0.,0.,0.,3000.,0.])
        self.assertEqual([e['kind'] for e in ref[3]['rights_ledger']],['rights_subscription','rights_ex','rights_listing'])
        self.assertEqual(compare_backends(ref,VnpyRulesBacktester(cfg,rules).run(targets,bars))['status'],'matched')
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'account.json';account=PaperAccount(path)
            for n in (3,4,5):
                state=account.advance(bars.head(n),targets.head(n),rules,cfg,'vnpy_rules')
                self.assertEqual(reconcile_account(path)['status'],'matched')
            self.assertEqual(state,account.advance(bars,targets,rules,cfg,'vnpy_rules'))
            altered=deepcopy(state);altered['summary']['rights_ledger'][0]['cash_delta']+=1
            with patch('quantlab.execution.reconcile.PaperAccount.read',return_value=altered):
                self.assertIn('rights_ledger_mismatch',[e.get('reason') for e in reconcile_account(path)['errors']])

    def test_explicit_decline_cash_skip_and_error(self):
        bars,targets,rules,cfg=self.fixture();issue=cfg.rights_issues[0]
        for shares,price,policy,status in [(0,2.,'error','declined'),(500,100.,'skip','insufficient_cash')]:
            c=replace(cfg,rights_issues=[{**issue,'subscription_shares':shares,'subscription_price':price,'insufficient_cash':policy}])
            result=OpenExecutionBacktester(c,rules).run(targets,bars)
            self.assertEqual(result[3]['rights_ledger'][0]['status'],status)
            self.assertEqual(result[3]['rights_ledger'][0]['cash_delta'],0.)
            with TemporaryDirectory() as tmp:
                path=Path(tmp)/'paper.json';PaperAccount(path).advance(bars,targets,rules,c,'open')
                self.assertEqual(reconcile_account(path)['status'],'matched')
        with self.assertRaisesRegex(ValueError,'Insufficient cash'):
            OpenExecutionBacktester(replace(cfg,rights_issues=[{**issue,'subscription_price':100.}]),rules).run(targets,bars)

    def test_invalid_entitlement_timing_and_overlap(self):
        from quantlab.adapters.vnpy import validate_config
        bars,targets,rules,cfg=self.fixture();r=cfg.rights_issues[0]
        for change,message in [({'subscription_shares':501},'exceeds'),({'available_at':bars['datetime'][-1]},'availability'),({'denominator':3},'Fractional')]:
            with self.assertRaisesRegex(ValueError,message):OpenExecutionBacktester(replace(cfg,rights_issues=[{**r,**change}]),rules).run(targets,bars)
        with self.assertRaisesRegex(ValueError,'rights subscriptions'):validate_config(cfg)
        for changes in ({'numerator':True},{'subscription_shares':-1},{'insufficient_cash':'borrow'}):
            with self.assertRaises(ValueError):RightsIssues([{**r,**changes}])
        _,_,_,divcfg=test_stock_distributions.StockDistributionTests().account()
        with self.assertRaisesRegex(ValueError,'overlapping'):replace(divcfg,rights_issues=[r])

    def test_close_dividend_cash_cannot_pay_open_subscription(self):
        bars,targets,original_rules,cfg=self.fixture();dates=bars['datetime'].to_list()
        other=bars.with_columns(pl.lit('sz.000001').alias('symbol'),*[pl.when(pl.col('datetime')>=dates[2]).then(5.).otherwise(10.).alias(c) for c in ('open','close')])
        market=pl.concat([bars,other]).sort('datetime','symbol')
        other_targets=targets.with_columns(pl.lit('sz.000001').alias('symbol'),pl.lit(.4).alias('weight'))
        targets=pl.concat([targets.with_columns(pl.lit(.5).alias('weight')),other_targets]).sort('datetime','symbol')
        dividend={'action_id':'other-cash','symbol':'sz.000001','record_at':dates[1],'ex_at':dates[2].replace(hour=9,minute=30),'pay_at':dates[2],'available_at':dates[0],'cash_per_share':5.,'tax_rate':0.,'source':'synthetic close payment'}
        issue={**cfg.rights_issues[0],'subscription_price':4.,'insufficient_cash':'skip'}
        cfg=replace(cfg,rights_issues=[issue],corporate_actions=[dividend],max_actual_exposure=1)
        from quantlab.execution.rules import MarketRules
        rules=MarketRules([{**r,'symbol':symbol,'limit_up':None,'limit_down':None} for symbol in ('sh.600000','sz.000001') for r in original_rules.records])
        result=OpenExecutionBacktester(cfg,rules).run(targets,market)
        self.assertEqual(result[3]['rights_ledger'][0]['status'],'insufficient_cash')
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'account.json';PaperAccount(path).advance(market,targets,rules,cfg,'open')
            self.assertEqual(reconcile_account(path)['status'],'matched')
