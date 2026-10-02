"""策略工作台页面（离屏）：用缓存好的合成面板走一遍四个标签、沙盒回测、前向记录。"""
import json
import os
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

if find_spec('PyQt6'):
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QDoubleSpinBox, QLabel, QPushButton, QSpinBox, QTableWidget, QTabWidget
    from quantlab.desktop.app import MainWindow
    from quantlab.desktop import strategy_bench_page as page_mod
from quantlab.dipbuy import panel as dpanel
from test_dipbuy import make_panel


def crash_panel():
    """30 只股票，最后 20 天一起下滑（闸门打开），最后一天有 10 只“跌破下轨后收复”。"""
    nd, nc = 340, 30
    base = 10 + 0.05 * np.sin(np.arange(nd))
    p = np.tile(base[:, None], (1, nc)) * (1 + 0.003 * np.arange(nc))[None, :]
    slide = np.ones(nd)
    for i in range(320, nd):
        slide[i] = slide[i - 1] * 0.99
    p = p * slide[:, None]
    p[nd - 2, :10] *= 0.93
    p[nd - 1, :10] = p[nd - 2, :10] * 1.035
    panel = make_panel(p)
    panel.o[nd - 1, :10] = p[nd - 2, :10] * 0.995
    return panel


def wait(window, until=None, seconds=20):
    import time
    end = time.monotonic() + seconds
    QTest.qWait(30)
    while time.monotonic() < end and (window.callbacks or (until and not until())):
        QTest.qWait(20)
    QTest.qWait(30)


