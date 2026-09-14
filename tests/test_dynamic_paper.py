import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.dynamic_paper import DynamicPaperAccount, DynamicPaperError
from quantlab.execution.rules import MarketRules

TZ=ZoneInfo('Asia/Shanghai')

def dt(value): return datetime.fromisoformat(value).replace(tzinfo=TZ)


def bars(day, rows):
    at=dt(day+'T15:00:00')
    return pl.DataFrame({'symbol':[r[0] for r in rows], 'datetime':[at]*len(rows), 'available_at':[at]*len(rows),
        'timeframe':['1d']*len(rows), 'open':[r[1] for r in rows], 'high':[r[2] for r in rows],
        'low':[r[3] for r in rows], 'close':[r[4] for r in rows], 'volume':[100000.0]*len(rows),
        'turnover':[1000000.0]*len(rows)})


def rule(day,symbol,up=20.0,down=5.0):
    return {'symbol':symbol,'effective_at':dt(day+'T00:00:00'),'available_at':dt(day+'T00:00:00'),
        'expires_at':dt(day+'T23:59:59'),'suspended':False,'st':False,'limit_up':up,'limit_down':down,
        'commission_bps':3.0,'minimum_commission':5.0,'sell_tax_bps':5.0,'transfer_bps':0.1,
        'source':'dynamic-paper synthetic rules'}


class DynamicPaperTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.account=DynamicPaperAccount(self.root/'paper_dynamic'/'long.json')
        self.cfg=ExecutionConfig(initial_cash=100000,top_n=10,exposure=1,price_mode='account')
    def tearDown(self): self.temp.cleanup()

    def test_dynamic_universe_addition_preserves_committed_prefix(self):
        first=self.account.advance(bars('2026-09-15',[('sh.600000',10,10.5,9.8,10.2)]),
            MarketRules([rule('2026-09-15','sh.600000')]),self.cfg,as_of=dt('2026-09-15T15:05:00'),
            target_at=dt('2026-09-14T15:10:00'),target_weights={'sh.600000':0.5},target_source_ref='plan:A')
        self.assertEqual(first['universe_symbols'],['sh.600000']);self.assertTrue(first['fills'])
        old_nav=list(first['nav']);old_fills=list(first['fills']);old_orders=list(first['orders'])
        second=self.account.advance(bars('2026-09-16',[('sh.600000',10.3,10.8,10.1,10.6),('sz.000001',20,21,19.8,20.5)]),
            MarketRules([rule('2026-09-16','sh.600000'),rule('2026-09-16','sz.000001',30,10)]),self.cfg,
            as_of=dt('2026-09-16T15:05:00'),target_at=dt('2026-09-15T15:10:00'),
            target_weights={'sh.600000':0.4,'sz.000001':0.3},target_source_ref='plan:B')
        self.assertEqual(second['universe_symbols'],['sh.600000','sz.000001'])
        self.assertEqual(second['nav'][:len(old_nav)],old_nav)
        self.assertEqual(second['fills'][:len(old_fills)],old_fills)
        self.assertEqual(second['orders'][:len(old_orders)],old_orders)
        self.assertEqual(second['target_events'][0]['weights'],{'sh.600000':0.5})
        self.assertEqual(second['target_events'][1]['weights'],{'sh.600000':0.4,'sz.000001':0.3})
        self.assertIn('sz.000001',second['summary']['ending_positions'])

    def test_repeat_delivery_is_idempotent_and_target_conflict_is_rejected(self):
        market=bars('2026-09-15',[('sh.600000',10,10.5,9.8,10.2)]);rules=MarketRules([rule('2026-09-15','sh.600000')])
        first=self.account.advance(market,rules,self.cfg,as_of=dt('2026-09-15T15:05:00'),
            target_at=dt('2026-09-14T15:10:00'),target_weights={'sh.600000':0.5},target_source_ref='plan:A')
        same=self.account.advance(market,rules,self.cfg,as_of=dt('2026-09-15T15:05:00'),
            target_at=dt('2026-09-14T15:10:00'),target_weights={'sh.600000':0.5},target_source_ref='plan:A')
        self.assertEqual(same,first)
        with self.assertRaises(DynamicPaperError) as conflict:
            self.account.advance(market,rules,self.cfg,as_of=dt('2026-09-15T15:05:00'),
                target_at=dt('2026-09-14T15:10:00'),target_weights={'sh.600000':0.4},target_source_ref='other')
        self.assertEqual(conflict.exception.code,'TARGET_CONFLICT')

    def test_cash_target_exits_positions_on_next_bar(self):
        self.account.advance(bars('2026-09-15',[('sh.600000',10,10.5,9.8,10.2)]),MarketRules([rule('2026-09-15','sh.600000')]),
            self.cfg,as_of=dt('2026-09-15T15:05:00'),target_at=dt('2026-09-14T15:10:00'),
            target_weights={'sh.600000':0.5},target_source_ref='open')
        state=self.account.advance(bars('2026-09-16',[('sh.600000',10.4,10.8,10.2,10.6)]),MarketRules([rule('2026-09-16','sh.600000')]),
            self.cfg,as_of=dt('2026-09-16T15:05:00'),target_at=dt('2026-09-15T15:10:00'),
            target_weights={},target_source_ref='exit')
        self.assertEqual(state['target_events'][-1]['weights'],{})
        self.assertEqual(state['summary']['ending_positions'],{})
        self.assertEqual([f['side'] for f in state['fills']],['buy','sell'])

    def test_late_target_and_bar_revision_are_rejected(self):
        market=bars('2026-09-15',[('sh.600000',10,10.5,9.8,10.2)]);rules=MarketRules([rule('2026-09-15','sh.600000')])
        self.account.advance(market,rules,self.cfg,as_of=dt('2026-09-15T15:05:00'),
            target_at=dt('2026-09-14T15:10:00'),target_weights={'sh.600000':0.5},target_source_ref='open')
        with self.assertRaises(DynamicPaperError) as late:
            self.account.advance(bars('2026-09-16',[('sh.600000',10.3,10.8,10.1,10.6)]),MarketRules([rule('2026-09-16','sh.600000')]),
                self.cfg,as_of=dt('2026-09-16T15:05:00'),target_at=dt('2026-09-15T14:00:00'),
                target_weights={'sh.600000':0.4},target_source_ref='late')
        self.assertEqual(late.exception.code,'LATE_TARGET')
        changed=market.with_columns(pl.lit(10.3).alias('close'),pl.lit(10.6).alias('high'))
        with self.assertRaises(DynamicPaperError) as revision:
            self.account.advance(changed,rules,self.cfg,as_of=dt('2026-09-16T15:05:00'))
        self.assertEqual(revision.exception.code,'BAR_REVISION')

    def test_changed_target_symbol_requires_completed_bar_in_delivery(self):
        self.account.advance(bars('2026-09-15',[('sh.600000',10,10.5,9.8,10.2)]),MarketRules([rule('2026-09-15','sh.600000')]),
            self.cfg,as_of=dt('2026-09-15T15:05:00'),target_at=dt('2026-09-14T15:10:00'),
            target_weights={'sh.600000':0.5},target_source_ref='open')
        only_other=bars('2026-09-16',[('sz.000001',20,21,19.8,20.5)])
        with self.assertRaises(DynamicPaperError) as error:
            self.account.advance(only_other,MarketRules([rule('2026-09-16','sz.000001',30,10)]),self.cfg,as_of=dt('2026-09-16T15:05:00'),
                target_at=dt('2026-09-15T15:10:00'),target_weights={'sh.600000':0.2},target_source_ref='reduce')
        self.assertEqual(error.exception.code,'TARGET_DELIVERY_INCOMPLETE')


    def test_rule_revision_and_identity_change_are_rejected(self):
        market=bars('2026-09-15',[('sh.600000',10,10.5,9.8,10.2)]);records=[rule('2026-09-15','sh.600000')]
        self.account.advance(market,MarketRules(records),self.cfg,as_of=dt('2026-09-15T15:05:00'),
            target_at=dt('2026-09-14T15:10:00'),target_weights={'sh.600000':0.5},target_source_ref='open')
        changed=[dict(records[0])];changed[0]['commission_bps']=4.0
        with self.assertRaises(DynamicPaperError) as rules_error:
            self.account.advance(bars('2026-09-16',[('sh.600000',10.3,10.8,10.1,10.6)]),MarketRules(changed),self.cfg,
                as_of=dt('2026-09-16T15:05:00'))
        self.assertEqual(rules_error.exception.code,'RULE_REVISION')
        other=ExecutionConfig(initial_cash=200000,top_n=10,exposure=1,price_mode='account')
        with self.assertRaises(DynamicPaperError) as identity:
            self.account.advance(bars('2026-09-16',[('sh.600000',10.3,10.8,10.1,10.6)]),MarketRules([rule('2026-09-16','sh.600000')]),other,
                as_of=dt('2026-09-16T15:05:00'))
        self.assertEqual(identity.exception.code,'ACCOUNT_IDENTITY_CHANGED')


if __name__=='__main__':unittest.main()
