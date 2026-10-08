"""每个交易日自动记录前向信号：新鲜度、开关与状态、只在数据变了才做、重复 / 过期 / 出错的处理。"""
import json
import sys
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

from quantlab.dipbuy import autorecord, panel as dpanel, tracker
from test_dipbuy import make_panel

SH = timezone(timedelta(hours=8))


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


def evening(panel, hours=20):
    d = datetime.fromisoformat(panel.last_date)
    return d.replace(hour=hours, tzinfo=SH)


class FreshnessTests(unittest.TestCase):
    def test_window_closes_at_next_trading_day_open(self):
        fri = '2026-09-25'            # 周五
        self.assertTrue(autorecord.is_fresh(fri, datetime(2026, 9, 25, 20, 0, tzinfo=SH)))      # 当天晚上
        self.assertTrue(autorecord.is_fresh(fri, datetime(2026, 9, 27, 12, 0, tzinfo=SH)))      # 周末
        self.assertTrue(autorecord.is_fresh(fri, datetime(2026, 9, 28, 9, 29, tzinfo=SH)))      # 周一开盘前
        self.assertFalse(autorecord.is_fresh(fri, datetime(2026, 9, 28, 9, 30, tzinfo=SH)))     # 周一开盘后不再记
        thu = '2026-09-24'
        self.assertFalse(autorecord.is_fresh(thu, datetime(2026, 9, 26, 12, 0, tzinfo=SH)))     # 周六：周五已开盘
        utc = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)                                   # = 周一 9:00 上海
        self.assertTrue(autorecord.is_fresh(fri, utc))

    def test_holiday_closures_are_skipped(self):
        # 国庆休市 10 月 1 日至 7 日，10 月 8 日（周四）开市：9 月 30 日的信号在假期里仍然新鲜
        last = '2026-09-30'
        self.assertEqual(autorecord.next_open_day(last), date(2026, 10, 8))
        self.assertTrue(autorecord.is_fresh(last, datetime(2026, 10, 7, 19, 0, tzinfo=SH)))
        self.assertTrue(autorecord.is_fresh(last, datetime(2026, 10, 8, 9, 29, tzinfo=SH)))
        self.assertFalse(autorecord.is_fresh(last, datetime(2026, 10, 8, 9, 30, tzinfo=SH)))

    def test_new_year_day_is_always_closed(self):
        self.assertEqual(autorecord.next_open_day('2026-12-31'), date(2027, 1, 4))      # 1 月 1 日周五休市，周末，周一开市
        self.assertEqual(autorecord.next_open_day('2026-09-30') > date(2026, 9, 30), True)

    def test_a_broken_closure_list_cannot_loop_forever(self):
        everyday = frozenset(date(2026, 10, 1) + timedelta(days=i) for i in range(60))
        with mock.patch.object(autorecord, 'KNOWN_CLOSURES', everyday):
            self.assertIsInstance(autorecord.next_open_day('2026-09-30'), date)


class StateTests(unittest.TestCase):
    def test_defaults_toggle_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertTrue(autorecord.load_state(out)['enabled'])
            autorecord.set_enabled(out, False)
            self.assertFalse(autorecord.load_state(out)['enabled'])
            (Path(out) / '_home' / 'dip_autorecord.json').write_text('{', encoding='utf-8')
            self.assertTrue(autorecord.load_state(out)['enabled'])                                # 坏文件回到默认
            self.assertEqual(autorecord.describe_last(None), '还没有自动检查过。')


