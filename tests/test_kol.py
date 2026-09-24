"""大V复盘: saved posts, extracted views, and their checks as judgments."""
import os
import unittest
from datetime import timedelta

from test_stock_report import Fixture

from quantlab.trading.judgments import load_judgments, review_judgments
from quantlab.trading.kol import (add_post, clean_view, confirm_views, digest_prompt, extract_views, get_post,
                                  list_posts, parse_extraction, set_views)

TEXT = '今天市场放量上涨。明天大盘大概率继续上攻。甲股份两连板，短期还有溢价。回避银行板块。'


class FakeProvider:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def run(self, system, messages, tools, dispatch, emit, stop):
        self.calls.append((system, messages, tools))
        return {'text': self.reply, 'model': 'fixture-model', 'provider': 'fixture'}


REPLY = ('好的，结果如下：{"summary": "看多大盘和甲股份", "views": ['
         '{"kind": "market", "target": "大盘", "stance": "bullish", "horizon": 1, "quote": "明天大盘大概率继续上攻"},'
         '{"kind": "stock", "target": "甲股份", "stance": "bullish", "horizon": 5, "quote": "甲股份两连板，短期还有溢价"},'
         '{"kind": "direction", "target": "银行", "stance": "bearish", "horizon": 3, "quote": "回避银行板块"},'
         '{"kind": "stock", "target": "不存在股份", "stance": "bullish", "horizon": 1, "quote": "编造的话"},'
         '{"kind": "stock", "target": "乙", "stance": "up", "horizon": 1, "quote": ""}]}')


class ParseTests(unittest.TestCase):
    def test_parse_checks_quotes_and_drops_bad_views(self):
        parsed = parse_extraction(REPLY, TEXT)
        self.assertEqual(parsed['summary'], '看多大盘和甲股份')
        self.assertEqual(len(parsed['views']), 4)
        self.assertEqual(parsed['dropped'], 1)
        self.assertEqual([v['quote_found'] for v in parsed['views']], [True, True, True, False])
        for bad in ('没有 JSON', '{"views": 3}', '{"views": [], "views": []}'):
            with self.assertRaises(ValueError):
                parse_extraction(bad, TEXT)

    def test_view_validation(self):
        view = clean_view({'kind': 'market', 'target': '', 'stance': 'neutral', 'horizon': 3, 'quote': ''}, TEXT)
        self.assertEqual(view['target'], '大盘')
        for bad in ({'kind': 'x'}, {'kind': 'stock', 'target': 'a', 'stance': 'bullish', 'horizon': 2},
                    {'kind': 'stock', 'target': 'a', 'stance': 'bullish', 'horizon': True},
                    {'kind': 'stock', 'target': '', 'stance': 'bullish', 'horizon': 1}):
            with self.assertRaises(ValueError):
                clean_view(bad, TEXT)


class KolStoreTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def post(self, day=None, **kwargs):
        args = dict(author='老张', text=TEXT, published_on=(day or self.f.days[-6]).isoformat(), platform='雪球')
        args.update(kwargs)
        return add_post(self.f.out, **args)

    def test_add_post_validation(self):
        post = self.post()
        self.assertEqual(post['title'], TEXT[:60])
        for bad, message in ((dict(author=''), '作者'), (dict(text=''), '正文'), (dict(platform='抖音'), '平台'),
                             (dict(url='ftp://x'), '链接'), (dict(text='x' * 30001), '过长'), ({}, '已经保存')):
            with self.assertRaisesRegex(ValueError, message):
                self.post(**bad)

    def test_extract_confirm_and_check(self):
        post = self.post()
        provider = FakeProvider(REPLY)
        extract_views(self.f.out, post['id'], api_key='', provider=provider)
        system, messages, tools = provider.calls[0]
        self.assertEqual(tools, [])
        self.assertIn('外部数据', system)
        self.assertIn(TEXT, messages[0]['content'])
        stored = get_post(self.f.out, post['id'])
        self.assertEqual((len(stored['views']), stored['extracted_by']['model']), (4, 'fixture-model'))
        result = confirm_views(self.f.out, post['id'], self.f.catalog)
        self.assertEqual(result['saved'], 2)
        self.assertEqual(len(result['skipped']), 2)  # the direction view and the unknown stock
        # Saving again replaces the post's judgments instead of duplicating them.
        confirm_views(self.f.out, post['id'], self.f.catalog)
        judgments = load_judgments(self.f.out)
        self.assertEqual(len(judgments), 2)
        self.assertTrue(all(j['author'] == '老张' and j['source'] == 'kol' for j in judgments))
        review = review_judgments(self.f.out, self.f.catalog)
        rows = {r['code']: r['result'] for r in review['rows']}
        self.assertEqual((rows['sh.600001']['verdict'], round(rows['sh.600001']['return'], 6)), ('right', 0.21))
        self.assertEqual(rows['market']['status'], 'done')
        self.assertIsNone(rows['market']['excess'])  # the market is its own benchmark
        author = review['stats']['groups']['author'][0]
        self.assertEqual((author['label'], author['finished']), ('老张', review['stats']['overall']['finished']))
        self.assertIn('已保存 2 条待核对', list_posts(self.f.out)[0]['status'])
        self.assertIn('老张', digest_prompt(list_posts(self.f.out), None))

    def test_weekend_post_is_judged_from_the_previous_close(self):
        friday = next(d for d in reversed(self.f.days[:-3]) if d.weekday() == 4)
        post = self.post(day=friday + timedelta(days=1))
        set_views(self.f.out, post['id'], [{'kind': 'stock', 'target': '600002', 'stance': 'bearish', 'horizon': 1,
                                            'quote': ''}])
        confirm_views(self.f.out, post['id'], self.f.catalog)
        judgment = load_judgments(self.f.out)[0]
        self.assertEqual((judgment['made_on'], judgment['close']), (friday.isoformat(), 20.0))

    def test_provider_key_is_required_for_http_models(self):
        from quantlab.agent.model_config import ModelConfig
        post = self.post()
        with self.assertRaisesRegex(ValueError, '密钥'):
            extract_views(self.f.out, post['id'], config=ModelConfig(provider='responses', model='m'), api_key='')


@unittest.skipUnless(__import__('importlib').util.find_spec('PyQt6'), 'Install desktop dependency')
class KolPageDesktopTests(unittest.TestCase):
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

    def card(self, window, attribute):
        from quantlab.desktop.widgets import Card
        return next(c for c in window.scroll.widget().findChildren(Card) if hasattr(c, attribute))

    def test_import_add_view_confirm_and_author_table(self):
        from PyQt6.QtCore import QDate
        from PyQt6.QtWidgets import QTableWidget
        from quantlab.desktop.app import MainWindow
        window = MainWindow(self.f.out)
        window.data_catalog_path = self.f.catalog
        window.show()
        window.navigate_page('kol')
        self.wait(window)
        controls = self.card(window, 'import_controls').import_controls
        controls['save']()
        self.assertIn('作者', controls['status'].text())
        controls['author'].setText('老张')
        controls['day'].setDate(QDate.fromString(self.f.days[-6].isoformat(), 'yyyy-MM-dd'))
        controls['text'].setPlainText(TEXT)
        controls['save']()
        self.wait(window)
        detail = self.card(window, 'detail_controls').detail_controls
        detail['kind'].setCurrentIndex(1)  # 个股
        detail['target'].setText('甲股份')
        detail['horizon'].setCurrentIndex(2)  # 5 个交易日
        detail['add_view']()
        self.wait(window)
        detail = self.card(window, 'detail_controls').detail_controls
        self.assertEqual(detail['grid'].rowCount(), 1)
        detail['confirm']()
        self.assertIn('已保存 1 条', detail['status'].text())
        window.navigate_page('kol')
        self.wait(window)
        tables = window.scroll.widget().findChildren(QTableWidget)
        self.assertEqual(tables[-1].item(0, 0).text(), '老张')
        self.assertEqual(tables[-1].item(0, 2).text(), '100%')
        window.close()


if __name__ == '__main__':
    unittest.main()
