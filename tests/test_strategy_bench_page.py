"""策略工作台页面（离屏）：用缓存好的合成面板走一遍八个标签（含行业恐慌、策略 D）、沙盒回测、前向记录。"""
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
    from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QPushButton, QSpinBox, QTableWidget, QTabWidget
    from quantlab.desktop.app import MainWindow
    from quantlab.desktop import strategy_bench_page as page_mod
    from quantlab.desktop.strategy_calendar import CalendarCard
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
        self.sw = self.root / 'sw'
        self.write_sw_classification()
        for target, value in (('quantlab.desktop.strategy_bench_page.is_data_ready', True),
                              ('quantlab.dipbuy.panel.ready_dirs', (self.fake, self.fake)),
                              ('quantlab.dipbuy.panel.source_signature', 'sig'),
                              ('quantlab.dipbuy.industry.industry_dir', self.sw),
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

    def write_sw_classification(self):
        import pandas as pd
        self.sw.mkdir()
        rows = [dict(code=f'60000{i}', start_date='2014-01-01', l1_code=('110000', '220000', '230000')[i // 10 % 3]) for i in range(40)]
        pd.DataFrame(rows).to_parquet(self.sw / '2026-09-23.parquet')

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

    def test_eight_tabs_signal_and_forward_record(self):
        self.cache_panel()
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['今日信号', '回测与风险', '参数沙盒', '前向跟踪', '行业恐慌', '策略 D', '我的持仓', '策略说明'])
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

    def holdings_page(self, plan_day):
        """把“今天”钉在计划日，免得合成面板的 2025 年日期被当成过期数据；返回页面对象列表（最后一个是当前页面）。"""
        pages = []

        def today(page):
            pages.append(page)
            return plan_day
        patcher = mock.patch.object(page_mod.BenchPage, 'today', today)
        patcher.start()
        self.addCleanup(patcher.stop)
        return pages

    def test_holdings_tab_plans_buys_sells_and_keeps_its_own_file(self):
        from quantlab.dipbuy import autorecord
        panel = self.cache_panel()
        plan_day = autorecord.next_open_day(panel.last_date)
        pages = self.holdings_page(plan_day)
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        self.assertEqual(tabs.tabText(6), '我的持仓')
        texts = [w.text() for w in tabs.widget(6).findChildren(QLabel)]
        self.assertTrue(any('明天开盘要买' in t for t in texts))
        self.assertTrue(any('还没有录入持仓' in t for t in texts))
        page = pages[-1]
        self.assertEqual(page.hold_plan['plan_day'], plan_day.isoformat())
        self.assertGreater(len(page.hold_plan['buys']), 0)
        # 手动录入：一只明天到期的、一只早已到期的（合成面板里真实存在的代码只有 600000–600009）
        H = page.hold_plan['hold_days']
        due_day = str(panel.dates[len(panel.dates) - 1 - (H - 2)])
        old_day = str(panel.dates[len(panel.dates) - 1 - (H + 2)])
        for code, day in (('600001', due_day), ('600002', old_day)):
            pages[-1].hold_code.setText(code)
            pages[-1].hold_date.setText(day)
            self.button('添加持仓').click()
            QTest.qWait(30)
        sells = {r['code']: r for r in pages[-1].hold_plan['sells']}
        self.assertEqual(sells['sh.600001']['status'], 'due')
        self.assertEqual(sells['sh.600002']['status'], 'overdue')
        self.assertTrue(any('明天要卖' in t for t in self.labels()))
        self.assertNotIn('sh.600001', [b['code'] for b in pages[-1].hold_plan['buys']])         # 还没卖的不重复买
        pages[-1].hold_code.setText('abc')
        self.button('添加持仓').click()
        self.assertTrue(any('6 位数字' in t for t in self.labels()))
        # 卖完、数据更新后清掉已到期的：只清早已到期的
        self.button('清掉已到期的持仓（卖完、数据更新后点）').click()
        QTest.qWait(30)
        path = self.out / '_home' / 'dip_holdings.json'
        left = {h['code'] for h in json.loads(path.read_text(encoding='utf-8'))['holdings']}
        self.assertEqual(left, {'sh.600001'})
        self.assertTrue(any('已清掉 1 只' in t for t in self.labels()))
        # 买完记为已持有：计划日作为买入日，之后的计划不再出现这些票
        buys = [b for b in pages[-1].hold_plan['buys'] if len(b['code']) == 9]       # 合成面板里 sh.6000010 这类 7 位代码不是真代码，录不进去
        self.assertGreater(len(buys), 0)
        self.button('把这些记为已持有（买完后点）').click()
        QTest.qWait(50)
        saved = json.loads(path.read_text(encoding='utf-8'))['holdings']
        self.assertEqual({h['code'] for h in saved}, {'sh.600001'} | {b['code'] for b in buys})
        self.assertTrue(all(h['entry_date'] == plan_day.isoformat() for h in saved if h['code'] != 'sh.600001'))
        self.assertFalse({h['code'] for h in saved} & {b['code'] for b in pages[-1].hold_plan['buys']})
        self.assertTrue(any('已记入' in t for t in self.labels()))
        self.assertFalse((self.out / '_home' / 'dip_fusion_forward.json').exists())              # 其它记录文件不受影响

    def test_d2_is_a_third_variant_with_its_own_backtest_and_forward_ledger(self):
        from quantlab.dipbuy import autorecord
        panel = self.cache_panel()
        pages = self.holdings_page(autorecord.next_open_day(panel.last_date))
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        selector = next(c for c in tabs.widget(5).findChildren(QComboBox) if c.accessibleName() == '候选排序')
        self.assertEqual([selector.itemData(i) for i in range(selector.count())], ['D', 'D1', 'D2', 'D3', 'D4'])
        selector.setCurrentIndex(2)
        QTest.qWait(50)
        self.assertEqual(self.window.bench_state['fusion_variant'], 'D2')
        page = pages[-1]
        self.assertEqual(page.fus_cfg.variant, 'D2')
        self.assertTrue(page.fus_cfg.near_high_on)
        self.assertTrue(page.hold_ctx[0].near_high_on)                                    # 我的持仓跟着 D2
        texts = [w.text() for w in tabs.widget(5).findChildren(QLabel)]
        self.assertTrue(any('D2 = D1 再加一件事' in t for t in texts))
        self.assertTrue(any('策略 D2 的回测与风险' in t for t in texts))
        self.assertTrue(any('大盘离近 120 日高点' in t for t in texts))
        sig = page.fus_signal
        if sig['gate_open'] and sig['picks']:
            self.button('把今天的信号记入策略 D2 前向跟踪').click()
            QTest.qWait(50)
            ledger = json.loads((self.out / '_home' / 'dip_fusion2_forward.json').read_text(encoding='utf-8'))
            self.assertTrue(ledger['config']['near_high_on'])
            self.assertEqual(ledger['config']['rank_mode'], 'dd60')
            self.assertFalse((self.out / '_home' / 'dip_fusion1_forward.json').exists())     # D1 的台账不受影响
            self.assertFalse((self.out / '_home' / 'dip_fusion_forward.json').exists())
        else:
            self.assertTrue(sig['market_position']['blocked'] or not sig['gate_open'])
        selector = next(c for c in tabs.widget(5).findChildren(QComboBox) if c.accessibleName() == '候选排序')
        selector.setCurrentIndex(0)
        QTest.qWait(50)
        self.assertFalse(pages[-1].fus_cfg.near_high_on)                                  # 切回 D：不带过滤

    def test_d3_is_a_fourth_variant_with_its_own_backtest_and_forward_ledger(self):
        from quantlab.dipbuy import autorecord
        panel = self.cache_panel()
        pages = self.holdings_page(autorecord.next_open_day(panel.last_date))
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        selector = next(c for c in tabs.widget(5).findChildren(QComboBox) if c.accessibleName() == '候选排序')
        self.assertEqual([selector.itemData(i) for i in range(selector.count())], ['D', 'D1', 'D2', 'D3', 'D4'])
        selector.setCurrentIndex(3)
        QTest.qWait(50)
        self.assertEqual(self.window.bench_state['fusion_variant'], 'D3')
        page = pages[-1]
        self.assertEqual(page.fus_cfg.variant, 'D3')
        self.assertEqual(page.fus_cfg.order, ('C', 'A', 'B'))
        self.assertTrue(page.fus_cfg.near_high_on)
        self.assertTrue(page.hold_ctx[0].near_high_on)                                    # 我的持仓跟着 D3
        texts = [w.text() for w in tabs.widget(5).findChildren(QLabel)]
        self.assertTrue(any('D3 = D2 再改一件事' in t for t in texts))
        self.assertTrue(any('策略 D3 的回测与风险' in t for t in texts))
        self.assertTrue(any('大盘离近 120 日高点' in t for t in texts))
        sig = page.fus_signal
        if sig['gate_open'] and sig['picks']:
            self.button('把今天的信号记入策略 D3 前向跟踪').click()
            QTest.qWait(50)
            ledger = json.loads((self.out / '_home' / 'dip_fusion3_forward.json').read_text(encoding='utf-8'))
            self.assertTrue(ledger['config']['near_high_on'])
            self.assertEqual(ledger['config']['rank_mode'], 'dd60')
            self.assertEqual(ledger['config']['priority'], 'CAB')
            self.assertFalse((self.out / '_home' / 'dip_fusion2_forward.json').exists())     # D2 的台账不受影响
            self.assertFalse((self.out / '_home' / 'dip_fusion1_forward.json').exists())     # D1 的台账不受影响
            self.assertFalse((self.out / '_home' / 'dip_fusion_forward.json').exists())
        else:
            self.assertTrue(sig['market_position']['blocked'] or not sig['gate_open'])
        selector = next(c for c in tabs.widget(5).findChildren(QComboBox) if c.accessibleName() == '候选排序')
        selector.setCurrentIndex(0)
        QTest.qWait(50)
        self.assertEqual(pages[-1].fus_cfg.priority, 'ACB')
        self.assertFalse(pages[-1].fus_cfg.near_high_on)                                  # 切回 D：不带过滤

    def test_d4_is_a_fifth_variant_with_blacklist_and_its_own_backtest_and_forward_ledger(self):
        from quantlab.dipbuy import autorecord
        panel = self.cache_panel()
        pages = self.holdings_page(autorecord.next_open_day(panel.last_date))
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        selector = next(c for c in tabs.widget(5).findChildren(QComboBox) if c.accessibleName() == '候选排序')
        self.assertEqual([selector.itemData(i) for i in range(selector.count())], ['D', 'D1', 'D2', 'D3', 'D4'])
        selector.setCurrentIndex(4)
        QTest.qWait(50)
        self.assertEqual(self.window.bench_state['fusion_variant'], 'D4')
        page = pages[-1]
        self.assertEqual(page.fus_cfg.variant, 'D4')
        self.assertEqual(page.fus_cfg.industry_blacklist, ('国防军工', '房地产'))
        self.assertEqual(page.fus_cfg.order, ('C', 'A', 'B'))
        self.assertTrue(page.fus_cfg.near_high_on)
        self.assertTrue(page.hold_ctx[0].near_high_on)                                    # 我的持仓跟着 D4
        texts = [w.text() for w in tabs.widget(5).findChildren(QLabel)]
        self.assertTrue(any('D4 = D3 再加一件事' in t for t in texts))
        self.assertTrue(any('策略 D4 的回测与风险' in t for t in texts))
        self.assertTrue(any('大盘离近 120 日高点' in t for t in texts))
        sig = page.fus_signal
        if sig['gate_open'] and sig['picks']:
            self.button('把今天的信号记入策略 D4 前向跟踪').click()
            QTest.qWait(50)
            ledger = json.loads((self.out / '_home' / 'dip_fusion4_forward.json').read_text(encoding='utf-8'))
            self.assertTrue(ledger['config']['near_high_on'])
            self.assertEqual(ledger['config']['rank_mode'], 'dd60')
            self.assertEqual(ledger['config']['priority'], 'CAB')
            self.assertEqual(ledger['config']['industry_blacklist'], ['国防军工', '房地产'])
            self.assertFalse((self.out / '_home' / 'dip_fusion3_forward.json').exists())     # D3 的台账不受影响
            self.assertFalse((self.out / '_home' / 'dip_fusion1_forward.json').exists())     # D1 的台账不受影响
            self.assertFalse((self.out / '_home' / 'dip_fusion_forward.json').exists())
        else:
            self.assertTrue(sig['market_position']['blocked'] or not sig['gate_open'])
        selector = next(c for c in tabs.widget(5).findChildren(QComboBox) if c.accessibleName() == '候选排序')
        selector.setCurrentIndex(0)
        QTest.qWait(50)
        self.assertEqual(pages[-1].fus_cfg.priority, 'ACB')
        self.assertEqual(pages[-1].fus_cfg.industry_blacklist, ())
        self.assertFalse(pages[-1].fus_cfg.near_high_on)                                  # 切回 D：不带过滤

    def test_holdings_tab_refuses_stale_data_and_saves_equity(self):
        panel = self.cache_panel()
        self.go()                                          # 不钉“今天”：合成面板是 2025 年的，早已过期
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        texts = [w.text() for w in tabs.widget(6).findChildren(QLabel)]
        self.assertTrue(any('先更新数据' in t for t in texts))
        self.assertTrue(any('数据过期' in t for t in texts))
        box = next(b for b in tabs.widget(6).findChildren(QDoubleSpinBox) if b.accessibleName() == '账户总资产')
        box.setValue(88.0)
        box.editingFinished.emit()
        QTest.qWait(30)
        saved = json.loads((self.out / '_home' / 'dip_holdings.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['equity_wan'], 88.0)

    def test_industry_tab_shows_signal_backtest_and_keeps_its_own_ledger(self):
        self.cache_panel()
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        ind = self.window.bench_state['industry']
        self.assertNotIn('error', ind)
        self.assertEqual(ind['run']['kind'], 'industry')
        tab = tabs.widget(4)
        texts = [w.text() for w in tab.findChildren(QLabel)]
        self.assertTrue(any('这是什么' in t or '恐慌分' in t for t in texts))
        grids = tab.findChildren(QTableWidget)
        self.assertEqual(grids[0].rowCount(), 3)                      # 合成面板里只有 3 个行业
        self.assertEqual(grids[0].item(0, 5).text(), '触发')           # 最后 20 天一起下滑：触发
        for chart in tab.findChildren(page_mod.SeriesChart) + tab.findChildren(page_mod.BarChart):
            self.assertFalse(chart.grab().isNull())
        self.button('把今天的信号记入行业前向跟踪').click()
        QTest.qWait(50)
        ledger = json.loads((self.out / '_home' / 'dip_industry_forward.json').read_text(encoding='utf-8'))
        self.assertEqual(len(ledger['records']), 1)
        self.assertTrue(ledger['records'][0]['industries'])
        self.assertFalse((self.out / '_home' / 'dip_forward.json').exists())      # 大盘恐慌的记录不受影响
        self.button('清空行业记录').click()
        self.button('再点一次确认清空').click()
        QTest.qWait(50)
        self.assertFalse((self.out / '_home' / 'dip_industry_forward.json').exists())

    def test_industry_tab_degrades_when_classification_is_missing(self):
        self.cache_panel()
        with mock.patch('quantlab.dipbuy.industry.industry_dir', side_effect=dpanel.DipDataError('数据侧尚未交付 sw_industry_history')):
            self.go()
        self.assertIn('error', self.window.bench_state['industry'])
        self.assertTrue(any('行业恐慌暂不可用' in t for t in self.labels()))
        self.assertIsNotNone(self.window.bench_state['default'])      # 其余标签照常

    def test_fusion_tab_shows_three_layers_records_and_keeps_its_own_ledger(self):
        self.cache_panel()
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        fus = self.window.bench_state['fusion']
        self.assertNotIn('error', fus)
        self.assertEqual(fus['run']['kind'], 'fusion')
        tab = tabs.widget(5)
        texts = [w.text() for w in tab.findChildren(QLabel)]
        self.assertTrue(any('三层恐慌分' in t for t in texts))
        self.assertTrue(any('三层各自的成交' in t for t in texts))
        self.assertFalse(any('最低担保比例' in t for t in texts))               # D 不借钱，没有担保比例
        grids = tab.findChildren(QTableWidget)
        self.assertEqual(grids[0].rowCount(), 5)                               # 成交额五档
        self.assertEqual(grids[0].item(2, 4).text(), '触发')                    # 合成面板里成交额都一样，全落在中间档，最后 20 天一起下滑
        self.assertEqual(grids[1].rowCount(), 3)                               # 三个行业
        self.assertGreater(grids[2].rowCount(), 0)                             # 触发的层有候选
        self.assertIn(grids[2].item(0, 0).text(), ('A', 'C', 'B'))
        for chart in tab.findChildren(page_mod.SeriesChart) + tab.findChildren(page_mod.BarChart):
            self.assertFalse(chart.grab().isNull())
        cals = tab.findChildren(CalendarCard)                                   # 回测结果里有收益日历，年历 ⇄ 月历能切
        self.assertEqual(len(cals), 1)
        self.assertEqual(cals[0].view, 'year')
        cals[0].set_view('month')
        self.assertFalse(cals[0].chart.grab().isNull())
        self.assertIn('月累计收益', cals[0].summary.text())
        self.button('把今天的信号记入策略 D 前向跟踪').click()
        QTest.qWait(50)
        ledger = json.loads((self.out / '_home' / 'dip_fusion_forward.json').read_text(encoding='utf-8'))
        self.assertEqual(len(ledger['records']), 1)
        self.assertTrue(ledger['records'][0]['fired'])
        self.assertTrue(all(p['sleeve'] in 'ACB' for p in ledger['records'][0]['picks']))
        self.assertFalse((self.out / '_home' / 'dip_forward.json').exists())            # 其它两本记录不受影响
        self.assertFalse((self.out / '_home' / 'dip_industry_forward.json').exists())
        self.assertTrue(any('已记录' in t for t in self.labels()))
        self.button('清空策略 D 记录').click()
        self.button('再点一次确认清空').click()
        QTest.qWait(50)
        self.assertFalse((self.out / '_home' / 'dip_fusion_forward.json').exists())

    def test_fusion_tab_d1_option_switches_ranking_and_keeps_a_separate_ledger(self):
        self.cache_panel()
        self.go()
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        fus = self.window.bench_state['fusion']
        self.assertNotIn('error', fus['d1'])
        self.assertEqual(fus['d1']['run']['config']['rank_mode'], 'dd60')
        self.assertEqual(fus['run']['config']['rank_mode'], 'ret20')
        tab = tabs.widget(5)
        selector = next(c for c in tab.findChildren(QComboBox) if c.accessibleName() == '候选排序')
        self.assertEqual(selector.currentData(), 'D')
        self.assertFalse(any('D1 = 策略 D 只换一件事' in w.text() for w in tab.findChildren(QLabel)))
        selector.setCurrentIndex(1)                                            # 选 D1：页面重建
        QTest.qWait(50)
        self.assertEqual(self.window.bench_state['fusion_variant'], 'D1')
        tab = tabs.widget(5)
        texts = [w.text() for w in tab.findChildren(QLabel)]
        self.assertTrue(any('D1 = 策略 D 只换一件事' in t for t in texts))
        self.assertTrue(any('策略 D1 的回测与风险' in t for t in texts))
        self.assertTrue(any('60 日回撤' in t for t in texts))
        self.assertIn('60日回撤', [g.horizontalHeaderItem(i).text() for g in tab.findChildren(QTableWidget) for i in range(g.columnCount())])
        self.button('把今天的信号记入策略 D1 前向跟踪').click()
        QTest.qWait(50)
        ledger = json.loads((self.out / '_home' / 'dip_fusion1_forward.json').read_text(encoding='utf-8'))
        self.assertEqual(ledger['config']['rank_mode'], 'dd60')
        self.assertEqual(len(ledger['records']), 1)
        self.assertFalse((self.out / '_home' / 'dip_fusion_forward.json').exists())      # D 的台账不受影响
        selector = next(c for c in tabs.widget(5).findChildren(QComboBox) if c.accessibleName() == '候选排序')
        selector.setCurrentIndex(0)                                            # 切回 D：看到的是 D 自己的（空）台账
        QTest.qWait(50)
        self.assertEqual(self.window.bench_state['fusion_variant'], 'D')
        self.button('把今天的信号记入策略 D 前向跟踪')
        self.assertFalse(any('清空策略 D 记录' == b.text() for b in self.window.scroll.widget().findChildren(QPushButton)))
        selector = next(c for c in tabs.widget(5).findChildren(QComboBox) if c.accessibleName() == '候选排序')
        selector.setCurrentIndex(1)
        QTest.qWait(50)
        self.button('清空策略 D1 记录').click()
        self.button('再点一次确认清空').click()
        QTest.qWait(50)
        self.assertFalse((self.out / '_home' / 'dip_fusion1_forward.json').exists())

    def test_fusion_tab_degrades_without_industry_classification(self):
        self.cache_panel()
        with mock.patch('quantlab.dipbuy.industry.industry_dir', side_effect=dpanel.DipDataError('数据侧尚未交付 sw_industry_history')):
            self.go()
        self.assertIn('error', self.window.bench_state['fusion'])
        self.assertTrue(any('策略 D 暂不可用' in t for t in self.labels()))
        self.assertIsNotNone(self.window.bench_state['default'])                       # 其余标签照常

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

    def test_guide_tab_is_available_before_data_is_loaded(self):
        self.window.navigate_page('bench')
        wait(self.window)
        self.assertIsNone(self.window.bench_state['panel'])
        tabs = self.window.scroll.widget().findChild(QTabWidget)
        self.assertEqual(tabs.tabText(tabs.count() - 1), '策略说明')
        guide = tabs.widget(tabs.count() - 1)
        text = '\n'.join(w.text() for w in guide.findChildren(QLabel))
        for needle in ('A　大盘恐慌', 'B　行业恐慌', 'C　成交额分档恐慌', 'D　三层共用一笔钱', 'D1　D 换一种排序', '每天怎么用这个工作台', '风险与局限'):
            self.assertIn(needle, text)
        self.assertGreaterEqual(len(guide.findChildren(QTableWidget)), 3)

    def test_auto_record_row_without_recorder_explains_and_toggles(self):
        from quantlab.dipbuy import autorecord
        self.window.navigate_page('bench')
        wait(self.window)
        box = next(c for c in self.window.scroll.widget().findChildren(page_mod.QCheckBox) if c.accessibleName() == '自动记录前向信号')
        self.assertTrue(box.isChecked())
        self.assertTrue(any('只在正式启动牛牛时运行' in t for t in self.labels()))
        box.setChecked(False)
        self.assertFalse(autorecord.load_state(self.out)['enabled'])
        self.assertTrue(any('自动记录已关闭' in t for t in self.labels()))
        box.setChecked(True)
        self.assertTrue(autorecord.load_state(self.out)['enabled'])

    def test_auto_record_row_with_recorder_checks_and_refreshes_after_a_new_record(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class Stub(QObject):
            finished = pyqtSignal(object)
            running = False

            def __init__(self):
                super().__init__()
                self.calls = []

            def check(self, force=False):
                self.calls.append(force)
                return True

        stub = Stub()
        self.window.dip_autorecorder = stub
        self.cache_panel()
        self.go()
        self.button('现在检查一次').click()
        self.assertEqual(stub.calls, [True])
        self.assertTrue(any('正在检查数据' in t for t in self.labels()))
        stub.finished.emit({'error': '读取失败'})
        self.assertTrue(any('自动检查出错：读取失败' in t for t in self.labels()))
        # 自动记录写了台账以后，页面应当用真实行情重新结算并刷新
        with mock.patch.object(page_mod.BenchPage, 'refresh_all_forward') as refresh:
            stub.finished.emit({'checked_at': '2026-10-07T10:00:00', 'data_date': '2026-10-06',
                                'results': {'fusion': {'status': 'recorded', 'n_picks': 3}}})
            refresh.assert_called_once()

    def test_not_ready_shows_note_only(self):
        with mock.patch('quantlab.desktop.strategy_bench_page.is_data_ready', return_value=False):
            self.window.navigate_page('bench')
            wait(self.window)
        self.assertTrue(any('数据侧尚未开放' in t for t in self.labels()))
        self.assertFalse(hasattr(self.window, 'bench_state') and self.window.bench_state['panel'])


if __name__ == '__main__':
    unittest.main()
