"""策略 D（三层恐慌共用一笔钱）：参数、成交额分档、分档恐慌分、共享资金回测（优先级/权重/仓位上限/不重复）、当日信号、前向记录。全部用合成数据。"""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from quantlab.dipbuy import fusion, industry, tracker
from quantlab.dipbuy.engine import Candidates, Market
from quantlab.dipbuy.fusion import FusionConfig, FusionInputs
from quantlab.dipbuy.panel import Panel
from test_dipbuy import make_panel
from test_dipbuy_industry import ND, PER, sector_panel, write_class


def tiered_panel(nd=420, nc=60, drop_from=None, tier=0):
    """60 只股票，成交额按 j%5 分五档（每档 12 只）；drop_from 之后某一档每天跌 1.5%。"""
    rng = np.random.default_rng(5)
    r = rng.normal(0, 0.004, (nd, nc))
    if drop_from is not None:
        r[drop_from:, np.arange(nc) % 5 == tier] = -0.015
    panel = make_panel(10 * np.cumprod(1 + r, axis=0))
    panel.a[:] = (1e8 * (1 + np.arange(nc) % 5))[None, :]
    return panel


def scripted(nd=330, nc=30, gates=None, pools=None, rank=None):
    """直接给定三层闸门日和各层候选，只测共享资金组合。价格全程不动，所以每笔净收益 = 负的交易成本。"""
    panel = make_panel(np.full((nd, nc), 10.0))
    gate = {s: np.zeros(nd, bool) for s in 'ACB'}
    pool = {s: np.zeros((nd, nc), bool) for s in 'ACB'}
    for s, days in (gates or {}).items():
        gate[s][days] = True
    for s, (days, cols) in (pools or {}).items():
        for d in days:
            pool[s][d, cols] = True
    rk = np.tile(np.arange(nc, dtype=np.float32), (nd, 1)) if rank is None else rank
    mk = Market(mret=np.zeros(nd), mk20=np.zeros(nd), z=np.zeros(nd), count=np.full(nd, nc))
    cand = Candidates(uni=np.ones((nd, nc), bool), e6=pool['A'], buyok=np.ones((nd, nc), bool), ret20=rk)
    inp = FusionInputs(market=mk, cand=cand, gates=gate, pools=pool, rank=rk, buyok=cand.buyok,
                       labels=np.zeros((nd, nc), np.int8), z_c=np.zeros((nd, 5)), r20_c=np.zeros((nd, 5)),
                       n_c=np.zeros((nd, 5), np.int32), ind_state=None, cls=None, any_gate=gate['A'] | gate['C'] | gate['B'])
    return panel, inp


class ConfigTests(unittest.TestCase):
    def test_defaults_are_strategy_d(self):
        cfg = FusionConfig()
        self.assertEqual(cfg.weights, {'A': 0.08, 'C': 0.08, 'B': 0.025})
        self.assertEqual((cfg.z_threshold, cfg.positions, cfg.hold_days, cfg.gross_cap, cfg.cash_yield), (-1.5, 20, 20, 1.0, 0.02))

    def test_rejects_leverage_and_silly_values(self):
        for bad in ({'gross_cap': 1.5}, {'weight_b': 0.0}, {'weight_a': 0.9}, {'hold_days': 0}, {'z_threshold': 1.0}, {'cash_yield': 0.5}):
            with self.assertRaises(ValueError):
                FusionConfig(**bad)

    def test_hash_changes_with_parameters_and_roundtrips(self):
        a, b = FusionConfig(), FusionConfig(weight_b=0.03)
        self.assertNotEqual(a.hash(), b.hash())
        self.assertEqual(FusionConfig.from_dict(a.to_dict()), a)
        self.assertEqual(FusionConfig.from_dict({'weight_b': 0.03, 'unknown': 1}), b)
        self.assertEqual(a.dip_config().leverage, 1.0)


