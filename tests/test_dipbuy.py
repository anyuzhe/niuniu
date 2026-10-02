"""恐慌日抄底策略：特征、组合引擎（含杠杆/强平）、回测存取、前向记录、面板读取。全部用合成数据。"""
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import numpy as np

from quantlab.dipbuy import backtest, engine, panel as panel_mod, tracker
from quantlab.dipbuy.engine import Candidates, DipConfig, Market
from quantlab.dipbuy.panel import Cancelled, DipDataError, Panel


def make_dates(n, start='2024-01-02'):
    d = np.busday_offset(np.datetime64(start), np.arange(n), roll='forward')
    return d.astype(str).astype('<U10')


def make_panel(prices, *, amount=1e8):
    """prices: [nd, nc]，前复权=原始（factor=1），开盘=昨收。"""
    prices = np.asarray(prices, np.float32)
    nd, nc = prices.shape
    o = np.vstack([prices[:1], prices[:-1]])
    return Panel(dates=make_dates(nd), codes=np.array([f'sh.60000{i}' for i in range(nc)]), o=o.copy(), c=prices.copy(),
                 f=np.ones((nd, nc), np.float32), a=np.full((nd, nc), amount, np.float32),
                 st=np.zeros((nd, nc), bool), ts=np.ones((nd, nc), np.int8), meta={'signature': 'x'})


def scripted(nd, nc, z_at, e6_at, ret20=None):
    """直接给定闸门日和候选，只测组合引擎。"""
    z = np.full(nd, 0.0)
    z[z_at] = -2.0
    market = Market(mret=np.zeros(nd), mk20=np.zeros(nd), z=z, count=np.full(nd, 100.0))
    e6 = np.zeros((nd, nc), bool)
    for t, js in e6_at.items():
        e6[t, js] = True
    r = np.full((nd, nc), 0.0, np.float32) if ret20 is None else ret20
    return market, Candidates(uni=np.ones((nd, nc), bool), e6=e6, buyok=np.ones((nd, nc), bool), ret20=r)


def cfg(**kw):
    base = dict(positions=2, hold_days=5, leverage=1.0, start='2024-01-02', slippage_bp=0.0)
    base.update(kw)
    return DipConfig(**base)


class ConfigTests(unittest.TestCase):
    def test_validation_and_hash(self):
        with self.assertRaises(ValueError):
            DipConfig(leverage=5)
        with self.assertRaises(ValueError):
            DipConfig(rank='x')
        with self.assertRaises(ValueError):
            DipConfig(liquidation_line=1.6, warn_line=1.5)
        a, b = DipConfig(), DipConfig()
        self.assertEqual(a.hash(), b.hash())
        self.assertNotEqual(a.hash(), DipConfig(leverage=1.0).hash())
        self.assertEqual(DipConfig.from_dict(a.to_dict()), a)
        self.assertEqual(DipConfig.from_dict({'leverage': 1.5, 'junk': 1}).leverage, 1.5)


class FeatureTests(unittest.TestCase):
    def test_bollinger_reclaim_marks_e6(self):
        rng = np.random.default_rng(1)
        nd = 330
        base = 10 + 0.05 * np.sin(np.arange(nd))
        p = np.tile(base[:, None], (1, 3)).astype(np.float64)
        p[300:, 0] = 8.0               # 第 300 天暴跌到下轨之下
        p[301, 0] = 9.9                # 第 301 天收回并收阳
        p[302:, 0] = 9.9
        panel = make_panel(p)
        panel.o[301, 0] = 9.0          # 低开高走 -> 阳线
        market, cand = engine.compute_features(panel)
        self.assertTrue(cand.e6[301, 0])
        self.assertFalse(cand.e6[301, 1])      # 平稳的股票没有信号
        self.assertFalse(cand.e6[300, 0])      # 暴跌当天只是跌破，还没收复
        self.assertTrue(np.isfinite(cand.ret20[301, 0]))

    def test_st_and_cheap_and_illiquid_are_not_candidates(self):
        nd = 330
        p = np.tile((10 + 0.05 * np.sin(np.arange(nd)))[:, None], (1, 4))
        p[300:, :] = 8.0
        p[301:, :] = 9.9
        panel = make_panel(p)
        panel.o[301, :] = 9.0
        panel.st[:, 1] = True
        panel.a[:, 2] = 1e6
        panel.ts[301, 3] = 0
        _, cand = engine.compute_features(panel)
        self.assertTrue(cand.e6[301, 0])
        self.assertFalse(cand.e6[301, 1])
        self.assertFalse(cand.e6[301, 2])
        self.assertFalse(cand.e6[301, 3])

    def test_z_gate_opens_after_market_crash(self):
        rng = np.random.default_rng(3)
        nd, nc = 200, 30
        r = rng.normal(0, 0.005, (nd, nc))
        r[150:170] -= 0.01             # 20 天每天多跌 1%
        p = 10 * np.cumprod(1 + r, 0)
        panel = make_panel(p)
        market, _ = engine.compute_features(panel)
        self.assertLess(market.z[169], -1.5)
        self.assertGreater(market.z[120], -1.5)
        self.assertTrue(np.isnan(market.z[10]))

    def test_features_cached_per_panel(self):
        panel = make_panel(np.full((330, 2), 10.0))
        self.assertIs(engine.compute_features(panel), engine.compute_features(panel))
        self.assertIsNot(engine.compute_features(panel), engine.compute_features(panel, 1e6, 3.0))


