"""R-Breaker 验证脚本的规则引擎：公式、线的顺序、状态机的触发条件与成交时点（无未来函数）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts', 'research', 'rbreaker'))

import numpy as np

import rb


def bars(closes, spread=0.0):
    c = np.array(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    return o, np.maximum(o, c) + spread, np.minimum(o, c) - spread, c


class FormulaTests(unittest.TestCase):
    def test_pivot_formulas_by_hand(self):
        ln = rb.lines(12.0, 9.0, 11.0, 'pivot')          # P = 32/3
        p = 32 / 3
        self.assertAlmostEqual(float(ln['Bbreak']), 12 + 2 * (p - 9))
        self.assertAlmostEqual(float(ln['Ssetup']), p + 3)
        self.assertAlmostEqual(float(ln['Senter']), 2 * p - 9)
        self.assertAlmostEqual(float(ln['Benter']), 2 * p - 12)
        self.assertAlmostEqual(float(ln['Bsetup']), p - 3)
        self.assertAlmostEqual(float(ln['Sbreak']), 9 - 2 * (12 - p))

    def test_pivot_width_is_three_times_prev_range(self):
        # 因子化时 (Bbreak-Sbreak) 恒等于 3(H-L)：区间位置因子就是“相对昨日振幅的价格偏离”
        rng = np.random.default_rng(1)
        h = 10 + rng.random(50)
        l = h - rng.random(50) - 0.1
        c = l + (h - l) * rng.random(50)
        ln = rb.lines(h, l, c, 'pivot')
        np.testing.assert_allclose(ln['Bbreak'] - ln['Sbreak'], 3 * (h - l))

    def test_line_order_both_variants(self):
        rng = np.random.default_rng(2)
        h = 10 + rng.random(200)
        l = h - rng.random(200) - 0.1
        c = l + (h - l) * rng.random(200)
        for v in ('pivot', 'classic'):
            ln = rb.lines(h, l, c, v)
            order = [ln[k] for k in ('Bbreak', 'Ssetup', 'Senter', 'Benter', 'Bsetup', 'Sbreak')]
            for a, b in zip(order, order[1:]):
                self.assertTrue(np.all(a > b), v)

    def test_classic_formulas_by_hand(self):
        ln = rb.lines(12.0, 9.0, 11.0, 'classic')
        ss, bs = 12 + 0.35 * 2, 9 - 0.35 * 1
        self.assertAlmostEqual(float(ln['Ssetup']), ss)
        self.assertAlmostEqual(float(ln['Bsetup']), bs)
        self.assertAlmostEqual(float(ln['Bbreak']), ss + 0.25 * (ss - bs))
        self.assertAlmostEqual(float(ln['Senter']), 1.07 / 2 * 21 - 0.07 * 9)
        self.assertAlmostEqual(float(ln['Benter']), 1.07 / 2 * 21 - 0.07 * 12)
        self.assertAlmostEqual(float(ln['Sbreak']), bs - 0.25 * (ss - bs))


LN = dict(Bbreak=110.0, Ssetup=105.0, Senter=102.0, Benter=98.0, Bsetup=95.0, Sbreak=90.0)


class MachineTests(unittest.TestCase):
    def test_breakout_long_enters_next_bar_open_and_exits_at_the_close(self):
        o, h, l, c = bars([100, 100, 111, 112, 113])
        trades = rb.run_day(o, h, l, c, LN)
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual((t.kind, t.side, t.entry_i, t.exit_i), ('brk_long', 1, 3, 4))
        self.assertEqual(t.entry, o[3])                # 信号根 i=2 的收盘 111 > 110，成交在第 3 根开盘，不是 111
        self.assertEqual(t.exit, c[4])

    def test_breakout_short_and_no_short_flag(self):
        o, h, l, c = bars([100, 100, 89, 88, 87])
        self.assertEqual([t.kind for t in rb.run_day(o, h, l, c, LN)], ['brk_short'])
        self.assertEqual(rb.run_day(o, h, l, c, LN, allow_short=False), [])

    def test_reversal_needs_the_setup_first_then_the_enter_line(self):
        # 冲高到 Ssetup 之上再回落到 Senter 之下才反手；先多头（突破 110），后来 107 → 101 才触发
        o, h, l, c = bars([100, 111, 111, 107, 101, 100])
        trades = rb.run_day(o, h, l, c, LN)
        self.assertEqual([(t.kind, t.side) for t in trades], [('brk_long', 1), ('rev_short', -1)])
        self.assertEqual(trades[0].exit_i, trades[1].entry_i)
        self.assertEqual(trades[0].exit, trades[1].entry)

    def test_no_reversal_without_having_been_above_setup(self):
        ln = dict(LN, Bbreak=130.0)
        o, h, l, c = bars([100, 101, 104, 101, 100])      # 最高没到 105，跌破 102 也不反转
        self.assertEqual(rb.run_day(o, h, l, c, ln), [])

    def test_reverse_long_after_short(self):
        o, h, l, c = bars([100, 89, 88, 93, 99, 100])
        trades = rb.run_day(o, h, l, c, LN)
        self.assertEqual([(t.kind, t.side) for t in trades], [('brk_short', -1), ('rev_long', 1)])

    def test_long_only_reversal_closes_without_flipping(self):
        o, h, l, c = bars([100, 111, 111, 107, 101, 100])
        trades = rb.run_day(o, h, l, c, LN, allow_short=False)
        self.assertEqual([t.side for t in trades], [1])

    def test_first_entry_gate_and_last_bar_never_enters(self):
        o, h, l, c = bars([100, 111, 100, 100])
        self.assertEqual([t.kind for t in rb.run_day(o, h, l, c, LN)], ['brk_long', 'rev_short'])     # 突破后回落到 Senter 以下 → 反手
        self.assertEqual(rb.run_day(o, h, l, c, LN, first_entry=3), [])
        o, h, l, c = bars([100, 100, 100, 111])           # 最后一根才突破：不能再进场
        self.assertEqual(rb.run_day(o, h, l, c, LN), [])

    def test_trade_return_signs(self):
        self.assertAlmostEqual(rb.Trade('x', 0, 1, 100, 110, 1).ret, 0.1)
        self.assertAlmostEqual(rb.Trade('x', 0, 1, 100, 110, -1).ret, -0.1)


class LongOnlyTests(unittest.TestCase):
    def test_rev_long_needs_low_below_bsetup_before_close_above_benter(self):
        o, h, l, c = bars([100, 94, 96, 99, 100])
        self.assertEqual(rb.first_rev_long(o, h, l, c, LN), (3, o[4]))
        o, h, l, c = bars([100, 99, 99, 99, 100])         # 没跌到 Bsetup=95
        self.assertIsNone(rb.first_rev_long(o, h, l, c, LN))

    def test_brk_long_first_trigger(self):
        o, h, l, c = bars([100, 111, 120, 99, 100])
        self.assertEqual(rb.first_brk_long(o, h, l, c, LN), (1, o[2]))


class MatrixTests(unittest.TestCase):
    def test_matrix_versions_match_the_scalar_state_machine(self):
        rng = np.random.default_rng(7)
        D, n = 300, 48
        base = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, (D, n)), axis=1))
        o = np.concatenate([base[:, :1], base[:, :-1]], axis=1)
        c = base
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, (D, n))))
        l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, (D, n))))
        m = c.mean(1)
        H, L, C = m * 1.004, m * 0.996, m                 # 窄一点的“前一日”区间，保证两个版本在随机数据里都会触发
        for variant in ('pivot', 'classic'):
            ln = rb.lines(H, L, C, variant)
            b = rb.first_brk_long_mat(c, ln['Bbreak'])
            r = rb.first_rev_long_mat(l, c, ln['Bsetup'], ln['Benter'])
            hit = 0
            for d in range(D):
                one = {k: float(v[d]) for k, v in ln.items()}
                s1 = rb.first_brk_long(o[d], h[d], l[d], c[d], one)
                s2 = rb.first_rev_long(o[d], h[d], l[d], c[d], one)
                self.assertEqual(-1 if s1 is None else s1[0], b[d])
                self.assertEqual(-1 if s2 is None else s2[0], r[d])
                hit += (s1 is not None) + (s2 is not None)
            self.assertGreater(hit, 5, variant)          # 随机数据里要真有触发，否则这个测试什么也没比


if __name__ == '__main__':
    unittest.main()
