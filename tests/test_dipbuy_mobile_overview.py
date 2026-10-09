"""手机版首页「市场概览」：情绪档位、历史位置、连跌推演、触发频率与历史类比、关注清单。全部合成数据。"""
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

from quantlab.dipbuy import fusion, mobile_overview as mo
from quantlab.dipbuy.engine import Z_WINDOW
from test_dipbuy_portfolio import fixture


class LevelTests(unittest.TestCase):
    def test_bands_and_edges(self):
        cases = [(-3.0, 'panic'), (-1.5001, 'panic'), (-1.5, 'tense'), (-1.2, 'tense'), (-1.0, 'weak'), (-0.5, 'weak'),
                 (-0.4, 'calm'), (0.0, 'calm'), (0.5999, 'calm'), (0.6, 'strong'), (1.49, 'strong'), (1.5, 'hot'), (4.0, 'hot')]
        for z, key in cases:
            self.assertEqual(mo.level_of(z)['key'], key, z)

    def test_missing_value_is_unknown_not_calm(self):
        for bad in (None, float('nan'), 'x'):
            self.assertEqual(mo.level_of(bad)['key'], 'unknown')

    def test_panic_is_the_trigger_zone(self):
        # 档位边界和策略的触发线一致：z ≤ -1.5 才是“恐慌”，否则页面会说恐慌而策略没动作
        self.assertEqual(mo.level_of(-1.5)['key'], 'tense')
        self.assertEqual(mo.LEVELS[0][0], -1.5)

    def test_percentile(self):
        s = np.array([np.nan, -2.0, -1.0, 0.0, 1.0, 2.0])
        self.assertAlmostEqual(mo.percentile_of(s, -1.0), 2 / 5)
        self.assertAlmostEqual(mo.percentile_of(s, 9.0), 1.0)
        self.assertIsNone(mo.percentile_of(s, None))
        self.assertIsNone(mo.percentile_of([np.nan], 0.0))


def calm_returns(n=300, seed=1, vol=0.01):
    return np.random.default_rng(seed).normal(0.0, vol, n)


class ScenarioTests(unittest.TestCase):
    def test_found_return_triggers_and_one_step_less_does_not(self):
        mret = calm_returns()
        thr = -1.5
        for sc in mo.scenarios(mret, thr, days=(3, 5)):
            self.assertIsNotNone(sc['daily'])
            self.assertLessEqual(mo._z_after(mret, [sc['daily']] * sc['days']), thr)
            self.assertGreater(mo._z_after(mret, [sc['daily'] + mo.SCENARIO_STEP] * sc['days']), thr)
            self.assertAlmostEqual(sc['cum'], (1 + sc['daily']) ** sc['days'] - 1)
            self.assertLess(sc['daily'], 0)

    def test_longer_decline_needs_smaller_daily_drop(self):
        by = {s['days']: s for s in mo.scenarios(calm_returns(), -1.5, days=(3, 5, 8))}
        self.assertGreater(by[3]['daily'] * -1, by[5]['daily'] * -1)
        self.assertGreater(by[5]['daily'] * -1, by[8]['daily'] * -1)

    def test_one_day_is_not_enough_when_far_from_the_line(self):
        # 平静的市场一天跌不出 z ≤ -1.5：页面应当说“一天内基本不可能”，而不是给一个荒唐的数
        one = mo.scenarios(calm_returns(), -1.5, days=(1,))[0]
        self.assertIsNone(one['daily'])
        self.assertIsNone(one['cum'])

    def test_already_deep_in_panic_triggers_with_tiny_drop(self):
        mret = calm_returns()
        mret[-25:] = -0.012                      # 已经连跌 25 天
        self.assertLessEqual(mo._z_after(mret, []), -1.5)
        sc = mo.scenarios(mret, -1.5, days=(1,))[0]
        self.assertIsNotNone(sc['daily'])
        self.assertGreater(sc['daily'], -0.002)

    def test_short_history_gives_none(self):
        self.assertIsNone(mo._z_after(np.zeros(Z_WINDOW - 5), []))
        self.assertTrue(all(s['daily'] is None for s in mo.scenarios(np.zeros(10), -1.5)))


class HistoryTests(unittest.TestCase):
    def test_counts_episodes_and_forward_returns(self):
        n = 400
        dates = [f'd{i}' for i in range(n)]
        z = np.zeros(n)
        z[:60] = np.nan
        z[100:103] = -2.0          # 第 1 段（3 天）
        z[200:202] = -1.6          # 第 2 段（2 天）
        z[395:] = -1.7             # 最后一段：往后不足 20 天，不进入前向统计
        mret = np.zeros(n)
        mret[101:121] = 0.01       # 第 1 段首日之后 20 天，每天 +1%
        h = mo.history_of_gate(dates, z, mret, -1.5, horizon=20)
        self.assertEqual(h['days'], 3 + 2 + 5)
        self.assertEqual(h['episodes'], 3)
        self.assertEqual(h['fwd_n'], 2)
        self.assertAlmostEqual(h['fwd_worst'], 0.0)
        self.assertAlmostEqual(h['fwd_win'], 0.5)
        self.assertEqual(h['last_date'], 'd399')
        self.assertEqual(h['since_last'], 0)
        self.assertGreater(h['fwd_mean'], 0.1)

    def test_no_trigger_ever(self):
        h = mo.history_of_gate(['a', 'b', 'c'], np.array([0.1, 0.2, 0.3]), np.zeros(3), -1.5, horizon=1)
        self.assertEqual((h['days'], h['episodes'], h['last_date'], h['since_last']), (0, 0, None, None))
        self.assertNotIn('fwd_median', h)


