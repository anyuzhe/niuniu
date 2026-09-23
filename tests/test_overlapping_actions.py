"""Explicit account entitlements, not assumptions about exchange allocation rules."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import polars as pl
import test_stock_distributions
from quantlab.execution.corporate_actions import CashDividends
from quantlab.execution.backtest import OpenExecutionBacktester
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account
from _optional import requires_vnpy


def overlapping_fixture(include=True, stock=True):
    market,targets,rules,cfg=test_stock_distributions.StockDistributionTests().account()
    dates=market['datetime'].to_list()
    first={**cfg.corporate_actions[0],'list_at':dates[4].replace(hour=9,minute=30)}
    second={**first,'action_id':'second','record_at':dates[2],
        'ex_at':dates[3].replace(hour=9,minute=30),'pay_at':dates[4],
        'entitled_pending_actions':[first['action_id']] if include else [],
        'source':'synthetic explicit overlapping entitlement fixture'}
    if not stock:
        for key in ('stock_per_share','list_at','fractional_policy'):second.pop(key)
        second['cash_per_share']=1.
    price=(2.5 if include else 10/3) if stock else (4. if include else 4.5)
    market=market.with_columns(*[pl.when(pl.col('datetime')>=dates[3]).then(price).otherwise(pl.col(c)).alias(c) for c in ('open','close')],pl.lit(1.).alias('low'))
    targets=targets.with_columns(pl.Series('weight',[.5,.5,0.,0.,0.]))
    return market,targets,rules,replace(cfg,corporate_actions=[first,second])


class OverlappingActionTests(unittest.TestCase):
    @requires_vnpy
    def test_stock_entitlement_native_restart_and_no_early_sale(self):
        from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
        from quantlab.adapters.vnpy import compare_backends
        market,targets,rules,cfg=overlapping_fixture()
        result=OpenExecutionBacktester(cfg,rules).run(targets,market)
        self.assertEqual(result[0]['equity'].to_list(),[10000.]*5)
        self.assertEqual([f['quantity'] for f in result[1]],[500,500,1500])
        self.assertEqual(result[0]['pending_stock_value'].to_list(),[0.,0.,2500.,3750.,0.])
        entry=next(r for r in result[3]['corporate_action_ledger'] if r['action_id']=='second')
        self.assertEqual(entry['quantity'],1000)
        self.assertEqual(entry['entitlement_basis']['included_pending_shares'],500)
        self.assertEqual(compare_backends(result,VnpyRulesBacktester(cfg,rules).run(targets,market))['status'],'matched')
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'account.json';account=PaperAccount(path)
            account.advance(market.head(4),targets.head(4),rules,cfg,'vnpy_rules')
            self.assertEqual(reconcile_account(path)['status'],'matched')
            final=account.advance(market,targets,rules,cfg,'vnpy_rules')
            self.assertEqual(final,account.advance(market,targets,rules,cfg,'vnpy_rules'))
            check=reconcile_account(path)
            self.assertEqual(check['status'],'matched')
            self.assertEqual(check['checked_overlap_entitlements'],1)
            tampered=deepcopy(account.read())
            entry=next(r for r in tampered['summary']['corporate_action_ledger'] if r['action_id']=='second' and r['kind']=='dividend_accrual')
            entry['quantity']+=1
            with patch('quantlab.execution.reconcile.PaperAccount.read',return_value=tampered):
                self.assertIn('overlap_entitlement_mismatch',[r.get('reason') for r in reconcile_account(path)['errors']])

    def test_cash_inclusion_and_explicit_exclusion(self):
        for include,expected in [(True,1000.),(False,500.)]:
            market,targets,rules,cfg=overlapping_fixture(include,False)
            result=OpenExecutionBacktester(cfg,rules).run(targets,market)
            self.assertEqual(result[3]['dividend_cash'],expected)
            self.assertEqual(result[0]['equity'].to_list(),[10000.]*5)
            entry=next(r for r in result[3]['corporate_action_ledger'] if r['action_id']=='second')
            self.assertEqual(entry['entitlement_basis']['pending_sources'],{'cash-1':500})

    def test_unspecified_or_invalid_pending_sources_are_rejected(self):
        market,targets,rules,cfg=overlapping_fixture()
        first,second=cfg.corporate_actions
        second={k:v for k,v in second.items() if k!='entitled_pending_actions'}
        with self.assertRaisesRegex(ValueError,'Overlapping'):OpenExecutionBacktester(replace(cfg,corporate_actions=[first,second]),rules).run(targets,market)
        for ids in (['missing'],['second'],['cash-1','cash-1'],'cash-1',[1]):
            with self.assertRaises(ValueError):CashDividends([first,{**second,'entitled_pending_actions':ids}])
        other={**first,'symbol':'sz.000001'}
        with self.assertRaisesRegex(ValueError,'same symbol'):CashDividends([other,cfg.corporate_actions[1]])
        already_listed={**first,'list_at':market['datetime'][2].replace(hour=9,minute=30)}
        with self.assertRaisesRegex(ValueError,'earlier unlisted'):CashDividends([already_listed,cfg.corporate_actions[1]])
