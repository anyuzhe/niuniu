from datetime import date, timedelta
import itertools
import unittest

import polars as pl

from quantlab.trading.limit_states import annotate_limit_states, regime_columns
from quantlab.trading.price_limit_regime import limit_rule


def bar(day, code='sh.600001', preclose=10.0, o=None, h=None, l=None, c=None, *, tradable=True, st=False, **extra):
    c = preclose if c is None else c
    o = c if o is None else o
    h = max(o, c) if h is None else h
    l = min(o, c) if l is None else l
    row = dict(date=day, code=code, open=o if tradable else None, high=h if tradable else None,
               low=l if tradable else None, close=c if tradable else None, preclose=preclose, tradable=tradable, is_st=st)
    row.update(extra)
    return row


def annotate(rows):
    return annotate_limit_states(pl.DataFrame(rows))


class RegimeEquivalenceTests(unittest.TestCase):
    def test_vectorized_regime_matches_scalar_rule_on_boundary_grid(self):
        symbols = ['sh.600001', 'sz.002001', 'sz.300001', 'sz.302001', 'sh.688001', 'sh.689009', 'bj.920001', 'sh.900901']
        days = [date(2019, 7, 19), date(2019, 7, 22), date(2020, 8, 21), date(2020, 8, 24), date(2021, 11, 12),
                date(2021, 11, 15), date(2023, 4, 7), date(2023, 4, 10), date(2026, 7, 3), date(2026, 7, 6)]
        listings = [(None, None), (None, 1), (None, 6)]
        for offset in (-3, 0, 2, 25):
            listings.extend([('offset', offset, None), ('offset', offset, 1), ('offset', offset, 3), ('offset', offset, 7)])
        rows, expected = [], []
        for symbol, day, st, listing, delisting in itertools.product(symbols, days, (False, True), listings, (None, 30, 31)):
            if listing[0] == 'offset':
                listing_date, since = day - timedelta(days=listing[1]), listing[2]
            else:
                listing_date, since = listing
            rows.append(dict(date=day, code=symbol, open=10.0, high=10.0, low=10.0, close=10.0, preclose=10.0,
                             tradable=True, is_st=st, listing_date=listing_date, sessions_since_listing=since,
                             sessions_to_delisting=delisting))
            expected.append(limit_rule(symbol, day, is_st=st, listing_date=listing_date,
                                       sessions_since_listing=since, sessions_to_delisting=delisting))
        schema = {'date': pl.Date, 'code': pl.String, 'open': pl.Float64, 'high': pl.Float64, 'low': pl.Float64,
                  'close': pl.Float64, 'preclose': pl.Float64, 'tradable': pl.Boolean, 'is_st': pl.Boolean,
                  'listing_date': pl.Date, 'sessions_since_listing': pl.Int64, 'sessions_to_delisting': pl.Int64}
        # The grid intentionally repeats code/date pairs, so evaluate the regime expressions directly.
        frame = regime_columns(pl.DataFrame(rows, schema=schema))
        actual = frame.select('board', 'limit_rule_status', 'limit_rule_reason', 'limit_rate', 'listing_window_checked').to_dicts()
        mismatches = [(rows[i], expected[i], got) for i, got in enumerate(actual)
                      if (got['board'], got['limit_rule_status'], got['limit_rule_reason'], got['limit_rate'], got['listing_window_checked'])
                      != (expected[i]['board'], expected[i]['status'], expected[i]['reason'], expected[i]['rate'], expected[i]['listing_window_checked'])]
        self.assertGreater(len(rows), 9000)
        self.assertEqual(mismatches[:3], [])