@unittest.skipUnless(find_spec('PyQt6'), 'PyQt6 not installed')
class BenchPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out = self.root / 'out'
        self.out.mkdir()
        self.fake = self.root / 'lake'
        self.fake.mkdir()
        for target, value in (('quantlab.desktop.strategy_bench_page.is_data_ready', True),
                              ('quantlab.dipbuy.panel.ready_dirs', (self.fake, self.fake)),
                              ('quantlab.dipbuy.panel.source_signature', 'sig'),
                              ('quantlab.dipbuy.panel.load_names', {'sh.600000': '甲股份'})):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = MainWindow(self.out)
        self.window.data_catalog_path = self.root / 'catalog.md'
        self.window.show()

    def tearDown(self):
        wait(self.window)
        self.window.close()
        QTest.qWait(10)
        self.temp.cleanup()

    def cache_panel(self):
        panel = crash_panel()
        panel.meta = {'signature': 'sig', 'first_date': str(panel.dates[0]), 'last_date': panel.last_date}
        panel.save(dpanel.cache_dir(self.out))
        return panel

    def labels(self):
        return [w.text() for w in self.window.scroll.widget().findChildren(QLabel)]

    def button(self, text):
        return next(b for b in self.window.scroll.widget().findChildren(QPushButton) if b.text() == text)

    def go(self):
        self.window.navigate_page('bench')
        wait(self.window, lambda: self.window.bench_state['panel'] is not None)

    def test_first_run_waits_for_a_click_then_loads(self):
        self.window.navigate_page('bench')
        wait(self.window)
        self.assertIsNone(self.window.bench_state['panel'])
        self.assertIn('读取数据并回测', [b.text() for b in self.window.scroll.widget().findChildren(QPushButton)])
        self.cache_panel()
        self.button('读取数据并回测').click()
        wait(self.window, lambda: self.window.bench_state['panel'] is not None)
        self.assertEqual(self.window.bench_state['panel'].shape, (340, 30))
        self.assertTrue(any('数据面板：30 只股票' in t for t in self.labels()))

    def test_four_tabs_signal_and_forward_record(self):
        self.cache_panel()
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['今日信号', '回测与风险', '参数沙盒', '前向跟踪'])
        sig = self.window.bench_state['default']
        self.assertEqual(sig['format'], 'niuniu-dipbuy-run-v1')
        # 今日信号：闸门开，10 只收复，计划里 20 只上限内全部是计划内
        texts = self.labels()
        self.assertTrue(any(t == '开' for t in texts))
        self.assertTrue(any('10 只' == t for t in texts))
        self.assertGreaterEqual(len(tabs.widget(0).findChildren(page_mod.SeriesChart)), 1)
        grid = tabs.widget(0).findChildren(QTableWidget)[-1]
        self.assertEqual(grid.rowCount(), 10)
        self.assertEqual(grid.item(0, 5).text(), '计划内')
        self.assertNotEqual(grid.item(0, 6).text(), '—')
        # 回测与风险：图表能画
        for chart in tabs.widget(1).findChildren(page_mod.SeriesChart) + tabs.widget(1).findChildren(page_mod.BarChart):
            self.assertFalse(chart.grab().isNull())
        self.assertTrue(any('最低担保比例' in t for t in texts))
        # 前向记录：记一条
        self.button('把今天的信号记入前向跟踪').click()
        QTest.qWait(50)
        ledger = json.loads((self.out / '_home' / 'dip_forward.json').read_text(encoding='utf-8'))
        self.assertEqual(len(ledger['records']), 1)
        self.assertEqual(ledger['records'][0]['status'], 'waiting')
        self.assertTrue(any('已记录' in t for t in self.labels()))
        self.assertFalse(self.button('把今天的信号记入前向跟踪').isEnabled())
        self.button('清空记录').click()
        self.assertEqual(self.button('再点一次确认清空').text(), '再点一次确认清空')
        self.button('再点一次确认清空').click()
        QTest.qWait(50)
        self.assertFalse((self.out / '_home' / 'dip_forward.json').exists())

    def test_sandbox_runs_saves_and_compares(self):
        self.cache_panel()
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        tabs.setCurrentIndex(2)
        spins = {w.accessibleName(): w for w in tabs.widget(2).findChildren(QDoubleSpinBox) + tabs.widget(2).findChildren(QSpinBox)}
        spins['杠杆倍数'].setValue(1.0)
        spins['持仓只数'].setValue(5)
        self.button('运行回测').click()
        wait(self.window, lambda: self.window.bench_state['sandbox'] is not None)
        result = self.window.bench_state['sandbox']
        self.assertEqual(result['config']['leverage'], 1.0)
        self.assertEqual(result['config']['positions'], 5)
        saved = list((self.out / '_dipbuy' / 'runs').glob('*.json'))
        self.assertEqual(len(saved), 1)
        self.assertTrue(any('与默认策略对照' in t for t in self.labels()))
        for chart in tabs.widget(2).findChildren(page_mod.SeriesChart):
            self.assertFalse(chart.grab().isNull())

    def test_closed_gate_shows_observation_only_and_blocks_recording(self):
        base = 10 + 0.05 * np.sin(np.arange(340))
        flat = make_panel(np.tile(base[:, None], (1, 12)))
        flat.meta = {'signature': 'sig'}
        flat.save(dpanel.cache_dir(self.out))
        self.go()
        texts = self.labels()
        self.assertTrue(any(t == '关' for t in texts))
        self.assertTrue(any('闸门没开' in t for t in texts))
        self.assertFalse(self.button('把今天的信号记入前向跟踪').isEnabled())
        self.button('把今天的信号记入前向跟踪').click()     # 禁用时点击无效
        self.assertFalse((self.out / '_home' / 'dip_forward.json').exists())

    def test_page_rebuild_keeps_loaded_state(self):
        self.cache_panel()
        self.go()
        panel = self.window.bench_state['panel']
        self.window.navigate_page('market')
        wait(self.window)
        self.window.navigate_page('bench')
        wait(self.window)
        self.assertIs(self.window.bench_state['panel'], panel)
        self.assertTrue(any('数据面板：30 只股票' in t for t in self.labels()))

    def test_not_ready_shows_note_only(self):
        with mock.patch('quantlab.desktop.strategy_bench_page.is_data_ready', return_value=False):
            self.window.navigate_page('bench')
            wait(self.window)
        self.assertTrue(any('数据侧尚未开放' in t for t in self.labels()))
        self.assertFalse(hasattr(self.window, 'bench_state') and self.window.bench_state['panel'])


if __name__ == '__main__':
    unittest.main()
