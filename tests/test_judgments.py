"""复盘验证: saved judgments checked against later bars, and the review page."""
import json
import os
import unittest
from datetime import date, timedelta

from test_stock_report import Fixture

from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.trading.judgments import (delete_judgment, evaluate, judgments_prompt, load_judgments,
                                        review_judgments, save_judgment, summarize)

D0 = date(2026, 3, 2)
DAYS = [D0 + timedelta(days=i) for i in range(30)]


def bars(closes, factor=1.0):
    """Adjusted closes; raw close = adjusted / factor."""
    return [{'date': d, 'close': c, 'close_raw': c / factor} for d, c in zip(DAYS, closes)]


def judgment(stance='bullish', horizon=5, stop=None, target=None):
    return {'made_on': DAYS[0].isoformat(), 'stance': stance, 'horizon': horizon, 'stop': stop, 'target': target}


class EvaluateTests(unittest.TestCase):
    def test_bullish_right_at_horizon_with_market_excess(self):
        market = {d: 0.001 for d in DAYS}
        r = evaluate(judgment(), bars([10, 10.2, 10.4, 10.5, 10.6, 10.8, 20]), market, DAYS[10])
        self.assertEqual((r['status'], r['verdict'], r['sessions_done'], r['end_day']), ('done', 'right', 5, DAYS[5].isoformat()))
        self.assertAlmostEqual(r['return'], 0.08)
        self.assertAlmostEqual(r['market'], 1.001 ** 5 - 1, places=5)
        self.assertAlmostEqual(r['aligned_excess'], 0.08 - (1.001 ** 5 - 1), places=5)
        self.assertTrue(r['text'].startswith('判断正确'))

    def test_stop_ends_the_check_early_using_actual_close(self):
        # Adjusted closes are half the actual price: the stop at 19 actual = 9.5 adjusted.
        r = evaluate(judgment(stop=19.0, target=30.0), bars([10, 9.8, 9.4, 12, 12, 12], factor=0.5), None, DAYS[10])
        self.assertEqual((r['verdict'], r['trigger']['kind'], r['trigger']['date']), ('wrong', 'stop', DAYS[2].isoformat()))
        self.assertAlmostEqual(r['return'], -0.06)
        self.assertIsNone(r['market'])

    def test_bearish_target_neutral_and_flat(self):
        r = evaluate(judgment('bearish', target=9.0), bars([10, 9.5, 8.9, 12, 12, 12]), None, DAYS[10])
        self.assertEqual((r['verdict'], r['aligned']), ('right', 0.11))
        r = evaluate(judgment('neutral'), bars([10, 11, 12, 13, 14, 15]), None, DAYS[10])
        self.assertEqual((r['verdict'], r['aligned']), ('none', None))
        r = evaluate(judgment(), bars([10, 10, 10, 10, 10, 10.05]), None, DAYS[10])
        self.assertEqual(r['verdict'], 'flat')

    def test_running_waiting_and_suspended_sessions(self):
        market = {d: 0.0 for d in DAYS}
        r = evaluate(judgment(horizon=10), bars([10, 11, 12]), market, DAYS[2])
        self.assertEqual((r['status'], r['sessions_done'], r['verdict']), ('running', 2, None))
        r = evaluate(judgment(), bars([10]), market, DAYS[0])
        self.assertEqual(r['status'], 'waiting')
        # The stock is suspended on sessions 1-3: the market calendar still counts them.
        partial = [b for b in bars([10, 0, 0, 0, 11, 12]) if b['close']]
        r = evaluate(judgment(), partial, market, DAYS[10])
        self.assertEqual((r['status'], r['end_day']), ('done', DAYS[5].isoformat()))
        self.assertAlmostEqual(r['return'], 0.2)

    def test_summary_counts_only_finished_directional(self):
        rows = [{'source': 'me', 'stance': 'bullish', 'horizon': 5, 'result': {'status': 'done', 'verdict': 'right',
                 'aligned': 0.05, 'aligned_excess': 0.02}},
                {'source': 'ai', 'stance': 'bearish', 'horizon': 5, 'result': {'status': 'done', 'verdict': 'wrong',
                 'aligned': -0.03, 'aligned_excess': None}},
                {'source': 'me', 'stance': 'neutral', 'horizon': 5, 'result': {'status': 'done', 'verdict': 'none'}},
                {'source': 'me', 'stance': 'bullish', 'horizon': 10, 'result': {'status': 'running'}}]
        s = summarize(rows)
        self.assertEqual((s['overall']['finished'], s['overall']['hit_rate']), (2, 0.5))
        self.assertAlmostEqual(s['overall']['avg_aligned'], 0.01)
        self.assertEqual(s['overall']['avg_aligned_excess'], 0.02)
        self.assertEqual(s['pending']['running'], 1)
        self.assertIn('参考意义有限', s['notes'][0])
        me = next(g for g in s['groups']['source'] if g['key'] == 'me')
        self.assertEqual((me['finished'], me['hit_rate']), (1, 1.0))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def save(self, **kwargs):
        args = dict(code='600001', name='甲股份', made_on=self.f.days[-6].isoformat(), close=10.0, stance='bullish',
                    horizon=5)
        args.update(kwargs)
        return save_judgment(self.f.out, **args)

    def test_validation(self):
        for bad, message in ((dict(stance='up'), '看多'), (dict(horizon=7), '周期'), (dict(stop=11.0), '失效价应低于'),
                             (dict(stance='bearish', target=12.0), '看空'), (dict(stance='neutral', stop=9.0), '观望'),
                             (dict(code='12'), '代码'), (dict(close=0), '正数')):
            with self.assertRaisesRegex(ValueError, message):
                self.save(**bad)
        self.assertEqual(load_judgments(self.f.out), [])

    def test_review_checks_freezes_and_deletes(self):
        right = self.save(reason='放量突破', stop=9.0)  # sh.600001: 10 -> 12.1 over the last five sessions
        running = self.save(code='sh.600002', close=20.0, stance='bearish', horizon=10, source='ai',
                            made_on=self.f.days[-3].isoformat())
        review = review_judgments(self.f.out, self.f.catalog)
        rows = {r['id']: r for r in review['rows']}
        done = rows[right['id']]['result']
        self.assertEqual((done['status'], done['verdict']), ('done', 'right'))
        self.assertAlmostEqual(done['return'], 0.21, places=6)
        self.assertIsNotNone(done['market'])  # the overview carries the per-session market series
        self.assertAlmostEqual(done['excess'], done['return'] - done['market'], places=5)
        self.assertEqual(rows[running['id']]['result']['status'], 'running')
        self.assertAlmostEqual(rows[running['id']]['result']['aligned'], 0.1, places=6)
        stored = {j['id']: j for j in json.loads((self.f.out / '_home' / 'judgments.json').read_text())['judgments']}
        self.assertEqual(stored[right['id']]['result']['verdict'], 'right')  # finished checks are frozen
        self.assertIsNone(stored[running['id']]['result'])
        self.assertIn('甲股份', judgments_prompt(review))
        self.assertTrue(delete_judgment(self.f.out, right['id']))
        self.assertFalse(delete_judgment(self.f.out, right['id']))
        self.assertEqual(len(load_judgments(self.f.out)), 1)

    def test_everyday_tool_reads_judgments(self):
        self.save()
        runtime = ChatRuntime(self.f.out, self.f.out, tool_profile='everyday', data_catalog_path=self.f.catalog)
        result = runtime.api.call('get_judgments', {})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['data']['stats']['overall']['finished'], 1)
        self.assertIn('判断正确', result['data']['recent'][0]['result'])