class SimulateTests(unittest.TestCase):
    def setUp(self):
        nd = 40
        self.p = np.full((nd, 3), 10.0)
        self.panel = make_panel(self.p)

    def test_trade_timing_and_cost(self):
        p = self.p.copy()
        p[6:, 0] = 10.0
        p[10:, 0] = 11.0                   # 信号日 t=5，次日开盘 t=6 买，t=10 收盘卖
        panel = make_panel(p)
        panel.o[6, 0] = 10.0
        market, cand = scripted(40, 3, [5], {5: [0]})
        res = engine.simulate(panel, market, cand, cfg(positions=1))
        self.assertEqual(len(res['trades']), 1)
        tr = res['trades'][0]
        self.assertEqual((tr['signal'], tr['entry'], tr['exit']), (str(panel.dates[5]), str(panel.dates[6]), str(panel.dates[10])))
        expected = (11 - 0.01) / (10 + 0.01) - 1 - 0.0005 - 0.00022
        self.assertAlmostEqual(tr['ret'], expected, places=6)
        self.assertAlmostEqual(res['eq'][11], 1 + expected, places=6)      # 1x、N=1：全仓
        self.assertEqual(res['info']['n_liquidations'], 0)

    def test_ranking_prefers_biggest_20d_drop(self):
        ret = np.zeros((40, 3), np.float32)
        ret[5] = [-0.05, -0.30, -0.10]
        market, cand = scripted(40, 3, [5], {5: [0, 1, 2]}, ret)
        res = engine.simulate(self.panel, market, cand, cfg(positions=1))
        self.assertEqual(res['trades'][0]['code'], 'sh.600001')
        res2 = engine.simulate(self.panel, market, cand, cfg(positions=2))
        self.assertEqual({t['code'] for t in res2['trades']}, {'sh.600001', 'sh.600002'})

    def test_random_rank_is_seeded(self):
        market, cand = scripted(40, 3, [5], {5: [0, 1, 2]})
        a = engine.simulate(self.panel, market, cand, cfg(positions=1, rank='random', seed=1))['trades']
        b = engine.simulate(self.panel, market, cand, cfg(positions=1, rank='random', seed=1))['trades']
        self.assertEqual(a, b)

    def test_leverage_charges_interest_on_borrowed_cash(self):
        market, cand = scripted(40, 3, [5], {5: [0, 1]})
        flat1 = engine.simulate(self.panel, market, cand, cfg(leverage=1.0))
        flat2 = engine.simulate(self.panel, market, cand, cfg(leverage=2.0))
        self.assertEqual(flat1['info']['interest'], 0.0)
        # 2x：借 1.0，6%/242 一天，信号日到卖出前一天共 5 个交易日
        self.assertAlmostEqual(flat2['info']['interest'], 1.0 * 0.06 / 242 * 5, places=5)   # 利息滚入负债，略大于单利
        # 平价进出：2x 的成本翻倍，再扣利息
        self.assertAlmostEqual(flat2['eq'][20], 1 + 2 * (flat1['eq'][20] - 1) - flat2['info']['interest'], places=6)
        self.assertIsNotNone(flat2['info']['min_margin_ratio'])

    def test_cash_yield_adds_return_when_idle(self):
        market, cand = scripted(40, 3, [], {})
        base = engine.simulate(self.panel, market, cand, cfg())
        paid = engine.simulate(self.panel, market, cand, cfg(cash_yield=0.02))
        self.assertAlmostEqual(base['eq'][30], 1.0)
        self.assertGreater(paid['eq'][30], 1.0)

    def test_crash_triggers_liquidation(self):
        p = self.p.copy()
        p[7:, :] = 6.0                     # 买入后暴跌 40%
        panel = make_panel(p)
        market, cand = scripted(40, 3, [5], {5: [0, 1]})
        res = engine.simulate(panel, market, cand, cfg(leverage=2.0))
        self.assertEqual(res['info']['n_liquidations'], 1)
        self.assertTrue(any(t['closed'] == 'liquidated' for t in res['trades']))
        self.assertLess(res['info']['min_margin_ratio'], 1.3)
        res1 = engine.simulate(panel, market, cand, cfg(leverage=1.0))
        self.assertEqual(res1['info']['n_liquidations'], 0)

    def test_no_double_buy_and_slots(self):
        market, cand = scripted(40, 3, [5, 6, 7], {5: [0], 6: [0, 1], 7: [0, 1, 2]})
        res = engine.simulate(self.panel, market, cand, cfg(positions=2))
        codes = [t['code'] for t in res['trades']] + [p['code'] for p in res['open_positions']]
        self.assertEqual(sorted(codes), ['sh.600000', 'sh.600001'])    # 已持有的不重复买，满 2 只后不再开

    def test_open_position_at_end_is_marked_not_dropped(self):
        market, cand = scripted(40, 3, [30], {30: [0]})
        res = engine.simulate(self.panel, market, cand, cfg(positions=1, hold_days=20))
        self.assertEqual(res['trades'], [])
        self.assertEqual(len(res['open_positions']), 1)
        self.assertEqual(res['open_positions'][0]['code'], 'sh.600000')
        self.assertFalse(np.isnan(res['eq'][39]))

    def test_stop_event_cancels(self):
        market, cand = scripted(40, 3, [5], {5: [0]})
        stop = threading.Event()
        stop.set()
        with self.assertRaises(Cancelled):
            engine.simulate(self.panel, market, cand, cfg(), stop=stop)

    def test_summary_and_curves(self):
        market, cand = scripted(40, 3, [5], {5: [0, 1]})
        res = engine.simulate(self.panel, market, cand, cfg())
        cv = engine.curve(self.panel, market, res)
        self.assertEqual(len(cv['dates']), len(cv['equity']))
        self.assertEqual(len(engine.drawdown_series(cv['equity'])), len(cv['dates']))
        s = engine.summarize(self.panel, market, res, cfg())
        self.assertEqual(s['gate_days'], 1)
        self.assertEqual(s['episodes'], 1)
        self.assertEqual(s['trades']['n'], 2)

    def test_episodes(self):
        g = np.zeros(60, bool)
        g[[3, 4, 5, 12, 40]] = True
        self.assertEqual(engine.episodes(g), [(3, 5), (12, 12), (40, 40)])


