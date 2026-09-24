"""Stock report, 我的股票 and the everyday assistant profile, over the synthetic lake."""
import json
import os
import tempfile
import unittest
import unittest.mock
from datetime import timedelta
from pathlib import Path

import polars as pl

import test_market_overview as base

from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.home_tools import EVERYDAY_TOOLS
from quantlab.agent.model_config import ModelConfig
from quantlab.trading.market_overview import save_overview
from quantlab.trading.my_stocks import add_stock, inspect_my_stocks, load_my_stocks, my_stocks_prompt, remove_stock
from quantlab.trading.stock_report import (StockReportError, build_stock_report, normalize_code, online_context,
                                           report_prompt)


class Fixture:
    """Reuse the market fixture, then add DATA event files and save an overview."""

    def setUp(self):
        self.base = base.MarketOverviewTests('test_cli_builds_and_shows')
        self.base.setUp()
        self.root, self.days, self.build = self.base.root, self.base.days, self.base.build
        lake = self.root / 'lake'
        earn, lock, trades = lake / 'earn', lake / 'lock', lake / 'trades'
        for d in (earn, lock, trades):
            d.mkdir()
        last = self.days[-1]
        pl.DataFrame({'code': ['000004'], 'name': ['丁股份'], 'notice_date': [str(last)], 'report_date': ['2026-09-30'],
                      'indicator': ['净利润'], 'forecast_type': ['首亏'], 'change_pct_lower': [-50.0],
                      'change_pct_upper': [-30.0]}).write_parquet(earn / f'{last}.parquet')
        pl.DataFrame({'SECURITY_CODE': ['000004'], 'FREE_SHARES_TYPE': ['首发原股东限售股份']}).write_parquet(
            lock / f'{last + timedelta(days=10)}.parquet')
        pl.DataFrame({'code': ['000004'], 'notice_date': [str(last)], 'holder': ['某股东'], 'direction': ['减持'],
                      'change_shares_10k': [-100.0], 'channel': ['二级市场']}).write_parquet(trades / f'{last}.parquet')
        self.catalog = base._catalog(self.root, [
            ('qfq_published_f24', lake / 'qfq'), ('security_status_baostock_v2', lake / 'status'),
            ('limit_up_pool_ths', lake / 'pool'), ('margin_detail_exchange', lake / 'margin'),
            ('reference_snapshot_baostock_20260923', lake / 'ref'), ('earnings_forecast_em', earn),
            ('lockup_expiry_em', lock), ('holder_trades_em', trades)])
        self.out = self.root / 'artifacts'
        save_overview(self.out, self.build())

    def tearDown(self):
        self.base.tearDown()


class StockReportTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def test_code_forms(self):
        self.assertEqual(normalize_code('600000'), 'sh.600000')
        self.assertEqual(normalize_code('000001.SZ'), 'sz.000001')
        self.assertEqual(normalize_code('SH600000'), 'sh.600000')
        self.assertIsNone(normalize_code('12345'))

    def test_report_by_code_and_name_with_flags_and_events(self):
        report = build_stock_report(self.f.out, '丁股份', self.f.catalog)
        self.assertEqual(report['code'], 'sz.000004')
        self.assertEqual(len(report['kline']), 40)
        text = ' '.join(report['flags'])
        self.assertIn('解禁', text)
        self.assertIn('减持', text)
        self.assertIn('首亏', text)
        self.assertNotIn('sz.000004', [p['code'] for p in report['peers']])
        self.assertIn('丁股份（sz.000004）', report['summary'])
        self.assertIn('什么情况说明判断错了', report_prompt(report))

    def test_streak_flag_and_unknown_stock(self):
        report = build_stock_report(self.f.out, 'sh.600001', self.f.catalog)
        self.assertEqual(report['facts']['streak'], 2)
        with self.assertRaisesRegex(StockReportError, '找不到'):
            build_stock_report(self.f.out, '不存在的名字', self.f.catalog)
        with self.assertRaisesRegex(StockReportError, '不在'):
            build_stock_report(self.f.out, '600999', self.f.catalog)

    def test_report_requires_market_overview(self):
        with self.assertRaisesRegex(StockReportError, '今日市场'):
            build_stock_report(self.f.root / 'empty', '600001', self.f.catalog)

    def test_online_sections_fail_independently_without_substitution(self):
        class Provider:
            def stock_announcements(self, code, limit):
                return type('R', (), {'rows': ({'publish_date': '2026-08-25', 'title': '公告'},)})()

            def stock_research_reports(self, code, limit):
                raise RuntimeError('down')
        (self.f.root / 'api').mkdir()
        catalog = base._catalog(self.f.root / 'api', [('stock_announcements', ''), ('stock_research_reports', '')])
        text = catalog.read_text(encoding='utf-8').replace('| FILE |', '| API |').replace('| ``', '| `x`')
        catalog.write_text(text, encoding='utf-8')
        result = online_context('sh.600001', catalog, Provider())
        self.assertEqual(result['announcements']['rows'][0]['title'], '公告')
        self.assertIn('查询失败', result['research_reports']['error'])
        missing = online_context('sh.600001', self.f.catalog, Provider())
        self.assertEqual(missing['announcements']['error'], '数据侧尚未开放这个接口')

    def test_my_stocks_add_inspect_remove(self):
        add_stock(self.f.out, '600001', weight=0.3, cost=10)
        add_stock(self.f.out, 'sz.000004', weight=0.2)
        with self.assertRaisesRegex(ValueError, '超过'):
            add_stock(self.f.out, '600002', weight=0.6)
        result = inspect_my_stocks(self.f.out, self.f.catalog)
        rows = {r['code']: r for r in result['rows']}
        self.assertAlmostEqual(rows['sh.600001']['pnl'], 0.21, places=6)
        self.assertTrue(rows['sz.000004']['flags'])
        self.assertIn('50%', ' '.join(result['notes']))
        self.assertIn('丁股份', my_stocks_prompt(result))
        remove_stock(self.f.out, '600001')
        self.assertEqual([i['code'] for i in load_my_stocks(self.f.out)], ['sz.000004'])


class EverydayProfileTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def test_everyday_profile_is_small_and_reads_pages(self):
        runtime = ChatRuntime(self.f.out, self.f.out, tool_profile='everyday', data_catalog_path=self.f.catalog)
        names = {t['name'] for t in runtime.api.schemas()}
        self.assertLessEqual(names, EVERYDAY_TOOLS)
        self.assertIn('get_stock_report', names)
        self.assertNotIn('propose_experiment', names)
        denied = runtime.api.call('propose_experiment', {})
        self.assertEqual(denied['error']['code'], 'UNKNOWN_TOOL')
        report = runtime.api.call('get_stock_report', {'query': '600001'})
        self.assertTrue(report['ok'], report)
        self.assertLessEqual(len(report['data']['kline']), 20)
        overview = runtime.api.call('get_market_overview', {})
        self.assertEqual(overview['data']['trading_day'], self.f.days[-1].isoformat())

    def test_everyday_system_prompt_is_short_and_turn_works(self):
        class Provider:
            system = ''

            def run(self, system, messages, tools, dispatch, emit, stop):
                Provider.system = system
                result = dispatch('get_market_overview', {}, 'c1')
                assert result['ok'], result
                return {'text': '市场偏弱', 'model': 'fixture', 'provider': 'fixture', 'tool_calls': 1, 'usage': {}}
        runtime = ChatRuntime(self.f.out, self.f.out, tool_profile='everyday', data_catalog_path=self.f.catalog)
        cid = runtime.store.create()
        result = runtime.send(cid, '今天市场怎么样', ModelConfig(), allow_send=True, provider=Provider())
        self.assertEqual(result['text'], '市场偏弱')
        self.assertLess(len(Provider.system), 8000)
        self.assertIn('基本规则', Provider.system)

    def test_research_profile_keeps_full_tools_and_rejects_bad_profile(self):
        runtime = ChatRuntime(self.f.out, self.f.out, data_catalog_path=self.f.catalog)
        names = {t['name'] for t in runtime.api.schemas()}
        self.assertIn('propose_experiment', names)
        self.assertIn('get_market_overview', names)
        with self.assertRaises(ValueError):
            ChatRuntime(self.f.out, self.f.out, tool_profile='other')


@unittest.skipUnless(__import__('importlib').util.find_spec('PyQt6'), 'Install desktop dependency')
class StockPagesDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.f = Fixture()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def wait(self, window):
        from PyQt6.QtTest import QTest
        for _ in range(100):
            QTest.qWait(20)
            if not window.callbacks:
                break

    def test_report_page_my_stocks_and_ai_prefill(self):
        from PyQt6.QtWidgets import QLabel, QTableWidget
        from quantlab.desktop.app import MainWindow
        window = MainWindow(self.f.out)
        window.data_catalog_path = self.f.catalog
        window.show()
        window.open_stock_report('丁股份')
        self.wait(window)
        texts = [w.text() for w in window.scroll.widget().findChildren(QLabel)]
        self.assertTrue(any('解禁' in t for t in texts))
        add_stock(self.f.out, '600001')
        window.navigate_page('mine')
        self.wait(window)
        tables = window.scroll.widget().findChildren(QTableWidget)
        self.assertEqual(tables[0].rowCount(), 1)
        window.ask_ai('请帮我看看 600001')
        dialog = window._research_chat_dialog
        self.assertEqual(dialog.input.toPlainText(), '请帮我看看 600001')
        self.assertEqual(dialog.profile.currentData(), 'everyday')
        self.assertEqual(dialog.runtime.tool_profile, 'everyday')
        window.close()


if __name__ == '__main__':
    unittest.main()