@unittest.skipUnless(__import__('importlib').util.find_spec('PyQt6'), 'Install desktop dependency')
class ReviewPageDesktopTests(unittest.TestCase):
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

    def test_save_from_stock_report_then_review(self):
        from PyQt6.QtWidgets import QLabel, QTableWidget
        from quantlab.desktop.app import MainWindow
        from quantlab.desktop.widgets import Card
        window = MainWindow(self.f.out)
        window.data_catalog_path = self.f.catalog
        window.show()
        window.navigate_page('review')
        self.wait(window)
        texts = [w.text() for w in window.scroll.widget().findChildren(QLabel)]
        self.assertTrue(any('还没有保存过判断' in t for t in texts))
        window.open_stock_report('600001')
        self.wait(window)
        card = next(c for c in window.scroll.widget().findChildren(Card) if hasattr(c, 'judgment_controls'))
        controls = card.judgment_controls
        controls['stop'].setValue(13.0)  # above the close for 看多: refused
        controls['save']()
        self.assertIn('没有保存', controls['status'].text())
        controls['stop'].setValue(11.0)
        controls['reason'].setText('两连板')
        controls['save']()
        self.assertIn('已保存', controls['status'].text())
        saved = load_judgments(self.f.out)
        self.assertEqual((saved[0]['code'], saved[0]['made_on'], saved[0]['close']),
                         ('sh.600001', self.f.days[-1].isoformat(), 12.1))
        window.navigate_page('review')
        self.wait(window)
        tables = window.scroll.widget().findChildren(QTableWidget)
        detail = tables[-1]
        self.assertEqual(detail.rowCount(), 1)
        self.assertEqual(detail.item(0, 5).text(), '等待数据')
        self.assertEqual(detail.item(0, 9).text(), '两连板')
        window.close()


if __name__ == '__main__':
    unittest.main()
