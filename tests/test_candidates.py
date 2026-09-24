"""Candidate screens and their historical check, on feature tables with known outcomes."""
import unittest
from datetime import date, timedelta

import polars as pl

from quantlab.trading.candidates import HOLD_SESSIONS, ROUND_TRIP_COST, RULES, screen_candidates

DAYS = [date(2025, 1, 1) + timedelta(days=i) for i in range(260)]


def features(edge, *, one_word_winner=False):
    """Ten stocks per day; stock 0 is a 首板 every day and earns `edge` over the others."""
    rows = []
    for d in DAYS:
        for k in range(10):
            winner = k == 0
            rows.append({
                'date': d, 'code': f'sh.60000{k}', 'name': f'股{k}', 'industry': '行业',
                'tradable': True, 'is_st': False, 'pct': 0.1 if winner else 0.0,
                'streak': 1 if winner else 0, 'rank20': 0.5, 'ma20_gap': 0.0, 'ma60_gap': 0.0,
                'high60_gap': -0.2, 'amount_ratio': 1.0, 'ret5': 0.0, 'ret20': 0.0, 'ret60': 0.0,
                'fwd5': (edge if winner else 0.0) + (0.001 * (DAYS.index(d) % 3)),
                'next_tradable': True, 'next_one_word': one_word_winner and winner,
            })
    return pl.DataFrame(rows)


def rule(result, key):
    return next(r for r in result if r['key'] == key)


class CandidateTests(unittest.TestCase):
    def test_rules_are_documented(self):
        self.assertEqual(len({r.key for r in RULES}), len(RULES))
        self.assertTrue(all(r.description for r in RULES))

    def test_positive_edge_is_found_after_costs(self):
        # MIN_SELECTED=3 needs at least three picks per day: make three first boards.
        frame = features(0.0).with_columns(
            pl.when(pl.col('code').is_in(['sh.600000', 'sh.600001', 'sh.600002'])).then(1).otherwise(0).alias('streak'),
            (pl.when(pl.col('code').is_in(['sh.600000', 'sh.600001', 'sh.600002'])).then(0.02).otherwise(0.0)
             + pl.col('fwd5')).alias('fwd5'))
        result = screen_candidates(frame, DAYS[-1], DAYS)
        first = rule(result, 'first_board')
        self.assertEqual(first['count'], 3)
        v = first['validation']
        self.assertEqual(v['verdict'], 'positive', v)
        self.assertAlmostEqual(v['mean_excess'], 0.02 - 0.02 * 3 / 10, places=4)
        self.assertAlmostEqual(v['net_excess'], v['mean_excess'] - ROUND_TRIP_COST, places=6)
        # Non-overlapping samples: one signal every HOLD_SESSIONS sessions after warm-up, minus the tail.
        self.assertEqual(v['samples'], len(DAYS[60:-HOLD_SESSIONS][::HOLD_SESSIONS]))
        self.assertIn('扣约0.2%往返成本后', v['text'])

    def test_no_edge_is_unclear_and_too_few_picks_is_insufficient(self):
        result = screen_candidates(features(0.0), DAYS[-1], DAYS)
        first = rule(result, 'first_board')
        self.assertEqual(first['count'], 1)
        # Only one pick per day (< MIN_SELECTED): no reliable daily average.
        self.assertEqual(first['validation']['verdict'], 'insufficient')

    def test_unbuyable_one_word_opens_are_excluded(self):
        frame = features(0.05, one_word_winner=True).with_columns(
            pl.when(pl.col('code').is_in(['sh.600000', 'sh.600001', 'sh.600002'])).then(1).otherwise(0).alias('streak'))
        result = screen_candidates(frame, DAYS[-1], DAYS)
        v = rule(result, 'first_board')['validation']
        # sh.600000 (the one-word winner) is dropped; the two remaining picks are below MIN_SELECTED.
        self.assertEqual(v['verdict'], 'insufficient')

    def test_st_and_suspended_stocks_are_never_candidates(self):
        frame = features(0.0).with_columns(
            pl.when(pl.col('code') == 'sh.600000').then(True).otherwise(False).alias('is_st'))
        self.assertEqual(rule(screen_candidates(frame, DAYS[-1], DAYS), 'first_board')['count'], 0)
        frame = features(0.0).with_columns(
            pl.when(pl.col('code') == 'sh.600000').then(False).otherwise(True).alias('tradable'))
        self.assertEqual(rule(screen_candidates(frame, DAYS[-1], DAYS), 'first_board')['count'], 0)


if __name__ == '__main__':
    unittest.main()
