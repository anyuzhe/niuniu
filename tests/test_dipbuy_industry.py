"""行业恐慌（只看信号）：申万分类读取、行业分、触发行业里的候选、回测入口、独立的前向记录。全部用合成数据。"""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from quantlab.dipbuy import industry, tracker
from quantlab.dipbuy.engine import DipConfig
from quantlab.dipbuy.panel import DipDataError, Panel

ND, PER = 420, 12          # 420 个交易日（上市满 250 日 + 60 日波动窗口之后才打分），3 个行业各 12 只


def make_dates(n, start='2024-01-02'):
    return np.busday_offset(np.datetime64(start), np.arange(n), roll='forward').astype(str).astype('<U10')


def make_panel(prices):
    prices = np.asarray(prices, np.float32)
    nd, nc = prices.shape
    o = np.vstack([prices[:1], prices[:-1]])
    return Panel(dates=make_dates(nd), codes=np.array([f'sh.6{i:05d}' for i in range(nc)]), o=o.copy(), c=prices.copy(),
                 f=np.ones((nd, nc), np.float32), a=np.full((nd, nc), 1e8, np.float32), st=np.zeros((nd, nc), bool),
                 ts=np.ones((nd, nc), np.int8), meta={'signature': 'x'})


def sector_panel(drop_from, drop_days=20, recover_days=0):
    """行业 A（前 12 只）从 drop_from 起每天跌 1.5%，第 j 只再多跌 0.05% x j（所以 j 越大跌得越多）；B、C 平稳。"""
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.003, (ND, 3 * PER))
    for j in range(PER):
        r[drop_from:drop_from + drop_days, j] = -0.015 - 0.0005 * j
        if recover_days:
            r[drop_from + drop_days:drop_from + drop_days + recover_days, j] = 0.01
    return make_panel(10 * np.cumprod(1 + r, axis=0))


