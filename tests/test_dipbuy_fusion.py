"""策略 D（三层恐慌共用一笔钱）：参数、成交额分档、分档恐慌分、共享资金回测（优先级/权重/仓位上限/不重复）、当日信号、前向记录。全部用合成数据。"""
import tempfile
import unittest
from pathlib import Path

from dataclasses import replace
from types import SimpleNamespace

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

    def test_delisted_stock_exits_at_last_price_and_equity_stays_finite(self):
        panel, inp = scripted(gates={'A': [300]}, pools={'A': ([300], [0, 1])})
        panel.c[305:, 0] = np.nan                       # 0 号股票 305 日起退市：没有价格，也没有复权因子
        panel.o[305:, 0] = np.nan
        panel.f[305:, 0] = np.nan
        raw = fusion.simulate_fused(panel, inp, FusionConfig(hold_days=20, start='2024-01-02'))
        self.assertEqual(len(raw['trades']), 2)
        self.assertTrue(all(np.isfinite(t['ret']) for t in raw['trades']))
        self.assertTrue(np.isfinite(raw['eq'][raw['t0']:raw['tend'] + 1]).all())

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


class RankOptionTests(unittest.TestCase):
    """D1 = D 只换候选排序：先取 20 日跌幅前 K，再按 60 日回撤最深优先。"""

    def test_default_hash_is_unchanged_and_d1_is_a_separate_config(self):
        d, d1 = FusionConfig(), fusion.d1_config()
        self.assertEqual(d.hash(), '50af776c23a6')                       # 加排序选项之前 D 的哈希，已有前向记录靠它对账
        self.assertEqual((d.variant, d1.variant), ('D', 'D1'))
        self.assertNotEqual(d.hash(), d1.hash())
        self.assertEqual(FusionConfig.from_dict(d1.to_dict()), d1)
        legacy = {k: v for k, v in d.to_dict().items() if k not in ('rank_mode', 'rank_k')}
        self.assertEqual(FusionConfig.from_dict(legacy), d)              # 旧台账里的参数没有排序字段，读出来仍是 D
        self.assertEqual(FusionConfig(rank_k=60).hash(), d.hash())       # D 不用 rank_k，不影响哈希
        self.assertNotEqual(FusionConfig(rank_mode='dd60', rank_k=60).hash(), d1.hash())
        for bad in ({'rank_mode': 'x'}, {'rank_mode': 'dd60', 'rank_k': 1}, {'rank_k': 500}):
            with self.assertRaises(ValueError):
                FusionConfig(**bad)
        self.assertEqual(fusion.config_for('D1'), d1)
        self.assertEqual(fusion.config_for('D'), d)

    def test_drawdown60_matches_a_naive_loop(self):
        rng = np.random.default_rng(3)
        c = 10 * np.cumprod(1 + rng.normal(0, 0.02, (150, 6)), axis=0)
        c[40:70, 1] = np.nan                                              # 停牌
        c[:90, 2] = np.nan                                                # 还没上市
        panel = make_panel(c)
        got = fusion.drawdown60(panel)
        want = np.full(c.shape, np.nan)
        for t in range(c.shape[0]):
            win = panel.c[max(0, t - 59):t + 1].astype(np.float64)
            for j in range(c.shape[1]):
                col = win[:, j]
                if np.isfinite(col).sum() >= 40 and np.isfinite(panel.c[t, j]):
                    want[t, j] = panel.c[t, j] / np.nanmax(col) - 1
        np.testing.assert_allclose(got, want, rtol=1e-5, atol=1e-6, equal_nan=True)
        self.assertLessEqual(float(np.nanmax(got)), 1e-6)
        self.assertIs(fusion.drawdown60(panel), got)                      # 缓存在面板上

    def dd_setup(self):
        panel, inp = scripted(gates={'A': [300]}, pools={'A': ([300], list(range(10)))})        # 20 日跌幅排名 = 列号
        dd = np.zeros(panel.shape, np.float32)
        dd[300, :5] = [-0.1, -0.5, -0.3, -0.9, -0.2]
        dd[300, 5:] = -0.99                                                                    # 没入选前 K 的，回撤再深也排在后面
        panel.cache[('fusion-dd60',)] = dd
        return panel, inp

    def test_two_stage_order_takes_top_k_by_drop_then_deepest_drawdown(self):
        panel, inp = self.dd_setup()
        base = np.nonzero(inp.pools['A'][300] & inp.buyok[300])[0]
        pool = np.array([j for j in base if j != 3])                                           # 3 号已持有
        d1 = fusion.order_candidates(panel, inp, FusionConfig(rank_mode='dd60', rank_k=5), 300, base, pool)
        self.assertEqual(list(d1), [1, 2, 4, 0, 5, 6, 7, 8, 9])
        d = fusion.order_candidates(panel, inp, FusionConfig(), 300, base, pool)
        self.assertEqual(list(d), [0, 1, 2, 4, 5, 6, 7, 8, 9])

    def test_simulation_buys_d1_picks_in_drawdown_order_and_d_unchanged(self):
        panel, inp = self.dd_setup()
        got = {}
        for name, cfg in (('D', FusionConfig(positions=3, hold_days=20, start='2024-01-02')),
                          ('D1', FusionConfig(positions=3, hold_days=20, start='2024-01-02', rank_mode='dd60', rank_k=5))):
            raw = fusion.simulate_fused(panel, inp, cfg)
            got[name] = sorted(t['code'][-1] for t in raw['trades'])
        self.assertEqual(got, {'D': ['0', '1', '2'], 'D1': ['1', '2', '3']})


class RankOptionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.panel = sector_panel(330, drop_days=20, recover_days=30)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        write_class(self.tmp.name, self.panel)
        self.cls = industry.load_classification(self.tmp.name, self.panel.codes)
        self.d = FusionConfig(positions=5, hold_days=10, start='2024-01-02')
        self.d1 = FusionConfig(positions=5, hold_days=10, start='2024-01-02', rank_mode='dd60', rank_k=10)

    def cut(self, n):
        p = self.panel
        return Panel(dates=p.dates[:n], codes=p.codes, o=p.o[:n], c=p.c[:n], f=p.f[:n], a=p.a[:n], st=p.st[:n], ts=p.ts[:n], meta={})

    def test_d1_has_its_own_ledger_signal_fields_and_backtest(self):
        cut = self.cut(350)
        sig_d = fusion.latest_fusion_signal(cut, fusion.build_inputs(cut, self.d, self.cls), self.d)
        sig = fusion.latest_fusion_signal(cut, fusion.build_inputs(cut, self.d1, self.cls), self.d1)
        self.assertEqual((sig_d['variant'], sig['variant']), ('D', 'D1'))
        self.assertTrue(all(p['dd60'] is None for p in sig_d['picks']))
        self.assertTrue(sig['picks'] and all(p['dd60'] is not None and p['dd60'] <= 0 for p in sig['picks']))
        with tempfile.TemporaryDirectory() as out:
            tracker.record_signal(out, sig, self.d1, kind='fusion1')
            self.assertTrue((Path(out) / '_home' / 'dip_fusion1_forward.json').is_file())
            self.assertFalse((Path(out) / '_home' / 'dip_fusion_forward.json').exists())     # D 的记录不受影响
            self.assertEqual(tracker.load_ledger(out, 'fusion1')['config']['rank_mode'], 'dd60')
            with self.assertRaisesRegex(ValueError, '已有前向记录'):
                tracker.record_signal(out, dict(sig, date='2099-01-01'), self.d, kind='fusion1')   # 参数冻结：不能把 D 记进 D1 的台账
            port = fusion.forward_portfolio(out, self.panel, self.cls, kind='fusion1')
            self.assertIsNotNone(port)
            self.assertIsNone(fusion.forward_portfolio(out, self.panel, self.cls, kind='fusion'))
            tracker.clear_ledger(out, 'fusion1')
            self.assertEqual(tracker.load_ledger(out, 'fusion1')['records'], [])
        run = fusion.run_backtest(self.panel, self.d1, self.cls)
        self.assertEqual(run['config']['rank_mode'], 'dd60')
        self.assertEqual(run['config_hash'], self.d1.hash())
        self.assertGreater(len(run['trades']), 0)
        self.assertTrue(any('D1' in c for c in run['caveats']))


