"""策略说明的内容：八个策略都讲到、数字取自配置、表格行列对齐。"""
import os
import sys
import unittest
from importlib.util import find_spec

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(__file__))

from dataclasses import replace

from quantlab.dipbuy import engine, fusion

if find_spec('PyQt6'):
    from quantlab.desktop import strategy_guide as guide
else:
    guide = None


@unittest.skipUnless(guide, 'PyQt6 not installed')
class GuideTests(unittest.TestCase):
    def flat(self, **kw):
        return '\n'.join(str(b) for _, blocks in guide.sections(**kw) for b in blocks)

    def test_every_strategy_and_topic_is_covered(self):
        titles = [t for t, _ in guide.sections()]
        for needle in ('先看这一页', '共同规则', 'A　', 'B　', 'C　', 'D　', 'D1　', 'D2　', 'D3　', 'D4　', '每天怎么用', '回测数字', '试过但没用', '风险与局限', '术语'):
            self.assertTrue(any(needle in t for t in titles), needle)

    def test_tables_are_rectangular(self):
        for _, blocks in guide.sections():
            for block in blocks:
                if block[0] == 'table':
                    self.assertTrue(all(len(r) == len(block[1]) for r in block[2]), block[1])
        self.assertTrue(all(len(r) == len(guide.RESULT_HEAD) for r in guide.RESULTS))

    def test_numbers_follow_the_config(self):
        text = self.flat()
        d = fusion.default_config()
        self.assertIn(f'A {d.weight_a * 100:g}%', text)
        self.assertIn(f'B {d.weight_b * 100:g}%', text)
        self.assertIn(f'{d.hold_days} 个交易日', text)
        changed = self.flat(d=replace(d, weight_b=0.03, hold_days=15), d1=replace(fusion.d1_config(), rank_k=30, hold_days=15))
        self.assertIn('B 3%', changed)
        self.assertIn('15 个交易日', changed)
        self.assertIn('前 30 只', changed)

    def test_defaults_documented_match_code(self):
        # 说明里写死的口径要和代码一致：阈值、杠杆、持有天数
        text = self.flat()
        a = engine.DipConfig()
        self.assertIn(f'{a.z_threshold:g}', text)
        self.assertIn(f'默认杠杆 {a.leverage:g} 倍', text)
        self.assertIn('含退市', text)
        self.assertIn('不下单', text)


if __name__ == '__main__':
    unittest.main()