def write_class(directory, panel, *, extra_old=True):
    import pandas as pd
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for j, code in enumerate(panel.codes):
        sym = str(code).split('.')[-1]
        l1 = ('110000', '220000', '230000')[j // PER]
        if extra_old:
            rows.append(dict(code=sym, start_date='2000-01-01', l1_code='999999'))     # 旧分类，应被更新的覆盖
        rows.append(dict(code=sym, start_date='2014-01-01', l1_code=l1))
    pd.DataFrame(rows).to_parquet(directory / '2026-09-23.parquet')
    (directory / '_receipts').mkdir(exist_ok=True)
    (directory / '_receipts' / 'x.json').write_text('{}')
    (directory / '2026-01-01.parquet').write_bytes(b'not used because an older file name')   # 更早的文件名不会被选中


class ClassificationTests(unittest.TestCase):
    def test_loads_latest_file_and_latest_record_per_stock(self):
        panel = sector_panel(300)
        with tempfile.TemporaryDirectory() as d:
            write_class(d, panel)
            cls = industry.load_classification(d, panel.codes)
        self.assertEqual(cls.as_of, '2026-09-23')
        self.assertEqual(cls.codes, ['110000', '220000', '230000'])
        self.assertEqual(cls.names, ['农林牧渔', '基础化工', '钢铁'])
        self.assertEqual(cls.sizes, [PER] * 3)
        self.assertEqual(cls.n_mapped, 3 * PER)
        self.assertEqual(cls.name_of(0), '农林牧渔')

    def test_refuses_when_most_stocks_do_not_map(self):
        panel = sector_panel(300)
        import pandas as pd
        with tempfile.TemporaryDirectory() as d:
            pd.DataFrame([dict(code='600000', start_date='2014-01-01', l1_code='110000')]).to_parquet(Path(d) / '2026-09-23.parquet')
            with self.assertRaisesRegex(DipDataError, '对得上'):
                industry.load_classification(d, panel.codes)

    def test_empty_directory_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(DipDataError, '没有行业分类文件'):
                industry.load_classification(d, np.array(['sh.600000']))


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.panel = sector_panel(ND - 20)           # 最后 20 天行业 A 一起下跌
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        write_class(self.tmp.name, self.panel)
        self.cls = industry.load_classification(self.tmp.name, self.panel.codes)
        self.cfg = industry.default_config()

    def test_only_the_panicked_industry_triggers_and_picks_are_ranked_by_drop(self):
        sig = industry.latest_industry_signal(self.panel, self.cfg, self.cls)
        self.assertTrue(sig['gate_open'])
        self.assertEqual(sig['triggered'], ['农林牧渔'])
        self.assertEqual(sig['industries'][0]['name'], '农林牧渔')
        self.assertTrue(sig['industries'][0]['triggered'])
        self.assertFalse(any(r['triggered'] for r in sig['industries'][1:]))
        self.assertLess(sig['industries'][0]['z'], -1.5)
        self.assertEqual(len(sig['picks']), PER)                       # 只有触发行业里的 12 只
        self.assertTrue(all(p['industry'] == '农林牧渔' for p in sig['picks']))
        rets = [p['ret20'] for p in sig['picks']]
        self.assertEqual(rets, sorted(rets))                           # 跌得最多的在前
        self.assertEqual(sig['picks'][0]['code'], str(self.panel.codes[PER - 1]))
        self.assertEqual(sig['n_e6'], PER)
        self.assertEqual(sig['z'], sig['industries'][0]['z'])          # 引擎里的 z = 当天最弱行业的分
        self.assertIsNotNone(sig['market_z'])

    def test_calm_day_has_no_trigger_and_no_picks(self):
        day = str(self.panel.dates[ND - 60])
        sig = industry.latest_industry_signal(self.panel, self.cfg, self.cls, day=day)
        self.assertFalse(sig['gate_open'])
        self.assertEqual(sig['triggered'], [])
        self.assertEqual(sig['picks'], [])

    def test_threshold_is_respected(self):
        strict = DipConfig(leverage=1.0, z_threshold=-4.0)
        sig = industry.latest_industry_signal(self.panel, strict, self.cls)
        z = sig['industries'][0]['z']
        self.assertEqual(sig['gate_open'], z <= -4.0)

    def test_small_industry_is_not_scored(self):
        panel = sector_panel(ND - 20)
        panel.ts[:, 5:PER] = 0                      # 行业 A 只剩 5 只能交易，不够 8 只
        market_cls = industry.load_classification(self.tmp.name, panel.codes)
        sig = industry.latest_industry_signal(panel, self.cfg, market_cls)
        a = next(r for r in sig['industries'] if r['name'] == '农林牧渔')
        self.assertIsNone(a['z'])
        self.assertFalse(sig['gate_open'])


class BacktestAndLedgerTests(unittest.TestCase):
    def setUp(self):
        self.panel = sector_panel(330, drop_days=20, recover_days=30)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        write_class(self.tmp.name, self.panel)
        self.cls = industry.load_classification(self.tmp.name, self.panel.codes)
        self.cfg = DipConfig(leverage=1.0, positions=5, hold_days=10, start='2024-01-02')

    def test_backtest_only_trades_the_triggered_industry(self):
        run = industry.run_backtest(self.panel, self.cfg, self.cls)
        self.assertEqual(run['kind'], 'industry')
        self.assertEqual(run['classification']['n_industries'], 3)
        trades = run['trades']
        self.assertGreater(len(trades), 0)
        in_a = {str(c) for c in self.panel.codes[:PER]}
        self.assertTrue(all(t['code'] in in_a for t in trades))
        self.assertGreater(run['summary']['gate_days'], 0)
        self.assertTrue(any('今天的申万一级分类' in c for c in run['caveats']))

    def test_industry_ledger_is_separate_from_the_market_ledger(self):
        # 记录只能记最新一天：面板往前截断到信号日（下跌第 20 天，行业 A 已经触发）
        n = 350
        cut = Panel(dates=self.panel.dates[:n], codes=self.panel.codes, o=self.panel.o[:n], c=self.panel.c[:n],
                    f=self.panel.f[:n], a=self.panel.a[:n], st=self.panel.st[:n], ts=self.panel.ts[:n], meta={})
        sig = industry.latest_industry_signal(cut, self.cfg, self.cls)
        with tempfile.TemporaryDirectory() as out:
            self.assertTrue(sig['gate_open'])
            record = tracker.record_signal(out, sig, self.cfg, kind='industry')
            self.assertEqual(record['industries'], ['农林牧渔'])
            self.assertEqual({p['industry'] for p in record['picks']}, {'农林牧渔'})
            self.assertTrue((Path(out) / '_home' / 'dip_industry_forward.json').is_file())
            self.assertFalse((Path(out) / '_home' / 'dip_forward.json').exists())
            self.assertEqual(tracker.load_ledger(out)['records'], [])                   # 大盘恐慌的记录不受影响
            with self.assertRaisesRegex(ValueError, '已经记录'):
                tracker.record_signal(out, sig, self.cfg, kind='industry')
            fwd = tracker.settle_ledger(out, self.panel, kind='industry')
            self.assertEqual(len(fwd['records']), 1)
            port = tracker.forward_portfolio(out, self.panel, kind='industry',
                                             features=lambda c: industry.build_inputs(self.panel, c, self.cls)[:2])
            self.assertEqual(port['start_date'], record['signal_date'])
            tracker.clear_ledger(out, 'industry')
            self.assertEqual(tracker.load_ledger(out, 'industry')['records'], [])

    def test_no_trigger_cannot_be_recorded(self):
        n = 300
        cut = Panel(dates=self.panel.dates[:n], codes=self.panel.codes, o=self.panel.o[:n], c=self.panel.c[:n],
                    f=self.panel.f[:n], a=self.panel.a[:n], st=self.panel.st[:n], ts=self.panel.ts[:n], meta={})
        sig = industry.latest_industry_signal(cut, self.cfg, self.cls)
        self.assertFalse(sig['gate_open'])
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(ValueError, '没有行业触发'):
                tracker.record_signal(out, sig, self.cfg, kind='industry')

    def test_unknown_ledger_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            tracker.load_ledger('/tmp/x', 'bogus')


if __name__ == '__main__':
    unittest.main()