class SignalTests(unittest.TestCase):
    def test_latest_signal_plan_sizes_and_flags(self):
        nd = 330
        p = np.tile((10 + 0.05 * np.sin(np.arange(nd)))[:, None], (1, 3))
        p[300:, :] = 8.0
        p[301:, :] = 9.9
        p[301:, 1] = 9.95
        panel = make_panel(p)
        panel.o[301, :] = 9.0
        market, cand = engine.compute_features(panel)
        market.z[:] = -2.0
        sig = engine.latest_signal(panel, market, cand, cfg(positions=2, leverage=2.0), equity=100000, day=str(panel.dates[301]),
                                   names={'sh.600000': '甲'})
        self.assertTrue(sig['gate_open'])
        self.assertFalse(sig['is_last_day'])
        self.assertEqual(sig['n_e6'], 3)
        top = sig['picks'][0]
        self.assertEqual(top['plan_amount'], 100000.0)
        self.assertEqual(top['plan_shares'] % 100, 0)
        self.assertEqual(sum(1 for x in sig['picks'] if x['in_plan']), 2)
        self.assertEqual(sig['recent'][-1]['date'], str(panel.dates[301]))

    def test_settle_picks_prices_and_not_filled(self):
        nd = 40
        p = np.full((nd, 2), 10.0)
        p[10:, 0] = 11.0
        panel = make_panel(p)
        panel.o[6, 1] = 11.0                # 次日开盘 +10% 涨停：买不进
        picks = [{'rank': 1, 'code': 'sh.600001'}, {'rank': 2, 'code': 'sh.600000'}]
        rows = engine.settle_picks(panel, picks, str(panel.dates[5]), cfg())
        self.assertTrue(rows[0]['not_filled'])
        self.assertEqual(rows[1]['status'], 'closed')
        self.assertAlmostEqual(rows[1]['ret'], (11 - 0.01) / (10 + 0.01) - 1 - 0.0005 - 0.00022, places=6)
        early = engine.settle_picks(panel, picks[1:], str(panel.dates[37]), cfg())
        self.assertEqual(early[0]['status'], 'held' if early[0]['entry_date'] else 'waiting')