class QuintileTests(unittest.TestCase):
    def test_labels_follow_amount_tier_and_skip_non_universe(self):
        panel = tiered_panel()
        market, cand = fusion.compute_features(panel, 5e7, 3.0)
        labels = fusion.amount_labels(panel, cand)
        self.assertTrue((labels[-1] == np.arange(60) % 5).all())
        self.assertTrue((labels[:60] == -1).all())                       # 面板刚开始，还没有 60 日成交额
        cand.uni[-1, 7] = False
        self.assertEqual(fusion.amount_labels(panel, cand)[-1, 7], -1)

    def test_only_the_crashing_tier_gets_a_panic_score(self):
        panel = tiered_panel(drop_from=ND - 20, tier=0)
        market, cand = fusion.compute_features(panel, 5e7, 3.0)
        labels = fusion.amount_labels(panel, cand)
        z, r20, n = fusion.group_state(panel, cand, labels)
        self.assertEqual(z.shape, (420, 5))
        self.assertLess(z[-1, 0], -1.5)
        self.assertTrue((z[-1, 1:] > -1.5).all())
        self.assertEqual(int(n[-1, 0]), 12)
        self.assertLess(r20[-1, 0], -0.2)


class InputsTests(unittest.TestCase):
    def setUp(self):
        self.panel = tiered_panel(drop_from=ND - 20, tier=0)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        import pandas as pd
        rows = [dict(code=str(c).split('.')[-1], start_date='2014-01-01', l1_code=('110000', '220000', '230000')[j // 20])
                for j, c in enumerate(self.panel.codes)]
        pd.DataFrame(rows).to_parquet(Path(self.tmp.name) / '2026-09-23.parquet')
        self.cls = industry.load_classification(self.tmp.name, self.panel.codes)
        self.cfg = FusionConfig()

    def test_amount_tier_gate_opens_and_its_pool_is_that_tier_only(self):
        inp = fusion.build_inputs(self.panel, self.cfg, self.cls)
        self.assertTrue(inp.gates['C'][-1])
        pool = np.nonzero(inp.pools['C'][-1])[0]
        self.assertEqual(set(pool), set(np.nonzero(np.arange(60) % 5 == 0)[0]))
        self.assertFalse(inp.gates['C'][ND - 60])                         # 下跌之前没有触发
        self.assertTrue((inp.any_gate == (inp.gates['A'] | inp.gates['C'] | inp.gates['B'])).all())

    def test_inputs_are_cached_per_threshold(self):
        a = fusion.build_inputs(self.panel, self.cfg, self.cls)
        self.assertIs(a, fusion.build_inputs(self.panel, self.cfg, self.cls))
        self.assertIsNot(a, fusion.build_inputs(self.panel, FusionConfig(z_threshold=-2.5), self.cls))

    def test_signal_ranks_by_drop_and_never_repeats_a_stock(self):
        cfg = FusionConfig(positions=5)
        inp = fusion.build_inputs(self.panel, cfg, self.cls)
        sig = fusion.latest_fusion_signal(self.panel, inp, cfg, equity=1_000_000)
        self.assertTrue(sig['gate_open'] and sig['is_last_day'])
        self.assertIn('C', sig['fired'])
        self.assertEqual(sig['sleeves']['C']['detail'], '成交额最小档')
        codes = [p['code'] for p in sig['picks']]
        self.assertEqual(len(codes), len(set(codes)))
        for s in sig['fired']:
            rets = [p['ret20'] for p in sig['picks'] if p['sleeve'] == s]
            self.assertEqual(rets, sorted(rets))
            self.assertLessEqual(sum(1 for p in sig['picks'] if p['sleeve'] == s and p['in_plan']), 5)
        plan = [p for p in sig['picks'] if p['in_plan']]
        self.assertEqual(sig['plan_size'], len(plan))
        self.assertLessEqual(sum(p['plan_amount'] for p in plan), 1_000_000 + 1)
        first_c = next(p for p in plan if p['sleeve'] == 'C')
        self.assertAlmostEqual(first_c['plan_amount'], 80_000, delta=1)
        self.assertEqual(first_c['plan_shares'] % 100, 0)
        self.assertEqual(first_c['group'], '成交额最小档')
        self.assertEqual(len(sig['quintiles']), 5)
        self.assertEqual(len(sig['industries']), 3)

    def test_calm_day_has_no_picks(self):
        inp = fusion.build_inputs(self.panel, self.cfg, self.cls)
        sig = fusion.latest_fusion_signal(self.panel, inp, self.cfg, day=str(self.panel.dates[ND - 60]))
        self.assertFalse(sig['gate_open'])
        self.assertEqual((sig['fired'], sig['picks']), ([], []))
        self.assertFalse(sig['is_last_day'])


class SharedAccountTests(unittest.TestCase):
    cfg = dict(hold_days=20, start='2024-01-02')

    def run_sim(self, cfg, gates, pools):
        panel, inp = scripted(gates=gates, pools=pools)
        return panel, fusion.simulate_fused(panel, inp, cfg)

    def test_priority_weights_and_no_repeat_across_sleeves(self):
        days = [300]
        panel, raw = self.run_sim(FusionConfig(**self.cfg), {s: days for s in 'ACB'},
                                  {'A': (days, [0, 1, 2]), 'C': (days, [1, 2, 3, 4]), 'B': (days, [3, 4, 5, 6, 7, 8])})
        by = {}
        for t in raw['trades']:
            by.setdefault(t['sleeve'], []).append(t)
        self.assertEqual({s: sorted(t['code'][-1] for t in v) for s, v in by.items()},
                         {'A': ['0', '1', '2'], 'C': ['3', '4'], 'B': ['5', '6', '7', '8']})
        equity = float(raw['eq'][300])           # 信号日的净值（空仓期间已经按 2% 计息）
        w = {s: np.mean([t['weight'] for t in v]) / equity for s, v in by.items()}
        self.assertAlmostEqual(w['A'], 0.08, delta=0.002)
        self.assertAlmostEqual(w['C'], 0.08, delta=0.002)
        self.assertAlmostEqual(w['B'], 0.025, delta=0.002)
        self.assertEqual(len({t['code'] for t in raw['trades']}), len(raw['trades']))
        self.assertAlmostEqual(raw['expo'][303], 0.08 * 3 + 0.08 * 2 + 0.025 * 4, delta=0.01)
        self.assertEqual(sum(1 for t in raw['trades'] if t['entry'] != raw['trades'][0]['entry']), 0)

    def test_gross_cap_stops_buying_and_there_is_no_borrowing(self):
        days = [300]
        cfg = FusionConfig(weight_a=0.3, weight_c=0.3, weight_b=0.3, gross_cap=0.5, **self.cfg)
        panel, raw = self.run_sim(cfg, {s: days for s in 'ACB'}, {s: (days, list(range(10 * 'ACB'.index(s), 10 * 'ACB'.index(s) + 5))) for s in 'ACB'})
        self.assertAlmostEqual(sum(t['weight'] for t in raw['trades']), 0.5 * float(raw['eq'][300]), delta=0.005)
        self.assertEqual([t['sleeve'] for t in raw['trades']], ['A', 'A'])          # 前面的层先吃满额度，后面的买不到
        self.assertLessEqual(float(np.nanmax(raw['expo'])), 0.5 + 0.01)
        self.assertGreater(float(raw['eq'][-1]), 0.99)                               # 没借钱，没有利息

    def test_each_sleeve_has_its_own_slot_limit(self):
        days = [300]
        cfg = FusionConfig(positions=2, **self.cfg)
        panel, raw = self.run_sim(cfg, {s: days for s in 'ACB'}, {'A': (days, list(range(6))), 'C': (days, list(range(6, 12))), 'B': (days, list(range(12, 18)))})
        counts = {s: sum(1 for t in raw['trades'] if t['sleeve'] == s) for s in 'ACB'}
        self.assertEqual(counts, {'A': 2, 'C': 2, 'B': 2})

    def test_later_sleeve_fills_idle_money_on_days_earlier_ones_do_not_fire(self):
        panel, raw = self.run_sim(FusionConfig(**self.cfg), {'B': [300, 301]}, {'B': ([300, 301], [0, 1, 2]) })
        self.assertEqual(sorted(t['code'][-1] for t in raw['trades']), ['0', '1', '2'])   # 第二天不会重复买已经持有的

    def test_idle_cash_earns_the_yield_and_costs_are_charged(self):
        panel, raw = self.run_sim(FusionConfig(**self.cfg), {'A': [300]}, {'A': ([300], [0])})
        self.assertGreater(raw['info']['cash_earned'], 0)
        self.assertLess(raw['trades'][0]['ret'], 0)                                # 价格没动，只剩手续费和 tick 成本
        flat = fusion.simulate_fused(*scripted(gates={}, pools={}), FusionConfig(cash_yield=0.0, **self.cfg))
        self.assertAlmostEqual(float(flat['eq'][-1]), 1.0, places=9)

    def test_no_entry_on_the_last_day_and_run_backtest_sections(self):
        panel, inp = scripted(gates={'A': [329]}, pools={'A': ([329], [0])})
        raw = fusion.simulate_fused(panel, inp, FusionConfig(**self.cfg))
        self.assertEqual((raw['trades'], raw['open_positions']), ([], []))
        s = fusion.sleeve_stats(raw)
        self.assertEqual(set(s), {'A', 'C', 'B'})
        self.assertEqual(s['A']['gate_days'], 1)


class BacktestAndLedgerTests(unittest.TestCase):
    def setUp(self):
        self.panel = sector_panel(330, drop_days=20, recover_days=30)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        write_class(self.tmp.name, self.panel)
        self.cls = industry.load_classification(self.tmp.name, self.panel.codes)
        self.cfg = FusionConfig(positions=5, hold_days=10, start='2024-01-02')

    def cut(self, n):
        p = self.panel
        return Panel(dates=p.dates[:n], codes=p.codes, o=p.o[:n], c=p.c[:n], f=p.f[:n], a=p.a[:n], st=p.st[:n], ts=p.ts[:n], meta={})

    def test_backtest_result_shape(self):
        run = fusion.run_backtest(self.panel, self.cfg, self.cls)
        self.assertEqual(run['kind'], 'fusion')
        self.assertEqual(run['engine_version'], fusion.FUSION_VERSION)
        self.assertEqual(set(run['summary']['sleeves']), {'A', 'C', 'B'})
        self.assertGreater(len(run['trades']), 0)
        self.assertTrue(all(t['sleeve'] in 'ACB' for t in run['trades']))
        self.assertLessEqual(run['summary']['stats']['exposure'], 1.0)
        self.assertEqual(run['config_hash'], self.cfg.hash())
        self.assertEqual(run['content_hash'], fusion.run_backtest(self.panel, self.cfg, self.cls)['content_hash'])
        self.assertTrue(any('幸存者偏差' in c for c in run['caveats']))

    def test_fusion_ledger_is_separate_weighted_and_capped_per_sleeve(self):
        cut = self.cut(350)
        inp = fusion.build_inputs(cut, self.cfg, self.cls)
        sig = fusion.latest_fusion_signal(cut, inp, self.cfg, equity=500_000)
        self.assertTrue(sig['gate_open'])
        with tempfile.TemporaryDirectory() as out:
            record = tracker.record_signal(out, sig, self.cfg, kind='fusion')
            self.assertTrue((Path(out) / '_home' / 'dip_fusion_forward.json').is_file())
            self.assertFalse((Path(out) / '_home' / 'dip_forward.json').exists())
            self.assertEqual(record['fired'], sig['fired'])
            self.assertEqual({p['sleeve'] for p in record['picks']}, {p['sleeve'] for p in sig['picks']})
            self.assertTrue(all('weight' in p for p in record['picks']))
            with self.assertRaisesRegex(ValueError, '已经记录'):
                tracker.record_signal(out, sig, self.cfg, kind='fusion')
            settled = tracker.settle_ledger(out, self.panel, kind='fusion')
            res = settled['records'][0]['result']
            per = {}
            for r in res['rows']:
                if not r['not_filled'] and r['in_plan']:
                    per[r.get('sleeve')] = per.get(r.get('sleeve'), 0) + 1
            self.assertTrue(all(n <= 5 for n in per.values()))
            self.assertIsNotNone(res['mean_ret'])
            closed = [r for r in res['rows'] if r['status'] == 'closed' and r['in_plan']]
            expect = sum(r['weight'] * r['ret'] for r in closed) / sum(r['weight'] for r in closed)
            self.assertAlmostEqual(res['mean_ret'], expect, places=9)
            port = fusion.forward_portfolio(out, self.panel, self.cls)
            self.assertEqual(port['start_date'], record['signal_date'])
            tracker.clear_ledger(out, 'fusion')
            self.assertEqual(tracker.load_ledger(out, 'fusion')['records'], [])

    def test_closed_gate_cannot_be_recorded(self):
        cut = self.cut(300)
        inp = fusion.build_inputs(cut, self.cfg, self.cls)
        sig = fusion.latest_fusion_signal(cut, inp, self.cfg)
        self.assertFalse(sig['gate_open'])
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(ValueError, '三层闸门都没开'):
                tracker.record_signal(out, sig, self.cfg, kind='fusion')


if __name__ == '__main__':
    unittest.main()
