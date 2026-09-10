"""Explicit corporate-action lifecycle contracts, using synthetic account inputs."""
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import polars as pl
import test_rights_issues
import test_stock_splits
import test_stock_distributions
from quantlab.execution.backtest import OpenExecutionBacktester
from quantlab.execution.corporate_actions import CashDividends,StockSplits,RightsIssues
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account
from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
from quantlab.adapters.vnpy import compare_backends


class CorporateActionLifecycleTests(unittest.TestCase):
    def check_account(self,bars,targets,rules,cfg):
        result=OpenExecutionBacktester(cfg,rules).run(targets,bars)
        self.assertEqual(compare_backends(result,VnpyRulesBacktester(cfg,rules).run(targets,bars))['status'],'matched')
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'account.json';account=PaperAccount(path)
            for n in range(2,len(bars)+1):
                state=account.advance(bars.head(n),targets.head(n),rules,cfg,'vnpy_rules')
                check=reconcile_account(path);self.assertEqual(check['status'],'matched',check['errors'])
            self.assertEqual(state,account.advance(bars,targets,rules,cfg,'vnpy_rules'))
            altered=deepcopy(state)
            ledger=next((altered['summary'][k] for k in ('rights_ledger','split_ledger','corporate_action_ledger') if altered['summary'].get(k)),None)
            if ledger:
                ledger[0]['cash_delta']+=1
                with patch('quantlab.execution.reconcile.PaperAccount.read',return_value=altered):self.assertEqual(reconcile_account(path)['status'],'different')
        return result

    def cancellation_fixture(self,when):
        bars,targets,rules,cfg=test_rights_issues.RightsIssueTests().fixture();dates=bars['datetime'].to_list();r=cfg.rights_issues[0]
        # Extend the explicit listing date, allowing cancellation after ex-date.
        r={**r,'list_at':dates[4].replace(hour=10),'subscription_fee':12.50,
            'cancellation':{'cancel_at':dates[when].replace(hour=9,minute=30),'refund_at':dates[4].replace(hour=9,minute=30),
                'available_at':dates[when].replace(hour=9),'fee_refund':2.50,'source':'synthetic cancellation notice'}}
        # A cancelled issue has no ex-price adjustment after cancellation.
        bars=bars.with_columns(*[pl.lit(10.).alias(c) for c in ('open','close')])
        targets=targets.with_columns(pl.Series('weight',[.5,0.,0.,0.,0.]))
        return bars,targets,rules,replace(cfg,rights_issues=[r])

    def test_cancellation_before_on_and_after_ex_refund_and_fees(self):
        for when in (2,3,4):
            with self.subTest(cancel_day=when):
                bars,targets,rules,cfg=self.cancellation_fixture(when)
                result=self.check_account(bars,targets,rules,cfg);ledger=result[3]['rights_ledger']
                self.assertEqual(ledger[0]['cost'],1000.);self.assertEqual(ledger[0]['fee'],12.50)
                self.assertEqual(ledger[-1]['cash_delta'],1002.50)
                self.assertNotIn('rights_listing',[r['kind'] for r in ledger])
                self.assertEqual(result[0]['equity'][-1],9990.)
                if when<4:
                    self.assertEqual(result[0]['subscription_receivable'][when],1002.50)
                    self.assertEqual(result[0]['pending_stock_value'][when],0.)
                if when==4:self.assertIn('rights_ex',[r['kind'] for r in ledger])

    def test_fee_affordability_decline_and_no_future_cancellation(self):
        bars,targets,rules,cfg=self.cancellation_fixture(4);r=cfg.rights_issues[0]
        costly={**r,'subscription_fee':5000.,'insufficient_cash':'skip'}
        result=self.check_account(bars,targets,rules,replace(cfg,rights_issues=[costly]))
        self.assertEqual(result[3]['rights_ledger'][0]['status'],'insufficient_cash')
        self.assertEqual(result[3]['rights_ledger'][-1]['cash_delta'],0.)
        self.assertEqual(result[0]['equity'].to_list(),[10000.]*5)
        late={**r,'cancellation':{**r['cancellation'],'available_at':bars['datetime'][-1]}}
        # A future notice must not suppress today's subscription or ex-date accrual.
        partial=OpenExecutionBacktester(replace(cfg,rights_issues=[late]),rules).run(targets.head(4),bars.head(4))
        self.assertEqual([e['kind'] for e in partial[3]['rights_ledger']],['rights_subscription','rights_ex'])
        with self.assertRaisesRegex(ValueError,'Cancellation availability'):
            OpenExecutionBacktester(replace(cfg,rights_issues=[late]),rules).run(targets,bars)
        missing={**r,'cancellation':{**r['cancellation'],'cancel_at':r['cancellation']['cancel_at']-timedelta(minutes=1)}}
        with self.assertRaisesRegex(ValueError,'cancellation-time'):
            OpenExecutionBacktester(replace(cfg,rights_issues=[missing]),rules).run(targets,bars)

    def test_floor_rights_and_explicit_overlapping_entitlements(self):
        bars,targets,rules,cfg=test_rights_issues.RightsIssueTests().fixture();r=cfg.rights_issues[0];dates=bars['datetime'].to_list()
        r={**r,'denominator':3,'fractional_policy':'floor','subscription_shares':166,'subscription_fee':1.25,'entitlement_quantity':500}
        dividend={'action_id':'overlap','symbol':r['symbol'],'record_at':dates[2],'ex_at':dates[3].replace(hour=9,minute=30),
            'pay_at':dates[4].replace(hour=9,minute=30),'available_at':dates[0],'cash_per_share':.10,'tax_rate':.1,
            'entitlement_quantity':600,'source':'synthetic registrar allocation including named rights'}
        result=self.check_account(bars,targets,rules,replace(cfg,rights_issues=[r],corporate_actions=[dividend]))
        self.assertEqual(result[3]['rights_ledger'][0]['entitled_shares'],166)
        self.assertAlmostEqual(result[3]['rights_ledger'][0]['fractional_discarded'],2/3)
        self.assertEqual(result[3]['corporate_action_ledger'][0]['quantity'],600)
        self.assertEqual(result[3]['dividend_cash'],54.)
        with self.assertRaisesRegex(ValueError,'overlapping'):
            replace(cfg,rights_issues=[r],corporate_actions=[{k:v for k,v in dividend.items() if k!='entitlement_quantity'}])

    def test_fractional_split_cash_tax_fee_and_lot_allocation(self):
        bars,targets,rules,cfg=test_stock_splits.StockSplitTests().fixture(1,3);r=cfg.stock_splits[0]
        r={**r,'fractional_policy':'floor','fractional_settlement':{'price':30.,'tax_rate':.1,'fee':1.}}
        result=self.check_account(bars,targets,rules,replace(cfg,stock_splits=[r]))
        entry=result[3]['split_ledger'][0]
        self.assertEqual(entry['after_quantity'],166);self.assertEqual(entry['fractional_gross'],20.)
        self.assertEqual(entry['fractional_tax'],2.);self.assertEqual(entry['cash_delta'],17.)
        self.assertEqual(result[0]['equity'][-1],9997.)
        # Allocation is per acquisition lot, not flooring the aggregate holding.
        day=r['effective_at'].date();lots={r['symbol']:[[day-timedelta(days=1),100],[day,200]]}
        engine=StockSplits([r]);delta=engine.advance(r['effective_at'],bars['datetime'][2],lots,{r['symbol']:30.},{},{},CashDividends())
        self.assertEqual(lots[r['symbol']],[[day-timedelta(days=1),33],[day,66]])
        self.assertEqual(delta,26.)

    def test_fractional_distribution_cash_uses_declared_payment_time(self):
        bars,targets,rules,cfg=test_stock_distributions.StockDistributionTests().account();r=cfg.corporate_actions[0]
        r={**r,'stock_per_share':.001,'fractional_policy':'floor','fractional_settlement':{'price':10.,'tax_rate':.1,'fee':.50}}
        result=self.check_account(bars,targets,rules,replace(cfg,corporate_actions=[r]))
        ledger=result[3]['corporate_action_ledger']
        self.assertEqual(ledger[0]['fractional_gross'],5.)
        self.assertEqual(ledger[0]['fractional_tax'],.50)
        self.assertEqual(ledger[0]['net'],4.)
        self.assertEqual(result[0]['dividend_receivable'][2],4.)
        self.assertEqual(result[3]['dividend_cash'],4.)
        invalid={**r,'fractional_settlement':{**r['fractional_settlement'],'fee':10.}}
        with self.assertRaisesRegex(ValueError,'exceeds proceeds'):
            OpenExecutionBacktester(replace(cfg,corporate_actions=[invalid]),rules).run(targets,bars)

    def test_invalid_explicit_terms(self):
        _,_,_,cfg=self.cancellation_fixture(3);r=cfg.rights_issues[0]
        for change in ({'subscription_fee':True},{'subscription_fee':.001},{'entitlement_quantity':-1},
            {'cancellation':{**r['cancellation'],'fee_refund':13.}},
            {'cancellation':{**r['cancellation'],'cancel_at':r['list_at']}},
            {'cancellation':{**r['cancellation'],'refund_at':r['record_at']}}):
            with self.subTest(change=change),self.assertRaises(ValueError):RightsIssues([{**r,**change}])

    def test_historical_fee_revision_and_independent_fee_tamper_detection(self):
        from quantlab.execution.rules import MarketRules
        bars,targets,rules,cfg=test_stock_splits.StockSplitTests().fixture()
        cfg=replace(cfg,stock_splits=None,fee_decimals=2)
        bars=bars.with_columns(pl.lit(10.).alias('open'),pl.lit(10.).alias('close'))
        dates=bars['datetime'].to_list();base=rules.records[0]
        early={**base,'expires_at':dates[-1]+timedelta(days=2),'limit_up':None,'limit_down':None,'commission_bps':1.,'minimum_commission':1.,'transfer_bps':.1,'sell_tax_bps':5.}
        late={**early,'effective_at':dates[2],'available_at':dates[2],'commission_bps':10.,'sell_tax_bps':8.,'source':'synthetic dated fee revision'}
        future={**late,'available_at':dates[-1]+timedelta(days=1),'commission_bps':1000.,'source':'future revision must not apply'}
        rules=MarketRules([early,late,future])
        result=self.check_account(bars,targets,rules,cfg)
        self.assertEqual(result[1][0]['commission'],1.)
        self.assertGreater(result[1][-1]['commission'],1.)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'account.json';state=PaperAccount(path).advance(bars,targets,rules,cfg)
            altered=deepcopy(state);altered['fills'][0]['commission']+=1.
            with patch('quantlab.execution.reconcile.PaperAccount.read',return_value=altered):
                self.assertIn('fill_fee_mismatch',[e.get('reason') for e in reconcile_account(path)['errors']])