class RunStoreTests(unittest.TestCase):
    def test_save_load_list_roundtrip(self):
        panel = make_panel(np.full((330, 4), 10.0))
        result = backtest.run_backtest(panel, DipConfig(start=str(panel.dates[100])))
        self.assertEqual(result['format'], backtest.RUN_FORMAT)
        self.assertEqual(result['content_hash'], backtest.content_hash(result))
        again = backtest.run_backtest(panel, DipConfig(start=str(panel.dates[100])))
        self.assertEqual(result['content_hash'], again['content_hash'])
        with tempfile.TemporaryDirectory() as tmp:
            run_id = backtest.save_run(tmp, result)
            loaded = backtest.load_run(tmp, run_id)
            self.assertEqual(loaded['content_hash'], result['content_hash'])
            rows = backtest.list_runs(tmp)
            self.assertEqual(rows[0]['run_id'], run_id)
            for bad in ('../x', '', 'abc'):
                with self.assertRaises(ValueError):
                    backtest.load_run(tmp, bad)
            self.assertEqual(backtest.list_runs(Path(tmp) / 'nothing'), [])
            (Path(tmp) / '_dipbuy' / 'runs' / 'junk.json').write_text('{', encoding='utf-8')
            self.assertEqual(len(backtest.list_runs(tmp)), 1)

    def test_symlinked_runs_dir_refused(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            (Path(tmp) / '_dipbuy').mkdir()
            (Path(tmp) / '_dipbuy' / 'runs').symlink_to(other)
            with self.assertRaises(ValueError):
                backtest.save_run(tmp, {'summary': {}})


def crash_panel():
    """一个有恐慌日、有候选股的合成面板：闸门日出现在最后几天。"""
    rng = np.random.default_rng(11)
    nd, nc = 330, 25
    r = rng.normal(0, 0.004, (nd, nc))
    r[300:320] -= 0.012
    p = 10 * np.cumprod(1 + r, 0)
    return make_panel(p)


class TrackerTests(unittest.TestCase):
    def signal(self, panel, c, day=None, z=-2.0):
        market, cand = engine.compute_features(panel)
        market.z[:] = z
        cand.e6[:] = False
        t = panel.index_of(day) if day else len(panel.dates) - 1
        cand.e6[t, :6] = True
        cand.ret20[t, :6] = np.linspace(-0.3, -0.1, 6)
        return engine.latest_signal(panel, market, cand, c, day=day)

    def test_record_guards_and_settle(self):
        panel = make_panel(np.full((60, 8), 10.0))
        c = cfg(positions=3)
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(ValueError, '事后补记'):
                tracker.record_signal(out, self.signal(panel, c, day=str(panel.dates[30])), c)
            with self.assertRaisesRegex(ValueError, '闸门没开'):
                tracker.record_signal(out, self.signal(panel, c, z=0.0), c)
            record = tracker.record_signal(out, self.signal(panel, c), c)
            self.assertEqual(record['signal_date'], str(panel.dates[-1]))
            with self.assertRaisesRegex(ValueError, '已经记录'):
                tracker.record_signal(out, self.signal(panel, c), c)
            data = tracker.load_ledger(out)
            self.assertEqual(data['config_hash'], c.hash())
            self.assertEqual(data['records'][0]['status'], 'waiting')
            self.assertEqual(len(data['records'][0]['picks']), 6)
            # 数据往后走 30 天，记录日是旧面板的最后一天
            longer = make_panel(np.vstack([np.full((60, 8), 10.0), np.full((30, 8), 11.0)]))
            res = tracker.settle_ledger(out, longer)
            rec = res['records'][0]
            self.assertEqual(rec['status'], 'closed')
            self.assertEqual(rec['result']['n_filled'], 3)
            self.assertEqual(sum(1 for r in rec['result']['rows'] if r['in_plan']), 3)
            self.assertGreater(rec['result']['mean_ret'], 0)
            self.assertFalse(res['summary']['enough'])
            # 完成的记录已写回，数据换了也不改写
            self.assertEqual(tracker.load_ledger(out)['records'][0]['status'], 'closed')
            other = replace(c, leverage=2.0)
            with self.assertRaisesRegex(ValueError, '参数已冻结'):
                tracker.record_signal(out, self.signal(longer, other), other)
            tracker.clear_ledger(out)
            self.assertEqual(tracker.load_ledger(out)['records'], [])

    def test_forward_portfolio_uses_frozen_config(self):
        panel = make_panel(np.full((60, 8), 10.0))
        c = cfg(positions=3, leverage=2.0)
        with tempfile.TemporaryDirectory() as out:
            self.assertIsNone(tracker.forward_portfolio(out, panel))
            tracker.record_signal(out, self.signal(panel, c), c)
            self.assertIsNone(tracker.forward_portfolio(out, panel))      # 记录日就是最新一天：还没有后续行情
            longer = make_panel(np.vstack([np.full((60, 8), 10.0), np.full((30, 8), 10.0)]))
            fwd = tracker.forward_portfolio(out, longer)
            self.assertEqual(fwd['start_date'], str(panel.dates[-1]))
            self.assertEqual(len(fwd['dates']), 31)          # 从记录日到面板末尾
            self.assertEqual(len(fwd['equity']), 31)
            self.assertEqual(fwd['mismatched'], [])         # 平稳面板没有真实信号，也没有对不上的

class PanelTests(unittest.TestCase):
    def write_lake(self, root, n_days=300, codes=('sh_600000', 'sz_000001', 'sz_300001')):
        import pyarrow as pa
        import pyarrow.parquet as pq
        q = Path(root) / 'qfq'
        s = Path(root) / 'status'
        q.mkdir()
        s.mkdir()
        days = np.busday_offset(np.datetime64('2022-01-03'), np.arange(n_days), roll='forward')
        for k, code in enumerate(codes):
            px = 10 + k + np.sin(np.arange(n_days) / 5)
            pq.write_table(pa.table({'date': pa.array(days, pa.date32()), 'code': [code.replace('_', '.')] * n_days, 'open': px,
                                     'high': px, 'low': px, 'close': px, 'volume': px * 0 + 1e6, 'amount': px * 0 + 1e8,
                                     'factor': px * 0 + 1.0}), q / f'{code}.parquet')
            pq.write_table(pa.table({'date': pa.array([str(d) for d in days]), 'code': [code] * n_days,
                                     'tradestatus': ['1'] * n_days, 'isST': ['1' if k == 2 else '0'] * n_days}),
                           s / f'{code}.parquet')
        (q / '._junk.parquet').write_bytes(b'x')
        return q, s

    def test_build_and_cache(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(panel_mod, 'MIN_STOCKS_PER_DAY', 2):
            q, s = self.write_lake(root)
            p = panel_mod.build_panel(q, s, start='2022-01-01')
            self.assertEqual(p.shape, (300, 3))
            self.assertEqual(list(p.codes), ['sh.600000', 'sz.000001', 'sz.300001'])
            self.assertTrue(p.st[:, 2].all() and not p.st[:, 0].any())
            self.assertTrue((p.ts == 1).all())
            self.assertAlmostEqual(float(p.c[0, 0]), 10.0, places=4)
            out = Path(root) / 'out'
            with mock.patch.object(panel_mod, 'ready_dirs', return_value=(q, s)):
                first = panel_mod.load_panel(out)
                self.assertTrue((panel_mod.cache_dir(out) / 'panel.npz').is_file())
                with mock.patch.object(panel_mod, 'build_panel', side_effect=AssertionError('should use cache')):
                    again = panel_mod.load_panel(out)
                self.assertEqual(again.shape, first.shape)
                (q / 'sh_600000.parquet').write_bytes((q / 'sh_600000.parquet').read_bytes() + b'\0')   # 源数据变了
                with self.assertRaises(AssertionError):
                    with mock.patch.object(panel_mod, 'build_panel', side_effect=AssertionError('rebuild')):
                        panel_mod.load_panel(out)

    def test_progress_cancel_and_missing_status(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(panel_mod, 'MIN_STOCKS_PER_DAY', 2):
            q, s = self.write_lake(root)
            stop = threading.Event()
            stop.set()
            with self.assertRaises(Cancelled):
                panel_mod.build_panel(q, s, stop=stop)
            for f in s.glob('*.parquet'):
                f.unlink()
            with self.assertRaisesRegex(DipDataError, '日状态'):
                panel_mod.build_panel(q, s)

    def test_not_ready_catalog_fails_closed(self):
        with self.assertRaises(DipDataError):
            panel_mod.ready_dirs('/nonexistent/catalog.md')


if __name__ == '__main__':
    unittest.main()
