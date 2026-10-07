"""我的持仓与明天的操作清单：代码规范化、持仓存取、到期判断、扣掉已持有后的买入计划、资金上限、数据过期。全部用合成数据。"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

from quantlab.dipbuy import portfolio
from quantlab.dipbuy.fusion import FusionConfig
from test_dipbuy_fusion import scripted

ND, NC = 330, 30


def fixture(cols_a=range(10), gate_last=True):
    last = ND - 1
    panel, inp = scripted(nd=ND, nc=NC, gates={'A': [last]} if gate_last else {}, pools={'A': ([last], list(cols_a))} if gate_last else {})
    return panel, inp


def day(panel, back):
    return str(panel.dates[len(panel.dates) - 1 - back])


class CodeTests(unittest.TestCase):
    def test_codes_are_normalised(self):
        for text in ('600000', 'sh600000', 'SH.600000', '600000.SH', ' sh.600000 '):
            self.assertEqual(portfolio.normalize_code(text), 'sh.600000')
        self.assertEqual(portfolio.normalize_code('000001'), 'sz.000001')
        self.assertEqual(portfolio.normalize_code('300750'), 'sz.300750')
        self.assertEqual(portfolio.normalize_code('688981'), 'sh.688981')
        for bad in ('', '60000', 'abc', '1234567', '500000x'):
            with self.assertRaises(ValueError):
                portfolio.normalize_code(bad)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_remove_roundtrip_and_validation(self):
        self.assertEqual(portfolio.load(self.out)['holdings'], [])
        h = portfolio.add_holding(self.out, code='600001', shares=1000, entry_date='2024-05-06', cost=9.5, sleeve='C')
        self.assertEqual(h['code'], 'sh.600001')
        again = portfolio.load(self.out)['holdings']
        self.assertEqual([(x['code'], x['shares'], x['sleeve'], x['cost']) for x in again], [('sh.600001', 1000, 'C', 9.5)])
        for kw in (dict(code='600001', shares=100, entry_date='2024-05-06'),             # 重复
                   dict(code='600002', shares=0, entry_date='2024-05-06'),
                   dict(code='600002', shares=100.5, entry_date='2024-05-06'),
                   dict(code='600002', shares=100, entry_date='5月6日'),
                   dict(code='600002', shares=100, entry_date='2024-05-06', cost=-1),
                   dict(code='600002', shares=100, entry_date='2024-05-06', sleeve='X')):
            with self.assertRaises(ValueError):
                portfolio.add_holding(self.out, **kw)
        self.assertTrue(portfolio.remove_holding(self.out, h['id']))
        self.assertFalse(portfolio.remove_holding(self.out, h['id']))
        self.assertEqual(portfolio.load(self.out)['holdings'], [])

    def test_equity_is_saved_and_garbage_files_are_ignored(self):
        portfolio.set_equity(self.out, 55.5)
        self.assertEqual(portfolio.load(self.out)['equity_wan'], 55.5)
        with self.assertRaises(ValueError):
            portfolio.set_equity(self.out, 0)
        (self.out / '_home' / 'dip_holdings.json').write_text('not json', encoding='utf-8')
        self.assertEqual(portfolio.load(self.out)['holdings'], [])


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.panel, self.inp = fixture()
        self.cfg = FusionConfig(positions=5)

    def plan(self, holdings=(), equity=1_000_000, **kw):
        return portfolio.plan_operations(self.panel, self.inp, self.cfg, list(holdings), equity=equity, **kw)

    def hold(self, col, back, sleeve='A', shares=1000, cost=None):
        return dict(id=f'h{col}', code=f'sh.60000{col}', shares=shares, entry_date=day(self.panel, back), cost=cost, sleeve=sleeve)

    def test_empty_account_gets_the_top_ranked_candidates_with_sized_orders(self):
        p = self.plan()
        self.assertTrue(p['gate_open'])
        self.assertEqual(p['fired'], ['A'])
        self.assertEqual([b['code'] for b in p['buys']], [f'sh.60000{i}' for i in range(5)])
        self.assertEqual([b['rank'] for b in p['buys']], [1, 2, 3, 4, 5])
        self.assertTrue(all(b['shares'] == 8000 and abs(b['amount'] - 80000) < 1e-6 for b in p['buys']))     # 8% × 100 万 ÷ 10 元
        self.assertEqual(len(p['spares']), 5)
        self.assertEqual(p['plan_day'], portfolio.autorecord.next_open_day(p['data_date']).isoformat())
        self.assertEqual(p['sells'], [])

    def test_already_held_names_are_skipped_and_use_up_slots(self):
        p = self.plan([self.hold(0, back=3), self.hold(1, back=3)])
        self.assertEqual([b['code'] for b in p['buys']], ['sh.600002', 'sh.600003', 'sh.600004'])           # 5 个名额 − 2 只已持有
        self.assertEqual(p['sleeves']['A']['held'], 2)
        self.assertEqual(p['sleeves']['A']['slots'], 3)
        self.assertTrue(all(r['status'] == 'hold' for r in p['holdings']))
        self.assertEqual(p['holdings'][0]['sell_in'], self.cfg.hold_days - 4)

    def test_due_and_overdue_follow_the_backtest_calendar(self):
        h_ = self.cfg.hold_days
        due = self.hold(2, back=h_ - 2)          # 数据最后一天是第 H−1 个持有日 → 明天收盘卖
        over = self.hold(3, back=h_ - 1)         # 第 H 个持有日 → 已到期，明天开盘卖
        late = self.hold(4, back=h_ + 3)
        p = self.plan([due, over, late])
        by = {r['code']: r for r in p['holdings']}
        self.assertEqual((by['sh.600002']['status'], by['sh.600002']['days_held'], by['sh.600002']['sell_in']), ('due', h_ - 1, 1))
        self.assertEqual((by['sh.600003']['status'], by['sh.600003']['days_held']), ('overdue', h_))
        self.assertEqual(by['sh.600004']['status'], 'overdue')
        self.assertIn('已过期 4 天', by['sh.600004']['advice'])
        self.assertEqual({r['code'] for r in p['sells']}, {'sh.600002', 'sh.600003', 'sh.600004'})
        # 已到期的当作已经卖掉：名额和“不重复买”都放开，所以 600003 / 600004 又能被买；明天才卖的 600002 还占着名额
        bought = [b['code'] for b in p['buys']]
        self.assertNotIn('sh.600002', bought)
        self.assertIn('sh.600003', bought)
        self.assertEqual(p['sleeves']['A']['held'], 1)

    def test_holding_bought_after_the_last_data_day_is_pending(self):
        h = dict(id='x', code='sh.600001', shares=500, entry_date=(date.fromisoformat(day(self.panel, 0)) + timedelta(days=1)).isoformat(),
                 cost=10.0, sleeve='A')
        p = self.plan([h])
        self.assertEqual(p['holdings'][0]['status'], 'pending')
        self.assertIsNone(p['holdings'][0]['sell_in'])
        self.assertNotIn('sh.600001', [b['code'] for b in p['buys']])        # 已经买了就不重复买

    def test_unknown_code_is_flagged_not_crashing(self):
        h = dict(id='x', code='sz.000001', shares=500, entry_date=day(self.panel, 5), cost=10.0, sleeve='')
        p = self.plan([h])
        self.assertEqual(p['holdings'][0]['status'], 'unknown')
        self.assertTrue(any('不在面板' in n for n in p['notes']))
        self.assertTrue(any('没有标注' in n for n in p['notes']))

    def test_gross_cap_limits_new_money_after_existing_positions(self):
        # 账户 10 万，已持有 9.5 万市值（19 只 × 500 股 × 10 元以外，用一只大仓位）
        big = self.hold(9, back=2, shares=9500, sleeve='C')
        p = self.plan([big], equity=100_000)
        self.assertEqual(p['buys'][0]['shares'], 500)                          # 剩 5000 元，只够 500 股
        self.assertAlmostEqual(sum(b['amount'] for b in p['buys']), 5000, places=6)
        self.assertEqual(len(p['buys']), 1)

    def test_a_plan_that_cannot_afford_one_lot_says_so(self):
        p = self.plan(equity=10_000)                                          # 8% = 800 元 < 一手 1000 元
        self.assertEqual(p['buys'], [])
        self.assertTrue(any('买不起一手' in n for n in p['notes']))

    def test_stale_data_gives_no_buy_plan(self):
        plan_day = portfolio.autorecord.next_open_day(day(self.panel, 0))
        p = self.plan(today=plan_day + timedelta(days=1))
        self.assertTrue(p['stale'])
        self.assertEqual(p['buys'], [])
        self.assertTrue(any('先更新数据' in n for n in p['notes']))
        fresh = self.plan(today=plan_day)
        self.assertFalse(fresh['stale'])
        self.assertEqual(len(fresh['buys']), 5)

    def test_no_gate_no_buys_but_sells_still_listed(self):
        panel, inp = fixture(gate_last=False)
        h = self.hold(1, back=self.cfg.hold_days)
        p = portfolio.plan_operations(panel, inp, self.cfg, [h], equity=1_000_000)
        self.assertFalse(p['gate_open'])
        self.assertEqual(p['buys'], [])
        self.assertEqual([r['code'] for r in p['sells']], ['sh.600001'])

    def test_near_high_filter_blocks_new_buys_but_not_sells_and_says_why(self):
        from dataclasses import replace
        from quantlab.dipbuy.engine import Market
        panel, inp = fixture()
        mret = np.full(ND, 0.001)                                          # 一路微涨：大盘就在高点上
        inp = replace(inp, market=Market(mret=mret, mk20=np.zeros(ND), z=np.zeros(ND), count=np.full(ND, NC)))
        cfg = FusionConfig(positions=5, near_high_on=True)
        filtered = portfolio.fusion.with_near_high_filter(inp, cfg)
        old = dict(id='h1', code='sh.600001', shares=1000, entry_date=day(panel, self.cfg.hold_days), cost=None, sleeve='A')
        p = portfolio.plan_operations(panel, filtered, cfg, [old], equity=1_000_000)
        self.assertFalse(p['gate_open'])
        self.assertEqual(p['buys'], [])
        self.assertEqual([r['code'] for r in p['sells']], ['sh.600001'])       # 到期照常卖
        self.assertTrue(any('近高点过滤已打开' in n for n in p['notes']))
        plain = portfolio.plan_operations(panel, inp, FusionConfig(positions=5), [], equity=1_000_000)
        self.assertEqual(len(plain['buys']), 5)
        self.assertFalse(any('近高点' in n for n in plain['notes']))


    def test_clear_expired_only_removes_overdue(self):
        with tempfile.TemporaryDirectory() as tmp:
            for col, back in ((1, 2), (2, self.cfg.hold_days - 1), (3, self.cfg.hold_days + 4)):
                portfolio.add_holding(tmp, code=f'60000{col}', shares=100, entry_date=day(self.panel, back), sleeve='A')
            n = portfolio.clear_expired(tmp, self.panel, self.cfg.hold_days)
            self.assertEqual(n, 2)
            self.assertEqual([h['code'] for h in portfolio.load(tmp)['holdings']], ['sh.600001'])


if __name__ == '__main__':
    unittest.main()