def fake_signal(gate=False):
    return dict(gate_open=gate, fired=['A'] if gate else [], blacklist=['国防军工'],
                sleeves={'A': dict(name='大盘恐慌', gate=gate, z=-0.3, detail='全市场等权'),
                         'C': dict(name='成交额分档恐慌', gate=False, z=-0.6, detail='成交额最大档'),
                         'B': dict(name='行业恐慌', gate=False, z=-0.9, detail='有色金属')},
                industries=[dict(name='国防军工', z=-1.0), dict(name='有色金属', z=-0.9)],
                market_position=dict(window=120, pct=0.05, gap=-0.14, on=True, would_block=False, blocked=False),
                recent=[dict(date=f'd{i}', a=-0.1 * i, c=-0.1, b=-0.2 * i) for i in range(10)])


class OverviewTests(unittest.TestCase):
    def build(self, gate_last=True, fresh=True, holdings=None):
        panel, inp = fixture(gate_last=gate_last)
        cfg = fusion.d4_config()
        sig = fake_signal(gate=gate_last)
        signals = {'fusion4': dict(sig, picks=[{'code': 'y'}] if gate_last else []), 'market': {'gate_open': False, 'picks': [{'code': 'x'}] * 5},
                   'broken': {'error': 'boom'}}
        labels = {'fusion4': '策略 D4', 'market': '策略 A（大盘恐慌）', 'broken': '坏的'}
        return mo.build_overview(panel, inp, sig, signals, holdings, as_of='2026-10-09', plan_day='2026-10-12', fresh=fresh,
                                 labels=labels, threshold=cfg.z_threshold), sig

    def test_shape_is_plain_json_with_all_sections(self):
        ov, _ = self.build()
        for key in ('level', 'market', 'layers', 'scenarios', 'history', 'signal', 'trend', 'watch', 'caveat'):
            self.assertIn(key, ov)
        self.assertEqual([l['key'] for l in ov['layers']], ['A', 'C', 'B'])
        self.assertEqual([b['kind'] for b in ov['signal']['books']], ['fusion4', 'market'])   # 出错的账不进来
        json.dumps(ov, allow_nan=False, default=lambda x: None if isinstance(x, float) and not math.isfinite(x) else float(x))

    def test_gate_closed_book_reports_no_picks(self):
        ov, _ = self.build()
        market = next(b for b in ov['signal']['books'] if b['kind'] == 'market')
        self.assertEqual((market['gate_open'], market['n_picks'], market['n_plan']), (False, 0, 0))

    def test_stale_data_and_holiday_gap_are_warned(self):
        ov, _ = self.build(fresh=False)
        titles = [w['title'] for w in ov['watch']]
        self.assertIn('数据还没更新', titles)
        self.assertEqual(ov['calendar_gap_days'], 3)
        self.assertNotIn('下一个开盘日隔着休市', titles)          # 周五 → 周一是正常周末
        panel, inp = fixture()
        sig = fake_signal()
        holiday = mo.build_overview(panel, inp, sig, {'fusion4': sig}, None, as_of='2026-09-30', plan_day='2026-10-09', fresh=True,
                                    labels={}, threshold=-1.5)
        self.assertIn('下一个开盘日隔着休市', [w['title'] for w in holiday['watch']])

    def test_open_gate_leads_the_watch_list(self):
        ov, sig = self.build()
        if not any(b['gate_open'] for b in ov['signal']['books']):
            self.skipTest('夹具没有打开闸门')
        self.assertEqual(ov['watch'][0]['title'], '有触发')

    def test_sells_due_comes_from_the_d4_plan(self):
        holdings = {'n_holdings': 2, 'plans': {'D4': {'sells': [{'code': 'a'}, {'code': 'b'}]}}}
        ov, _ = self.build(gate_last=False, holdings=holdings)
        self.assertEqual((ov['signal']['n_hold'], ov['signal']['sells_due']), (2, 2))
        self.assertIn('有持仓到期', [w['title'] for w in ov['watch']])

    def test_holdings_error_is_ignored(self):
        ov, _ = self.build(holdings={'error': 'x'})
        self.assertEqual((ov['signal']['n_hold'], ov['signal']['sells_due']), (0, 0))


if __name__ == '__main__':
    unittest.main()