class PatternTests(unittest.TestCase):
    def one(self, row):
        return annotate([row]).row(0, named=True)

    def test_close_touch_broken_one_word_and_t_board(self):
        day = date(2026, 9, 16)
        sealed = self.one(bar(day, o=10.5, h=11.0, l=10.4, c=11.0))
        self.assertEqual((sealed['limit_up_price'], sealed['limit_down_price']), (11.0, 9.0))
        self.assertTrue(sealed['is_limit_up_close'] and sealed['touched_limit_up'])
        self.assertFalse(sealed['is_broken_board'] or sealed['is_one_word_limit_up'] or sealed['is_t_board'])
        broken = self.one(bar(day, o=10.2, h=11.0, l=10.1, c=10.8))
        self.assertTrue(broken['touched_limit_up'] and broken['is_broken_board'])
        self.assertFalse(broken['is_limit_up_close'])
        word = self.one(bar(day, o=11.0, h=11.0, l=11.0, c=11.0))
        self.assertTrue(word['is_one_word_limit_up']);self.assertFalse(word['is_t_board'])
        t_board = self.one(bar(day, o=11.0, h=11.0, l=10.5, c=11.0))
        self.assertTrue(t_board['is_t_board']);self.assertFalse(t_board['is_one_word_limit_up'])

    def test_limit_down_sky_to_ground_and_ground_to_sky(self):
        day = date(2026, 9, 16)
        down = self.one(bar(day, o=9.5, h=9.6, l=9.0, c=9.0))
        self.assertTrue(down['is_limit_down_close'] and down['touched_limit_down'])
        sky_to_ground = self.one(bar(day, o=10.5, h=11.0, l=9.0, c=9.0))
        self.assertTrue(sky_to_ground['is_limit_up_to_down']);self.assertFalse(sky_to_ground['is_limit_down_to_up'])
        ground_to_sky = self.one(bar(day, o=9.2, h=11.0, l=9.0, c=11.0))
        self.assertTrue(ground_to_sky['is_limit_down_to_up']);self.assertFalse(ground_to_sky['is_limit_up_to_down'])

    def test_rounding_regime_changes_and_violation_flag(self):
        rounded = self.one(bar(date(2026, 9, 16), preclose=9.95, o=10.0, h=10.95, l=9.99, c=10.95))
        self.assertEqual((rounded['limit_up_price'], rounded['limit_down_price']), (10.95, 8.96))
        self.assertTrue(rounded['is_limit_up_close'])
        st_before = self.one(bar(date(2026, 7, 3), o=10.2, h=10.5, l=10.1, c=10.5, st=True))
        st_after = self.one(bar(date(2026, 7, 6), o=10.2, h=10.5, l=10.1, c=10.5, st=True))
        self.assertTrue(st_before['is_limit_up_close']);self.assertFalse(st_after['is_limit_up_close'])
        chinext_before = self.one(bar(date(2020, 8, 21), code='sz.300001', o=10.5, h=11.0, l=10.4, c=11.0))
        chinext_after = self.one(bar(date(2020, 8, 24), code='sz.300001', o=10.5, h=12.0, l=10.4, c=12.0))
        self.assertTrue(chinext_before['is_limit_up_close'] and chinext_after['is_limit_up_close'])
        violation = self.one(bar(date(2026, 9, 16), o=10.5, h=11.5, l=10.4, c=11.2))
        self.assertTrue(violation['limit_price_violation'])
        self.assertFalse(self.one(bar(date(2026, 9, 16), o=10.5, h=11.0, l=9.0, c=10.0))['limit_price_violation'])

    def test_no_limit_unmodeled_and_suspended_rows_have_no_inferred_states(self):
        ipo = self.one(bar(date(2026, 9, 16), code='sh.688001', o=30.0, h=60.0, l=28.0, c=50.0, preclose=20.0,
                           listing_date=date(2026, 9, 16), sessions_since_listing=1))
        self.assertEqual((ipo['limit_rule_status'], ipo['limit_up_price'], ipo['is_limit_up_close'], ipo['limit_up_streak']),
                         ('NO_LIMIT', None, None, 0))
        unknown = self.one(bar(date(2026, 9, 16), code='sh.900901', o=1.0, h=1.1, l=1.0, c=1.1, preclose=1.0))
        self.assertEqual((unknown['limit_rule_status'], unknown['limit_up_price']), ('UNMODELED', None))
        suspended = self.one(bar(date(2026, 9, 16), tradable=False))
        self.assertIsNone(suspended['is_limit_up_close']);self.assertIsNone(suspended['limit_up_streak'])


class SequenceTests(unittest.TestCase):
    def test_streak_skips_suspension_and_counts_rolling_windows(self):
        start = date(2026, 9, 1);rows = [];close = 10.0
        plan = ['flat', 'up', 'up', 'suspend', 'up', 'broken', 'up', 'up', 'up', 'up', 'up', 'up']
        for i, kind in enumerate(plan):
            day = start + timedelta(days=i)
            if kind == 'suspend':
                rows.append(bar(day, preclose=close, tradable=False));continue
            if kind == 'up':
                limit = round(close * 1.1 + 1e-9, 2);rows.append(bar(day, preclose=close, o=close, h=limit, l=close, c=limit));close = limit
            elif kind == 'broken':
                limit = round(close * 1.1 + 1e-9, 2);rows.append(bar(day, preclose=close, o=close, h=limit, l=close, c=close));
            else:
                rows.append(bar(day, preclose=close))
        out = annotate(rows).sort('date')
        streak = out['limit_up_streak'].to_list()
        self.assertEqual(streak, [0, 1, 2, None, 3, 0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(out['is_first_board'].to_list()[6], True)
        self.assertEqual(out['prev_is_broken_board'].to_list()[6], True)
        self.assertEqual(out['prev_limit_up_streak'].to_list()[4], 2)
        self.assertEqual(out['limit_ups_5d'].to_list()[-1], 5)
        self.assertEqual(out['limit_ups_10d'].to_list()[-1], 9)

    def test_multiple_codes_are_independent(self):
        rows = [bar(date(2026, 9, 15), code='sh.600001', o=10.0, h=11.0, l=10.0, c=11.0),
                bar(date(2026, 9, 15), code='sz.000001', o=10.0, h=10.2, l=9.9, c=10.1),
                bar(date(2026, 9, 16), code='sh.600001', preclose=11.0, o=11.0, h=12.1, l=11.0, c=12.1),
                bar(date(2026, 9, 16), code='sz.000001', preclose=10.1, o=10.1, h=11.11, l=10.1, c=11.11)]
        out = {(r['code'], r['date']): r for r in annotate(rows).iter_rows(named=True)}
        self.assertEqual(out[('sh.600001', date(2026, 9, 16))]['limit_up_streak'], 2)
        self.assertEqual(out[('sz.000001', date(2026, 9, 16))]['limit_up_streak'], 1)
        self.assertTrue(out[('sz.000001', date(2026, 9, 16))]['is_first_board'])


class ValidationTests(unittest.TestCase):
    def test_invalid_panels_fail_closed(self):
        good = bar(date(2026, 9, 16))
        with self.assertRaises(ValueError):annotate_limit_states([good])
        with self.assertRaises(ValueError):annotate([{k: v for k, v in good.items() if k != 'preclose'}])
        with self.assertRaises(ValueError):annotate([good, dict(good)])
        with self.assertRaises(ValueError):annotate([{**good, 'code': '600001'}])
        with self.assertRaises(ValueError):annotate([{**good, 'close': None}])
        with self.assertRaises(ValueError):annotate([{**good, 'high': 9.0, 'close': 10.0}])
        with self.assertRaises(ValueError):annotate([{**good, 'sessions_since_listing': 0}])


if __name__ == '__main__':
    unittest.main()
