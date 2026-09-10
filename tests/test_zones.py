import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
from polars.testing import assert_frame_equal

from quantlab.causal import assert_prefix_invariant
from quantlab.factors.engine import compute_factor
from quantlab.factors.zones import FVGActiveCount, FVGBearCreated, FVGBullCreated
from quantlab.zones.fvg import FVGZoneEngine


def bars(ranges, symbol="A"):
    times = [datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=i) for i in range(len(ranges))]
    return pl.DataFrame({"symbol": [symbol] * len(ranges), "datetime": times, "available_at": times,
        "timeframe": ["1d"] * len(ranges), "high": [float(hi) for lo, hi in ranges],
        "low": [float(lo) for lo, hi in ranges], "open": [(lo + hi) / 2 for lo, hi in ranges],
        "close": [(lo + hi) / 2 for lo, hi in ranges], "volume": [100.0] * len(ranges), "turnover": [1000.0] * len(ranges)})


class ZoneTests(unittest.TestCase):
    def test_both_directions_creation_partial_fill_and_terminal_state(self):
        ranges = [(9, 10), (10, 12), (12, 13), (11, 13), (11.5, 13), (9.5, 12)]
        for direction, prices in [(1, ranges), (-1, [(30-hi, 30-lo) for lo, hi in ranges])]:
            with self.subTest(direction=direction):
                frame = bars(prices)
                analysis = FVGZoneEngine().analyze(frame)
                self.assertEqual(len(analysis.zones), 1)
                zone = analysis.zones[0]
                self.assertEqual(zone.direction, direction)
                self.assertEqual(zone.created_at, frame["datetime"][2])
                self.assertEqual(zone.available_at, frame["available_at"][2])
                self.assertIsNone(zone.invalidated_at)
                self.assertEqual([u.filled_ratio for u in analysis.updates], [0.0, 0.5, 0.5, 1.0])
                self.assertEqual([u.touch_count for u in analysis.updates], [0, 1, 2, 3])
                self.assertEqual([u.status for u in analysis.updates], ["active", "active", "active", "filled"])
                self.assertEqual(analysis.counts["active_count"].to_list(), [None, None, 1, 1, 1, 0])
                self.assertEqual(FVGZoneEngine().detect(frame), list(analysis.zones))

    def test_jump_over_zone_invalidates_without_assuming_fill(self):
        frame = bars([(9, 10), (10, 12), (12, 13), (8, 9), (10, 13)])
        analysis = FVGZoneEngine().analyze(frame)
        original = next(z for z in analysis.zones if z.direction == 1)
        updates = [u for u in analysis.updates if u.zone_id == original.zone_id]
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[-1].status, "invalidated")
        self.assertEqual(updates[-1].touch_count, 0)
        self.assertEqual(updates[-1].filled_ratio, 0.0)
        self.assertEqual(updates[-1].available_at, frame["available_at"][3])

    def test_equality_is_not_a_gap_boundary_touch_is_not_fill(self):
        self.assertEqual(FVGZoneEngine().detect(bars([(9, 10), (10, 11), (10, 12)])), [])
        analysis = FVGZoneEngine().analyze(bars([(9, 10), (10, 12), (12, 13), (12, 13)]))
        self.assertEqual(analysis.updates[-1].touch_count, 1)
        self.assertEqual(analysis.updates[-1].filled_ratio, 0.0)
        self.assertEqual(analysis.updates[-1].status, "active")

    def test_lifecycle_and_factors_are_prefix_invariant(self):
        frame = bars([(9, 10), (10, 12), (12, 13), (11, 13), (11.5, 13), (9.5, 12)])
        full = FVGZoneEngine().analyze(frame)
        for n in range(2, 6):
            prefix = FVGZoneEngine().analyze(frame.head(n))
            cutoff = frame["available_at"][n-1]
            self.assertEqual(prefix.zones, tuple(z for z in full.zones if z.available_at <= cutoff))
            self.assertEqual(prefix.updates, tuple(u for u in full.updates if u.available_at <= cutoff))
            assert_frame_equal(prefix.counts, full.counts.head(n), check_exact=True)
        for factor in (FVGBullCreated(), FVGBearCreated(), FVGActiveCount()):
            assert_prefix_invariant(factor, frame, {}, frame["available_at"].to_list()[1:-1])

    def test_symbol_isolation_order_and_parameter_contract(self):
        frame = pl.concat([bars([(9, 10), (10, 12), (12, 13), (11, 13)]), bars([(20, 21)] * 4, "B")])
        engine = FVGZoneEngine()
        first, second = engine.analyze(frame), engine.analyze(frame.reverse())
        self.assertEqual(first.zones, second.zones)
        self.assertEqual(first.updates, second.updates)
        assert_frame_equal(first.counts, second.counts, check_exact=True)
        result = compute_factor(FVGActiveCount(), frame, {})
        self.assertEqual(result.filter(pl.col("symbol") == "B")["value"].to_list(), [None, None, 0.0, 0.0])
        for factor in (FVGBullCreated(), FVGBearCreated(), FVGActiveCount()):
            with self.assertRaisesRegex(ValueError, "no parameters"):
                factor.parameters({"lookback": 20})

    def test_delayed_bar_availability_is_kept(self):
        frame = bars([(9, 10), (10, 12), (12, 13)]).with_columns((pl.col("available_at") + pl.duration(minutes=5)).alias("available_at"))
        zone = FVGZoneEngine().detect(frame)[0]
        self.assertEqual(zone.available_at, zone.created_at + timedelta(minutes=5))


if __name__ == "__main__":
    unittest.main()
