"""Daily market overview over a synthetic lake in DATA's real file formats."""
import os
import tempfile
import unittest
import unittest.mock
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from quantlab.agent.market_overview_cli import main as cli_main
from quantlab.trading.market_overview import (MarketOverviewError, build_market_overview, latest_overview,
                                              save_overview)

SESSIONS = 40


def _sessions():
    days, day = [], date(2026, 7, 1)
    while len(days) < SESSIONS:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _catalog(root, rows):
    lines = ['# DATA → CODE 数据清单', '', '## 3. 可供 CODE 使用的数据（READY）', '',
             '| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |',
             '|---|---|---|---|---|---|---|---|']
    for dataset_id, path in rows:
        lines.append(f'| `{dataset_id}` | FILE | x | `{path}` | x | x | `READY` | x |')
    lines += ['', '## 4. 尚不可用、待审查或只供 DATA 内部使用', '']
    path = root / 'catalog.md'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


class MarketOverviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.days = _sessions()
        lake = self.root / 'lake'
        qfq, status = lake / 'qfq', lake / 'status'
        pool, margin, ref = lake / 'pool', lake / 'margin', lake / 'ref'
        for d in (qfq, status, pool, margin, ref):
            d.mkdir(parents=True)
        # Four main-board stocks in two industries. A: limit-up on the last two days (2 连板);
        # B: limit-down on the last day; C, D drift. An ex-rights factor change on C must not
        # be counted as a drop because returns use the adjusted close.
        paths = {'sh.600001': [10.0] * (SESSIONS - 3) + [10.0, 11.0, 12.1],
                 'sh.600002': [20.0] * (SESSIONS - 1) + [18.0],
                 'sz.000003': [5.0 + i * 0.01 for i in range(SESSIONS)],
                 'sz.000004': [8.0 - i * 0.01 for i in range(SESSIONS)]}
        for code, closes in paths.items():
            factor = [0.5 if (code == 'sz.000003' and i < SESSIONS - 5) else 1.0 for i in range(SESSIONS)]
            qfq_close = closes
            pl.DataFrame({'date': self.days, 'code': [code] * SESSIONS,
                          'open': qfq_close, 'high': qfq_close, 'low': qfq_close, 'close': qfq_close,
                          'volume': [1000] * SESSIONS, 'amount': [1e8] * SESSIONS, 'factor': factor}
                         ).write_parquet(qfq / f"{code.replace('.', '_')}.parquet")
            pl.DataFrame({'date': [d.isoformat() for d in self.days], 'code': [code] * SESSIONS,
                          'tradestatus': ['1'] * SESSIONS, 'isST': ['0'] * SESSIONS, 'fetch_ts': ['x'] * SESSIONS}
                         ).write_parquet(status / f"{code.replace('.', '_')}.parquet")
        last = self.days[-1]
        pl.DataFrame({'date': [last], 'code': ['600001'], 'name': ['甲股份'], 'reason': ['机器人+AI应用'],
                      'high_days': ['2天2板'], 'board_type': ['换手板']}).write_parquet(pool / f'{last}.parquet')
        for i, d in enumerate(self.days[-2:]):
            pl.DataFrame({'date': [d.isoformat()], 'margin_balance': [1e11 + i * 1e9]}).write_parquet(
                margin / f'{d}.parquet')
        calendar = [(self.days[0] + timedelta(days=i)) for i in range((last - self.days[0]).days + 1)]
        pl.DataFrame({'calendar_date': [d.isoformat() for d in calendar],
                      'is_trading_day': ['1' if d in self.days else '0' for d in calendar]}
                     ).write_parquet(ref / 'trade_calendar.parquet')
        pl.DataFrame({'code': list(paths), 'code_name': ['甲股份', '乙股份', '丙股份', '丁股份'],
                      'ipoDate': ['2000-01-01'] * 4, 'outDate': [''] * 4, 'type': ['1'] * 4, 'status': ['1'] * 4}
                     ).write_parquet(ref / 'stock_basic.parquet')
        pl.DataFrame({'updateDate': ['2026-09-21'] * 4, 'code': list(paths), 'code_name': ['甲', '乙', '丙', '丁'],
                      'industry': ['C35专用设备制造业', 'C35专用设备制造业', 'J66货币金融服务', 'J66货币金融服务'],
                      'industryClassification': ['证监会行业分类'] * 4}).write_parquet(ref / 'industry.parquet')
        self.catalog = _catalog(self.root, [
            ('qfq_published_f24', qfq), ('security_status_baostock_v2', status), ('limit_up_pool_ths', pool),
            ('margin_detail_exchange', margin), ('reference_snapshot_baostock_20260923', ref)])

    def tearDown(self):
        self.temp.cleanup()

    def build(self, **kwargs):
        with unittest.mock.patch('quantlab.trading.market_overview.MIN_INDUSTRY_MEMBERS', 1):
            return build_market_overview(self.catalog, **kwargs)

    def test_market_facts_ladder_and_percentiles(self):
        overview = self.build()
        self.assertEqual(overview['trading_day'], self.days[-1].isoformat())
        market = overview['market']
        self.assertEqual((market['limit_up'], market['limit_down']), (1, 1))
        self.assertEqual(market['max_streak'], 2)
        # C's factor jump is an ex-rights adjustment, not a fall: only B and D are down.
        self.assertEqual((market['up'], market['down']), (2, 2))
        self.assertEqual(overview['ladder'][0]['code'], 'sh.600001')
        self.assertEqual(overview['ladder'][0]['reason'], '机器人+AI应用')
        self.assertEqual(overview['percentile_window_sessions'], SESSIONS - 1 - 20 - 1 + 1)
        self.assertAlmostEqual(market['prev_limit_up_avg_pct'], 0.1, places=6)
        self.assertEqual(overview['margin']['change'], 1e9)
        self.assertTrue(any('上涨 2 家' in line for line in overview['summary']))

    def test_directions_and_reasons(self):
        overview = self.build()
        names = [r['industry'] for r in overview['industries']]
        self.assertEqual(set(names), {'专用设备制造业', '货币金融服务'})
        top = overview['industries'][0]
        self.assertIn(top['industry'], names)
        reasons = {r['reason']: r for r in overview['reasons']}
        self.assertEqual(reasons['机器人']['limit_ups'], 1)
        self.assertEqual(reasons['AI应用']['stocks'][0]['code'], 'sh.600001')

    def test_explicit_day_beyond_data_is_refused_and_save_roundtrip(self):
        future = self.days[-1] + timedelta(days=1)
        with self.assertRaisesRegex(MarketOverviewError, '还没有'):
            self.build(trading_day=future.isoformat())
        overview = self.build(trading_day=self.days[-2].isoformat())
        self.assertEqual(overview['trading_day'], self.days[-2].isoformat())
        out = self.root / 'artifacts'
        save_overview(out, overview)
        self.assertEqual(latest_overview(out)['trading_day'], self.days[-2].isoformat())

    def test_not_ready_input_is_reported_not_substituted(self):
        text = self.catalog.read_text(encoding='utf-8').replace(
            '| `qfq_published_f24` | FILE | x |', '| `qfq_published_f24` | FILE | x |', 1)
        self.catalog.write_text(text.replace("`READY` | x |\n| `security_status", "`NOT_READY` | x |\n| `security_status", 1),
                                encoding='utf-8')
        with self.assertRaisesRegex(MarketOverviewError, '尚未交付 qfq_published_f24'):
            self.build()

    def test_cli_builds_and_shows(self):
        out = self.root / 'artifacts'
        with unittest.mock.patch('quantlab.trading.market_overview.MIN_INDUSTRY_MEMBERS', 1):
            self.assertEqual(cli_main(['--output', str(out), '--data-catalog', str(self.catalog)]), 0)
        self.assertEqual(cli_main(['--output', str(out), '--show']), 0)
        self.assertEqual(cli_main(['--output', str(self.root / 'empty'), '--show']), 2)


@unittest.skipUnless(__import__('importlib').util.find_spec('PyQt6'), 'Install desktop dependency')
class MarketPagesDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_pages_render_saved_overview_without_data_root(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QLabel, QTableWidget
        from quantlab.desktop.app import MainWindow
        case = MarketOverviewTests('test_cli_builds_and_shows')
        case.setUp()
        try:
            out = case.root / 'artifacts'
            save_overview(out, case.build())
            window = MainWindow(out)
            window.show()
            QTest.qWait(30)
            texts = [w.text() for w in window.scroll.widget().findChildren(QLabel)]
            self.assertTrue(any('数据截至' in t for t in texts))
            self.assertTrue(any('涨停 1 家' in t for t in texts))
            window.navigate_page('themes')
            QTest.qWait(30)
            tables = window.scroll.widget().findChildren(QTableWidget)
            self.assertEqual(tables[0].rowCount(), 2)
            self.assertFalse(window._overview_building if hasattr(window, '_overview_building') else False)
            window.close()
        finally:
            case.tearDown()


if __name__ == '__main__':
    unittest.main()