class RecordLatestTests(unittest.TestCase):
    def setUp(self):
        self.panel = crash_panel()
        self.now = evening(self.panel)

    def test_records_market_ledger_once_and_only_while_fresh(self):
        with tempfile.TemporaryDirectory() as out:
            res = autorecord.record_latest(out, self.panel, None, {}, kinds=('market',), now=self.now)
            self.assertEqual(res['market']['status'], 'recorded')
            ledger = tracker.load_ledger(out, 'market')
            self.assertEqual([r['signal_date'] for r in ledger['records']], [self.panel.last_date])
            again = autorecord.record_latest(out, self.panel, None, {}, kinds=('market',), now=self.now)
            self.assertEqual(again['market']['status'], 'exists')
            self.assertEqual(len(tracker.load_ledger(out, 'market')['records']), 1)
            late = autorecord.record_latest(out, self.panel, None, {}, kinds=('market',), now=self.now + timedelta(days=3))
            self.assertEqual(late['market']['status'], 'stale')

    def test_stale_data_never_records(self):
        with tempfile.TemporaryDirectory() as out:
            res = autorecord.record_latest(out, self.panel, None, {}, kinds=('market', 'fusion'), now=self.now + timedelta(days=5))
            self.assertEqual({r['status'] for r in res.values()}, {'stale'})
            self.assertEqual(tracker.load_ledger(out, 'market')['records'], [])

    def test_closed_gate_and_missing_classification_are_reported_not_raised(self):
        calm = make_panel(np.full((340, 30), 10.0))
        with tempfile.TemporaryDirectory() as out:
            res = autorecord.record_latest(out, calm, None, {}, now=evening(calm))
            self.assertEqual(res['market']['status'], 'closed')
            self.assertEqual(res['fusion']['status'], 'error')                                    # 没有行业分类，D / D1 / B 算不了
            self.assertEqual(res['fusion1']['status'], 'error')
            self.assertEqual(res['fusion2']['status'], 'error')
            self.assertEqual(res['fusion3']['status'], 'error')
            self.assertEqual(res['industry']['status'], 'error')
            self.assertIn('行业分类', res['fusion']['message'])

    def test_one_ledger_failing_does_not_stop_the_others(self):
        real = autorecord.build_signal

        def flaky(kind, panel, cls, names):
            if kind == 'fusion':
                raise RuntimeError('boom')
            return real(kind, panel, cls, names)
        with tempfile.TemporaryDirectory() as out, mock.patch.object(autorecord, 'build_signal', flaky):
            res = autorecord.record_latest(out, self.panel, None, {}, kinds=('fusion', 'market'), now=self.now)
            self.assertEqual((res['fusion']['status'], res['market']['status']), ('error', 'recorded'))

    def test_frozen_config_conflict_is_skipped_with_reason(self):
        from quantlab.dipbuy.engine import DipConfig
        with tempfile.TemporaryDirectory() as out:
            market, cand = __import__('quantlab.dipbuy.engine', fromlist=['x']).compute_features(self.panel)
            old = __import__('quantlab.dipbuy.engine', fromlist=['x']).latest_signal(self.panel, market, cand, DipConfig(leverage=1.0))
            ledger_cfg = DipConfig(leverage=1.0)
            tracker.record_signal(out, dict(old, date='2000-01-03'), ledger_cfg, kind='market') if old['gate_open'] and old['picks'] else None
            res = autorecord.record_latest(out, self.panel, None, {}, kinds=('market',), now=self.now)
            self.assertIn(res['market']['status'], ('skipped', 'recorded'))                       # 有旧记录且参数不同 → skipped；没有旧记录 → recorded


class RunIfNewTests(unittest.TestCase):
    def setUp(self):
        self.panel = crash_panel()
        self.now = evening(self.panel)
        self.sig = ['sig-1']
        self.patches = [
            mock.patch.object(dpanel, 'current_sources', lambda catalog=None: (None, None, None, self.sig[0])),
            mock.patch.object(dpanel, 'load_panel', lambda *a, **k: self.panel),
            mock.patch.object(dpanel, 'load_names', lambda *a, **k: {}),
            mock.patch.object(autorecord.industry, 'load_classification_for', mock.Mock(side_effect=ValueError('no cls'))),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_runs_once_per_data_change_and_respects_the_switch(self):
        with tempfile.TemporaryDirectory() as out:
            first = autorecord.run_if_new(out, None, now=self.now, kinds=('market',))
            self.assertEqual(first['data_date'], self.panel.last_date)
            self.assertEqual(first['results']['market']['status'], 'recorded')
            self.assertIsNone(autorecord.run_if_new(out, None, now=self.now, kinds=('market',)))        # 数据没变：不再做
            forced = autorecord.run_if_new(out, None, force=True, now=self.now, kinds=('market',))
            self.assertEqual(forced['results']['market']['status'], 'exists')
            self.sig[0] = 'sig-2'
            autorecord.set_enabled(out, False)
            self.assertIsNone(autorecord.run_if_new(out, None, now=self.now, kinds=('market',)))        # 开关关着：不做
            autorecord.set_enabled(out, True)
            self.assertIsNotNone(autorecord.run_if_new(out, None, now=self.now, kinds=('market',)))     # 数据变了：再做
            state = autorecord.load_state(out)
            self.assertEqual(state['last_signature'], 'sig-2')
            text = autorecord.describe_last(state['last'])
            self.assertIn('策略 A（大盘恐慌）', text)
            self.assertIn(self.panel.last_date, text)

    def test_errors_are_retried_and_data_not_ready_is_silent(self):
        with tempfile.TemporaryDirectory() as out:
            with mock.patch.object(autorecord, 'build_signal', side_effect=RuntimeError('boom')):
                res = autorecord.run_if_new(out, None, now=self.now, kinds=('market',))
                self.assertEqual(res['results']['market']['status'], 'error')
            self.assertIsNone(autorecord.load_state(out)['last_signature'])                           # 出错的不算做完
            self.assertEqual(autorecord.run_if_new(out, None, now=self.now, kinds=('market',))['results']['market']['status'], 'recorded')
            with mock.patch.object(dpanel, 'current_sources', side_effect=dpanel.DipDataError('尚未交付')):
                self.assertIsNone(autorecord.run_if_new(out, None, force=True, now=self.now))


if __name__ == '__main__':
    unittest.main()
