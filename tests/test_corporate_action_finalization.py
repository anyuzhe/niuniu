import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory
from pathlib import Path
import polars as pl
import test_stock_splits,test_stock_distributions,test_rights_issues
from quantlab.execution.backtest import OpenExecutionBacktester
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account
from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
from quantlab.adapters.vnpy import compare_backends
from _optional import requires_vnpy

class CorporateActionFinalizationTests(unittest.TestCase):
    def account(self,bars,targets,rules,cfg):
        result=OpenExecutionBacktester(cfg,rules).run(targets,bars)
        self.assertEqual(compare_backends(result,VnpyRulesBacktester(cfg,rules).run(targets,bars))['status'],'matched')
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'account.json';a=PaperAccount(p)
            for cutoff in bars['datetime'].unique().sort().to_list()[1:]:
                a.advance(bars.filter(pl.col('datetime')<=cutoff),targets.filter(pl.col('datetime')<=cutoff),rules,cfg,'vnpy_rules')
                check=reconcile_account(p);self.assertEqual(check['status'],'matched',check['errors'])
        return result

    @requires_vnpy
    def test_pending_distribution_split_at_listing(self):
        bars,targets,rules,cfg=test_stock_distributions.StockDistributionTests().account();d=cfg.corporate_actions[0];dates=bars['datetime'].to_list()
        s={'action_id':'pending-split','symbol':d['symbol'],'effective_at':d['list_at'],'available_at':dates[0],
            'numerator':2,'denominator':1,'fractional_policy':'reject','convert_entitlements':[d['action_id']],'source':'synthetic same-unit pending conversion'}
        bars=bars.with_columns(*[pl.when(pl.col('datetime')>=dates[3]).then(pl.col(c)/2).otherwise(pl.col(c)).alias(c) for c in ('open','high','low','close')])
        result=self.account(bars,targets,rules,replace(cfg,stock_splits=[s]))
        self.assertEqual(result[0]['equity'].to_list(),[10000.]*5)
        self.assertEqual(result[3]['split_ledger'][0]['entitlement_conversions'][0]['after_quantity'],1000)

    @requires_vnpy
    def test_rights_conversion_before_payment_and_after_ex(self):
        for day in (2,4):
            bars,targets,rules,cfg=test_rights_issues.RightsIssueTests().fixture();d=cfg.rights_issues[0];dates=bars['datetime'].to_list()
            s={'action_id':'rights-split','symbol':d['symbol'],'effective_at':dates[day].replace(hour=9,minute=30),'available_at':dates[0],
                'numerator':2,'denominator':1,'fractional_policy':'reject','convert_entitlements':[d['action_id']],'source':'synthetic rights conversion'}
            bars=bars.with_columns(*[pl.when(pl.col('datetime')>=dates[day]).then(pl.col(c)/2).otherwise(pl.col(c)).alias(c) for c in ('open','high','low','close')])
            result=self.account(bars,targets,rules,replace(cfg,stock_splits=[s]))
            self.assertEqual(result[0]['equity'].to_list(),[10000.]*5)
            self.assertEqual(result[3]['rights_ledger'][-1]['shares'],1000)

    @requires_vnpy
    def test_independent_fractional_payment_dates(self):
        bars,targets,rules,cfg=test_stock_distributions.StockDistributionTests().account();dates=bars['datetime'].to_list()
        d={**cfg.corporate_actions[0],'stock_per_share':.001,'fractional_policy':'floor',
            'fractional_settlement':{'price':10.,'tax_rate':.1,'fee':.5,'pay_at':dates[4]}}
        result=self.account(bars,targets,rules,replace(cfg,corporate_actions=[d]))
        self.assertEqual(result[0]['dividend_receivable'].to_list(),[0.,0.,4.,4.,0.])
        self.assertEqual(result[3]['corporate_action_ledger'][-1]['kind'],'fractional_payment')
        bars,targets,rules,cfg=test_stock_splits.StockSplitTests().fixture(1,3);dates=bars['datetime'].to_list()
        s={**cfg.stock_splits[0],'fractional_policy':'floor','fractional_settlement':{'price':30.,'tax_rate':.1,'fee':1.,'pay_at':dates[4]}}
        result=self.account(bars,targets,rules,replace(cfg,stock_splits=[s]))
        self.assertEqual(result[0]['split_receivable'].to_list(),[0.,0.,17.,17.,0.])
        self.assertEqual(result[0]['equity'].to_list(),[10000.,10000.,9997.,9997.,9997.])
        self.assertEqual(result[3]['split_ledger'][-1]['kind'],'split_cash_payment')

    @requires_vnpy
    def test_oversubscription_allocation_unfilled_refund_and_cancellation(self):
        bars,targets,rules,cfg=test_rights_issues.RightsIssueTests().fixture();dates=bars['datetime'].to_list();r=cfg.rights_issues[0]
        r={**r,'subscription_shares':600,'subscription_fee':10.,'allow_oversubscription':True,
            'allocation':{'shares':300,'at':r['ex_at'],'available_at':dates[2],'refund_at':dates[4].replace(hour=9,minute=30),'fee_refund':3.,'source':'synthetic registrar allocation'}}
        result=self.account(bars,targets,rules,replace(cfg,rights_issues=[r]))
        ledger=result[3]['rights_ledger'];allocation=next(e for e in ledger if e['kind']=='rights_allocation')
        self.assertEqual(allocation['cost'],600.);self.assertEqual(allocation['refund_amount'],603.)
        self.assertEqual(ledger[-1]['shares'],300)
        self.assertEqual(result[0]['subscription_receivable'][3],603.)
        r={**r,'list_at':dates[4].replace(hour=10),'cancellation':{'cancel_at':dates[4].replace(hour=9,minute=30),'refund_at':dates[4].replace(hour=9,minute=30),
            'available_at':dates[3],'fee_refund':2.,'source':'synthetic cancellation after allocation'}}
        result=self.account(bars,targets,rules,replace(cfg,rights_issues=[r]))
        self.assertEqual(result[3]['rights_ledger'][-1]['cash_delta'],602.)
        self.assertEqual(result[3]['subscription_receivable'],0.)

    @requires_vnpy
    def test_post_listing_recovery_with_explicit_missing_share_compensation(self):
        bars,targets,rules,cfg=test_rights_issues.RightsIssueTests().fixture();dates=bars['datetime'].to_list();r=cfg.rights_issues[0]
        targets=targets.with_columns(pl.Series('weight',[.5,0.,0.,0.,0.]))
        r={**r,'list_at':r['ex_at'],'cancellation':{'cancel_at':dates[4].replace(hour=9,minute=30),'refund_at':dates[4].replace(hour=9,minute=30),
            'available_at':dates[3],'fee_refund':0.,'source':'synthetic post-listing cancellation',
            'recovery':{'shares':500,'missing_share_price':1.,'source':'explicit recovery in cash when shares sold'}}}
        result=self.account(bars,targets,rules,replace(cfg,rights_issues=[r]))
        cancellation=next(e for e in result[3]['rights_ledger'] if e['kind']=='rights_cancellation')
        self.assertEqual(cancellation['recovery_shares'],0)
        self.assertEqual(cancellation['replacement_cash'],500.)
        self.assertEqual(result[3]['rights_ledger'][-1]['cash_delta'],500.)

    @requires_vnpy
    def test_holding_tax_fifo_assessment_payment_and_split_fraction(self):
        import test_pipeline_dividends
        bars,targets,rules,cfg=test_pipeline_dividends.DividendTests().setup_account();dates=bars['datetime'].to_list()
        policy={'basis_per_share':1.,'bands':[{'months':1,'rate':.2},{'months':12,'rate':.1},{'months':None,'rate':0.}],
            'available_at':dates[0],'source':'explicit synthetic calendar-month tax schedule'}
        d={**cfg.corporate_actions[0],'holding_tax':policy}
        result=self.account(bars,targets,rules,replace(cfg,corporate_actions=[d]))
        self.assertEqual(result[0]['dividend_tax_payable'].to_list(),[0.,0.,100.,0.,0.])
        self.assertEqual(result[0]['equity'].to_list(),[10000.,10000.,9900.,9900.,9900.])
        self.assertEqual(result[3]['dividend_tax'],100.)
        targets=targets.with_columns(pl.Series('weight',[.5,.5,.5,0.,0.]))
        split={'action_id':'tax-split','symbol':d['symbol'],'effective_at':dates[3].replace(hour=9,minute=30),'available_at':dates[0],
            'numerator':1,'denominator':3,'fractional_policy':'floor','fractional_settlement':{'price':27.,'tax_rate':0.,'fee':0.},'source':'synthetic conversion preserving dividend tax basis'}
        bars=bars.with_columns(*[pl.when(pl.col('datetime')>=dates[3]).then(pl.col(c)*3).otherwise(pl.col(c)).alias(c) for c in ('open','high','low','close')])
        result=self.account(bars,targets,rules,replace(cfg,corporate_actions=[d],stock_splits=[split]))
        self.assertEqual(result[3]['dividend_tax'],100.)
        self.assertEqual(result[0]['equity'][-1],9900.)
        self.assertIn('split',[e['phase'] for e in result[3]['dividend_tax_ledger']])

    def test_calendar_month_tax_boundaries_and_partial_disposal(self):
        from datetime import datetime,date
        from zoneinfo import ZoneInfo
        from quantlab.execution.holding_tax import HoldingTax
        tz=ZoneInfo('Asia/Shanghai');at=lambda y,m,d:datetime(y,m,d,15,tzinfo=tz)
        r={'action_id':'tax','symbol':'sh.600000','record_at':at(2024,1,31),'pay_at':at(2024,2,2),
            'holding_tax':{'basis_per_share':1.,'bands':[{'months':1,'rate':.2},{'months':12,'rate':.1},{'months':None,'rate':0.}],
                'available_at':at(2024,1,1),'source':'explicit band boundary fixture'}}
        for sale,rate in [(at(2024,2,28),.2),(at(2024,2,29),.1),(at(2025,1,30),.1),(at(2025,1,31),0.)]:
            engine=HoldingTax([r]);engine.capture(r['record_at'],{r['symbol']:[[date(2024,1,31),500]]},{'tax':{'quantity':500}})
            engine.dispose(r['symbol'],[(date(2024,1,31),100)],sale,sale)
            self.assertEqual(engine.ledger[0]['tax'],100*rate)
            self.assertEqual(engine.claims['tax'][0]['quantity'],400)
            self.assertEqual(engine.settle(sale,sale,5.,'sale'),-min(100*rate,5.))
            self.assertEqual(engine.payable,max(100*rate-5.,0.))

    @requires_vnpy
    def test_quoted_rights_delivery_trading_exercise_expiry_and_conversion(self):
        from quantlab.execution.rules import MarketRules
        bars,targets,rules,cfg=test_stock_distributions.StockDistributionTests().account();dates=bars['datetime'].to_list()
        bars=bars.with_columns(pl.lit(10.).alias('open'),pl.lit(10.).alias('close'),pl.lit(11.).alias('high'),pl.lit(9.).alias('low'))
        right_bars=bars.with_columns(pl.lit('sz.000001').alias('symbol'),pl.lit(1.).alias('open'),pl.lit(1.).alias('close'),pl.lit(1.1).alias('high'),pl.lit(.9).alias('low'))
        market=pl.concat([bars,right_bars]).sort('datetime','symbol')
        targets=pl.concat([targets.with_columns(pl.lit(.5).alias('weight')),targets.with_columns(pl.lit('sz.000001').alias('symbol'),pl.lit(.05).alias('weight'))]).sort('datetime','symbol')
        rules=MarketRules([{**r,'symbol':symbol,'limit_up':None,'limit_down':None} for symbol in ('sh.600000','sz.000001') for r in rules.records])
        action={'action_id':'tradable','symbol':'sh.600000','rights_symbol':'sz.000001','record_at':dates[1],'deliver_at':dates[2].replace(hour=9,minute=30),
            'expires_at':dates[4].replace(hour=9,minute=30),'available_at':dates[0],'numerator':1,'denominator':1,'fractional_policy':'reject','source':'synthetic quoted entitlement',
            'exercise':{'at':dates[3].replace(hour=9,minute=30),'listing_at':dates[4].replace(hour=9,minute=30),'available_at':dates[0],
                'rights_quantity':200,'shares_per_right':1,'subscription_price':2.,'fee':1.,'insufficient_assets':'error','source':'explicit exercise'}}
        config=replace(cfg,corporate_actions=None,rights_trading=[action])
        result=self.account(market,targets,rules,config)
        self.assertEqual([e['kind'] for e in result[3]['rights_trading_ledger']],['tradable_rights_delivery','tradable_rights_exercise','tradable_rights_listing','tradable_rights_expiry'])
        self.assertEqual(result[3]['rights_trading_ledger'][1]['cash_delta'],-401.)
        self.assertNotIn('sz.000001',result[3]['ending_positions'])
        self.assertIn('rights_outside_trading_lifetime',[e['reason'] for e in result[2]])
        split={'action_id':'traded-underlying-split','symbol':'sh.600000','effective_at':dates[4].replace(hour=9,minute=30),'available_at':dates[0],
            'numerator':2,'denominator':1,'fractional_policy':'reject','convert_entitlements':['tradable'],'source':'explicit exercise-share conversion'}
        market=market.with_columns(*[pl.when((pl.col('symbol')=='sh.600000') & (pl.col('datetime')>=dates[4])).then(pl.col(c)/2).otherwise(pl.col(c)).alias(c) for c in ('open','high','low','close')])
        result=self.account(market,targets,rules,replace(config,stock_splits=[split]))
        self.assertEqual(result[3]['rights_trading_ledger'][2]['shares'],400)

    @requires_vnpy
    def test_zero_allocation_preserves_paid_fee_refund(self):
        bars,targets,rules,cfg=test_rights_issues.RightsIssueTests().fixture();dates=bars['datetime'].to_list();r=cfg.rights_issues[0]
        r={**r,'subscription_fee':10.,'allocation':{'shares':0,'at':r['ex_at'],'available_at':dates[0],
            'refund_at':dates[4].replace(hour=9,minute=30),'fee_refund':3.,'source':'zero allocation'},
            'list_at':dates[4].replace(hour=10),'cancellation':{'cancel_at':dates[4].replace(hour=9,minute=30),
            'refund_at':dates[4].replace(hour=9,minute=30),'available_at':dates[0],'fee_refund':7.,'source':'remaining paid fee return'}}
        result=self.account(bars,targets,rules,replace(cfg,rights_issues=[r]))
        ledger=result[3]['rights_ledger']
        self.assertEqual(next(e for e in ledger if e['kind']=='rights_allocation_refund')['cash_delta'],1003.)
        self.assertEqual(ledger[-1]['cash_delta'],7.)

    @requires_vnpy
    def test_explicit_fractional_pending_allocation_and_open_payment(self):
        bars,targets,rules,cfg=test_stock_distributions.StockDistributionTests().account();dates=bars['datetime'].to_list();d=cfg.corporate_actions[0]
        split={'action_id':'pending-floor','symbol':d['symbol'],'effective_at':dates[3].replace(hour=9,minute=30),'available_at':dates[0],
            'numerator':1,'denominator':3,'fractional_policy':'floor','convert_entitlements':[d['action_id']],
            'entitlement_allocations':{d['action_id']:{'shares':166,'cash':20.,'principal_reduction':0.}},
            'fractional_settlement':{'price':15.,'fee':0.,'tax_rate':0.,'pay_at':dates[4].replace(hour=9,minute=30)},'source':'explicit registrar fractional allocation'}
        bars=bars.with_columns(*[pl.when(pl.col('datetime')>=dates[3]).then(pl.col(c)*3).otherwise(pl.col(c)).alias(c) for c in ('open','high','low','close')])
        result=self.account(bars,targets,rules,replace(cfg,stock_splits=[split]))
        self.assertEqual(result[3]['split_ledger'][0]['entitlement_conversions'][0]['after_quantity'],166)
        self.assertEqual(result[3]['split_ledger'][-1]['kind'],'split_cash_payment')
        self.assertEqual(result[0]['split_receivable'][-1],0.)

    def test_tax_lots_cannot_silently_miss_real_disposal(self):
        from datetime import date
        from quantlab.execution.holding_tax import HoldingTax
        bars,targets,rules,cfg=test_stock_distributions.StockDistributionTests().account();d=cfg.corporate_actions[0]
        policy={'basis_per_share':1.,'bands':[{'months':None,'rate':.2}],'available_at':bars['datetime'][0],'source':'explicit batch',
            'lots':[{'acquired_at':'2000-01-01','quantity':500}]}
        engine=HoldingTax([{**d,'holding_tax':policy}])
        with self.assertRaisesRegex(ValueError,'existing position acquisition'):
            engine.capture(d['record_at'],{d['symbol']:[(d['record_at'].date(),500)]},{d['action_id']:{'quantity':500}})

    @requires_vnpy
    def test_returned_principal_then_allocation_not_refunded_twice(self):
        bars,targets,rules,cfg=test_rights_issues.RightsIssueTests().fixture();dates=bars['datetime'].to_list();r=cfg.rights_issues[0]
        r={**r,'allocation':{'shares':250,'at':r['ex_at'],'available_at':dates[0],'refund_at':dates[4].replace(hour=9,minute=30),'fee_refund':0.,'source':'half allocation after unit conversion'}}
        split={'action_id':'principal-conversion','symbol':r['symbol'],'effective_at':r['ex_at'],'available_at':dates[0],
            'numerator':2,'denominator':1,'fractional_policy':'reject','convert_entitlements':[r['action_id']],
            'entitlement_allocations':{r['action_id']:{'shares':1000,'cash':100.,'principal_reduction':100.}},'source':'explicit paid principal return'}
        bars=bars.with_columns(*[pl.when(pl.col('datetime')>=dates[3]).then(pl.col(c)/2).otherwise(pl.col(c)).alias(c) for c in ('open','high','low','close')])
        result=self.account(bars,targets,rules,replace(cfg,rights_issues=[r],stock_splits=[split]))
        allocation=next(e for e in result[3]['rights_ledger'] if e['kind']=='rights_allocation')
        self.assertEqual(allocation['cost'],450.);self.assertEqual(allocation['refund_amount'],450.);self.assertEqual(allocation['shares'],500)

    @requires_vnpy
    def test_post_listing_recovery_existing_shares_and_unfunded_debt(self):
        bars,targets,rules,cfg=test_rights_issues.RightsIssueTests().fixture();dates=bars['datetime'].to_list();r=cfg.rights_issues[0]
        r={**r,'list_at':r['ex_at'],'cancellation':{'cancel_at':dates[4].replace(hour=9,minute=30),'refund_at':dates[4].replace(hour=9,minute=30),
            'available_at':dates[0],'fee_refund':0.,'source':'explicit postlisting clawback','recovery':{'shares':500,'missing_share_price':100.,'source':'explicit cash compensation'}}}
        held=self.account(bars,targets.with_columns(pl.lit(.5).alias('weight')),rules,replace(cfg,rights_issues=[r]))
        event=next(e for e in held[3]['rights_ledger'] if e['kind']=='rights_cancellation')
        self.assertEqual(event['recovery_shares'],500);self.assertEqual(event['replacement_cash'],0.)
        sold=self.account(bars,targets.with_columns(pl.Series('weight',[.5,0.,0.,0.,0.])),rules,replace(cfg,rights_issues=[r]))
        self.assertLess(sold[3]['subscription_receivable'],0.)
        self.assertEqual(sold[0]['cash'][-1],0.)
