"""日内做T page over a small temporary gst_intraday-shaped DuckDB (offscreen Qt)."""
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from test_intraday_t0 import MINUTES


def build_walk_db(root: Path) -> Path:
    import duckdb
    path = root / 'gst_intraday.duckdb'
    conn = duckdb.connect(str(path))
    conn.execute('create table stocks (symbol varchar, name varchar, tick_days bigint, tick_from date, tick_to date,'
                 ' quote_days bigint, quote_from date, quote_to date)')
    conn.execute('create table stock_days (symbol varchar, date date, prev_close double, close double, volume hugeint,'
                 ' amount double, ref_close double, usable_ticks boolean, usable_quotes boolean)')
    conn.execute('create table bars_1m (symbol varchar, date date, minute varchar, open double, high double,'
                 ' low double, close double, volume hugeint, amount double, vwap double, ticks bigint,'
                 ' buy_volume hugeint, sell_volume hugeint)')
    conn.execute('create table ticks (symbol varchar, date date, seq bigint, time varchar, price double,'
                 ' volume bigint, amount double, side varchar)')
    rng = np.random.default_rng(3)
    days = ['2022-12-29', '2022-12-30', '2023-01-03', '2023-01-04']
    rows = []
    for symbol, name in (('sh.600352', '浙江龙盛'), ('sz.300033', '同花顺')):
        conn.execute('insert into stocks values (?,?,?,?,?,0,null,null)', [symbol, name, len(days), days[0], days[-1]])
        prev = 10.0
        for day in days:
            closes = prev * np.exp(np.cumsum(rng.normal(0, 0.003, len(MINUTES))))
            opens = np.r_[prev, closes[:-1]]
            for m, o, c in zip(MINUTES, opens, closes):
                rows.append([symbol, day, m, o, max(o, c), min(o, c), c, 50_000, c * 50_000, c, 10, 30_000, 20_000])
            conn.execute('insert into stock_days values (?,?,?,?,1,1,?,true,false)', [symbol, day, prev, closes[-1], prev])
            prev = float(closes[-1])
    conn.executemany('insert into bars_1m values (?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    conn.close()
    return path


def catalog(root: Path, db: Path, status='READY') -> Path:
    path = root / f'catalog-{status}.md'
    path.write_text('# DATA → CODE 数据清单\n\n## 3. 可供 CODE 使用的数据（READY）\n\n'
                    '| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |\n'
                    '|---|---|---|---|---|---|---|---|\n'
                    f'| `gst_intraday` | DATABASE | 日内 | `{db}` | duckdb | 回测 | `{status}` | 只读 |\n',
                    encoding='utf-8')
    return path


@unittest.skipUnless(__import__('importlib').util.find_spec('PyQt6'), 'Install desktop dependency')
class IntradayPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = build_walk_db(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def wait(self, window, until=None):
        from PyQt6.QtTest import QTest
        for _ in range(250):
            QTest.qWait(20)
            if not window.callbacks and (until is None or until()):
                break

    def window(self, status='READY'):
        from quantlab.desktop.app import MainWindow
        window = MainWindow(self.root / 'out')
        window.data_catalog_path = catalog(self.root, self.db, status)
        window.show()
        self.addCleanup(lambda: (getattr(window, 'intraday_reader', None) and window.intraday_reader.close(),
                                 window.close()))
        return window

    def texts(self, window):
        from PyQt6.QtWidgets import QLabel
        return [w.text() for w in window.scroll.widget().findChildren(QLabel)]

    def test_not_ready_shows_why(self):
        window = self.window('REVIEW_REQUIRED')
        window.navigate_page('intraday')
        self.wait(window)
        self.assertTrue(any('尚未开放日内数据库' in t for t in self.texts(window)))
        self.assertIsNone(getattr(window, 'intraday_reader', None))

    def test_backtest_results_saved_runs_and_replay(self):
        from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QPushButton, QTableWidget
        from quantlab.desktop.intraday_page import IntradayChart
        window = self.window()
        window.navigate_page('intraday')
        self.wait(window)
        self.assertTrue(any('2 只股票' in t for t in self.texts(window)))
        page = window.scroll.widget()
        combos = {c.accessibleName(): c for c in page.findChildren(QComboBox)}
        combos['策略'].setCurrentIndex(combos['策略'].findData('vwap_reversion'))
        combos['费用'].setCurrentIndex(combos['费用'].findData('none'))
        self.assertEqual(combos['股票范围'].count(), 3)
        k = next(s for s in page.findChildren(QDoubleSpinBox) if s.minimum() == 1.0 and s.maximum() == 4.0)
        k.setValue(1.0)  # loose band so the random walk trades
        run = next(b for b in page.findChildren(QPushButton) if b.text() == '开始回测')
        run.click()
        self.wait(window, lambda: window.intraday_state['running'] is None and window.intraday_state['result'])
        result = window.intraday_state['result']
        self.assertEqual(result['strategy'], 'vwap_reversion')
        self.assertEqual(result['params']['k'], 1.0)
        self.assertEqual(result['config']['costs']['slippage'], 0)
        self.assertEqual(result['summary']['train']['days'], 4)  # 2 stocks x 2 days up to 2022-12-31
        self.assertGreater(result['summary']['all']['trips'], 0)
        self.assertNotIn('days', result)
        self.assertTrue((self.root / 'out' / '_intraday' / 'runs' / f"{result['run_id']}.json").is_file())
        self.wait(window)
        page = window.scroll.widget()
        grids = page.findChildren(QTableWidget)
        trips_grid = next(g for g in grids if g.horizontalHeaderItem(0).text() == '日期')
        self.assertEqual(trips_grid.rowCount(), len(result['trips']))
        saved = next(c for c in page.findChildren(QComboBox) if c.accessibleName() == '已保存的回测')
        self.assertEqual(saved.count(), 1)
        # double-click the newest trip → replay tab shows that day with its marks
        trips_grid.cellDoubleClicked.emit(0, 0)
        newest = result['trips'][-1]
        chart = page.findChild(IntradayChart)
        self.wait(window, lambda: chart.day is not None and chart.day.date.isoformat() == newest['date'])
        self.assertEqual((chart.day.symbol, chart.day.date.isoformat()), (newest['symbol'], newest['date']))
        self.assertIn(newest, chart.trips)
        chart.grab()  # paints without error
        # simulate the current strategy on the shown day
        simulate = next(b for b in page.findChildren(QPushButton) if b.text().startswith('用上面设置的策略'))
        chart.trips = None
        simulate.click()
        self.wait(window, lambda: chart.trips is not None)
        self.assertEqual(chart.trips, [t for t in result['trips']
                                       if t['symbol'] == newest['symbol'] and t['date'] == newest['date']])
        # rebuilding the page keeps the result and the replayed day
        window.navigate_page('market')
        self.wait(window)
        window.navigate_page('intraday')
        self.wait(window)
        chart = window.scroll.widget().findChild(IntradayChart)
        self.wait(window, lambda: chart.day is not None)
        self.assertEqual(chart.day.date.isoformat(), newest['date'])

    def test_database_error_stays_on_the_page(self):
        window = self.window()
        self.db.unlink()
        window.navigate_page('intraday')
        self.wait(window)
        self.assertTrue(any('日内数据库打不开' in t for t in self.texts(window)))


if __name__ == '__main__':
    unittest.main()
