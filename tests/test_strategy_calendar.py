"""策略工作台收益日历：日 / 月 / 年收益的算法，控件的年历 ⇄ 月历切换、翻页，以及接进回测结果页。"""
import math
import os
import sys
import unittest
from importlib.util import find_spec

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(__file__))

if find_spec('PyQt6'):
    from PyQt6.QtWidgets import QApplication
    from quantlab.desktop.strategy_calendar import CalendarCard, calendar_stats

DATES = ['2024-12-30', '2024-12-31', '2025-01-02', '2025-01-03', '2025-02-03', '2025-02-04', '2025-03-03']
EQUITY = [1.0, 1.10, 1.21, 1.089, 1.2, 1.32, 1.188]


class CalendarStatsTests(unittest.TestCase):
    def test_daily_monthly_yearly_returns(self):
        s = calendar_stats(DATES, EQUITY)
        self.assertNotIn('2024-12-30', s['daily'])
        self.assertAlmostEqual(s['daily']['2024-12-31'], 0.10)
        self.assertAlmostEqual(s['daily']['2025-01-03'], -0.10)
        self.assertAlmostEqual(s['monthly'][(2024, 12)], 0.10)
        self.assertAlmostEqual(s['monthly'][(2025, 1)], 1.089 / 1.10 - 1)
        self.assertAlmostEqual(s['monthly'][(2025, 2)], 1.32 / 1.089 - 1)
        self.assertAlmostEqual(s['monthly'][(2025, 3)], 1.188 / 1.32 - 1)
        self.assertAlmostEqual(s['yearly'][2024], 0.10)
        self.assertAlmostEqual(s['yearly'][2025], 1.188 / 1.10 - 1)

    def test_missing_values_are_skipped_and_empty_curve_is_safe(self):
        s = calendar_stats(['2025-01-02', '2025-01-03', '2025-01-06'], [1.0, None, 1.2])
        self.assertEqual(list(s['daily']), ['2025-01-06'])
        self.assertAlmostEqual(s['daily']['2025-01-06'], 0.2)
        self.assertAlmostEqual(s['monthly'][(2025, 1)], 0.2)
        e = calendar_stats([], [])
        self.assertEqual((e['daily'], e['monthly'], e['yearly']), ({}, {}, {}))
        nan = calendar_stats(['2025-01-02'], [math.nan])
        self.assertEqual(nan['monthly'], {})


@unittest.skipUnless(find_spec('PyQt6'), 'PyQt6 not installed')
class CalendarCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_year_month_switch_paging_and_benchmark(self):
        card = CalendarCard(DATES, EQUITY, [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.9])
        card.resize(700, 600)
        self.assertEqual((card.view, card.year, card.month), ('year', 2025, 3))
        self.assertIn('2025 年收益：+8.0%', card.summary.text())
        self.assertIn('等权大盘', card.summary.text())
        card.step(-1)
        self.assertEqual(card.year, 2024)
        self.assertIn('2024 年收益：+10.0%', card.summary.text())
        card.step(-5)
        self.assertEqual(card.year, 2024)
        card.pick_month(12)
        self.assertEqual((card.view, card.year, card.month), ('month', 2024, 12))
        self.assertEqual(card.period.text(), '2024 年 12 月')
        self.assertIn('12 月累计收益：+10.0%', card.summary.text())
        card.step(1)
        self.assertEqual((card.year, card.month), (2025, 1))
        card.step(100)
        self.assertEqual((card.year, card.month), (2025, 3))
        card.chart.grab()
        card.set_view('year')
        card.chart.grab()
        self.assertEqual(len(card.chart._cells), 12)

    def test_empty_curve_shows_placeholder(self):
        card = CalendarCard([], [])
        card.chart.grab()
        self.assertEqual(card.period.text(), '暂无数据')


if __name__ == '__main__':
    unittest.main()