class NearHighFilterTests(unittest.TestCase):
    """可选的近高点过滤：大盘离近 window 日高点不足 pct 时，三层闸门全部关掉。默认关，关着时和没有这个选项完全一样。"""

    def market_inp(self, gate_days=(30, 150, 250), nd=330):
        panel, inp = scripted(nd=nd, gates={'A': list(gate_days)}, pools={'A': (list(gate_days), [0, 1])})
        mret = np.where(np.arange(nd) < 200, 0.005, -0.02)               # 前 200 天一路涨到高点，之后天天跌 2%
        mk = Market(mret=mret, mk20=np.zeros(nd), z=np.zeros(nd), count=np.full(nd, 30))
        stub_cls = SimpleNamespace(codes=[], names=[], sizes=[], as_of='2024-01-01', n_mapped=0, name_of=lambda j: '')
        stub_ind = SimpleNamespace(z=np.zeros((nd, 0)), n=np.zeros((nd, 0), int), ret20=np.zeros((nd, 0)))
        return panel, replace(inp, market=mk, cls=stub_cls, ind_state=stub_ind)

    def test_off_by_default_keeps_the_old_hash_and_validates(self):
        d, on = FusionConfig(), FusionConfig(near_high_on=True)
        self.assertEqual((d.near_high_on, d.near_high_window, d.near_high_pct), (False, 120, 0.05))
        self.assertEqual(d.hash(), '50af776c23a6')                       # 关着时哈希不变，已有前向记录照常对账
        self.assertEqual(FusionConfig(near_high_window=250, near_high_pct=0.03).hash(), d.hash())
        self.assertNotEqual(on.hash(), d.hash())
        self.assertNotEqual(on.hash(), FusionConfig(near_high_on=True, near_high_pct=0.03).hash())
        self.assertEqual(FusionConfig.from_dict(on.to_dict()), on)
        self.assertEqual(FusionConfig.from_dict({k: v for k, v in d.to_dict().items() if not k.startswith('near_high')}), d)
        for bad in ({'near_high_window': 5}, {'near_high_window': 5000}, {'near_high_pct': 0.0}, {'near_high_pct': 0.5}):
            with self.assertRaises(ValueError):
                FusionConfig(**bad)

    def test_gap_matches_a_naive_loop(self):
        _, inp = self.market_inp()
        idx = np.cumprod(1 + inp.market.mret)
        gap = fusion.near_high_gap(inp.market, 60)
        self.assertTrue(np.isnan(gap[:59]).all())
        for t in (59, 100, 199, 200, 250, 329):
            self.assertAlmostEqual(gap[t], idx[t] / idx[t - 59:t + 1].max() - 1, places=12)
        self.assertEqual(gap[150], 0.0)                                   # 一路涨：就在高点上
        self.assertLess(gap[250], -0.5)

    def test_filter_closes_gates_near_the_high_and_keeps_the_rest(self):
        panel, inp = self.market_inp()
        off = FusionConfig(near_high_window=60)
        self.assertIs(fusion.with_near_high_filter(inp, off), inp)        # 关着：原样返回
        cfg = FusionConfig(near_high_on=True, near_high_window=60)
        f = fusion.with_near_high_filter(inp, cfg)
        self.assertEqual([bool(f.any_gate[t]) for t in (30, 150, 250)], [True, False, True])    # 30 天历史不够不过滤，150 在高点被挡，250 已深跌放行
        self.assertEqual([bool(f.gates['A'][t]) for t in (30, 150, 250)], [True, False, True])
        self.assertTrue(f.raw_any_gate[150] and not f.any_gate[150])
        self.assertTrue(inp.any_gate[150])                                # 原对象不被改动
        loose = fusion.with_near_high_filter(inp, FusionConfig(near_high_on=True, near_high_window=60, near_high_pct=0.20))
        self.assertFalse(loose.any_gate[150])

    def test_simulation_skips_the_blocked_signal_day_and_signal_reports_it(self):
        panel, inp = self.market_inp()
        cfg = FusionConfig(near_high_on=True, near_high_window=60)
        base = fusion.simulate_fused(panel, inp, FusionConfig())
        raw = fusion.simulate_fused(panel, fusion.with_near_high_filter(inp, cfg), cfg)
        days = lambda r: sorted({str(t['signal']) for t in r['trades']})
        self.assertEqual(len(base['trades']), 6)
        self.assertEqual(len(raw['trades']), 4)
        self.assertNotIn(str(panel.dates[150]), days(raw))
        self.assertIn(str(panel.dates[150]), days(base))
        sig = fusion.latest_fusion_signal(panel, fusion.with_near_high_filter(inp, cfg), cfg, day=str(panel.dates[150]))
        self.assertFalse(sig['gate_open'])
        self.assertEqual(sig['picks'], [])
        mp = sig['market_position']
        self.assertTrue(mp['on'] and mp['blocked'] and mp['would_block'])
        self.assertEqual((mp['window'], mp['pct']), (60, 0.05))
        deep = fusion.latest_fusion_signal(panel, fusion.with_near_high_filter(inp, cfg), cfg, day=str(panel.dates[250]))
        self.assertTrue(deep['gate_open'])
        self.assertFalse(deep['market_position']['blocked'] or deep['market_position']['would_block'])
        plain = fusion.latest_fusion_signal(panel, inp, FusionConfig(near_high_window=60), day=str(panel.dates[150]))
        self.assertTrue(plain['gate_open'])                               # 过滤关着：照常有信号
        self.assertTrue(plain['market_position']['would_block'] and not plain['market_position']['blocked'])


if __name__ == '__main__':
    unittest.main()
