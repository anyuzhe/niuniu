import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
from polars.testing import assert_frame_equal

from quantlab.app import default_registry
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot
from quantlab.domain import Timeframe
from quantlab.multitimeframe.engine import MultiTimeframeEngine, align_context
from quantlab.storage.codec import digest


def at(day, hour=15):
    return datetime(2025, 1, day, hour, tzinfo=ZoneInfo("Asia/Shanghai"))


def bars(times, timeframe, prices):
    return pl.DataFrame({"symbol": ["A"]*len(times), "datetime": times, "available_at": times,
        "timeframe": [timeframe]*len(times), "open": prices, "close": prices,
        "high": [p+1 for p in prices], "low": [p-1 for p in prices],
        "volume": [100.]*len(times), "turnover": [1000.]*len(times)})


class Provider:
    def __init__(self):
        self.calls = []
        self.daily = bars([at(1), at(2), at(3)], "1d", [10., 11., 12.])
        self.minute = bars([at(1,10), at(2,10), at(2), at(3,10)], "5m", [10., 11., 11., 12.])

    def load(self, request):
        self.calls.append(request)
        frame = self.daily if request.timeframe == Timeframe.DAILY else self.minute
        frame = frame.filter(pl.col("datetime").dt.date().is_between(request.start, request.end))
        return DataBatch(frame, DataSnapshot(digest(frame.write_json()), "fixture", "raw", ()))


class MultiTimeframeTests(unittest.TestCase):
    def test_boundaries_symbols_missing_and_delayed_confirmation(self):
        low = pl.DataFrame({"symbol": ["A", "A", "A", "A", "B"],
            "datetime": [at(1,10), at(1), at(2,10), at(2), at(2)],
            "available_at": [at(1,10), at(1), at(2,10), at(2), at(2)]})
        high = pl.DataFrame({"symbol": ["A", "A"], "datetime": [at(1), at(2)],
            "available_at": [at(1), at(2)], "value": [3., None]})
        output = align_context(low.reverse(), high.reverse())
        self.assertEqual(output["context_value"].to_list(), [None, 3., 3., None, None])
        self.assertEqual(output["context_datetime"].to_list(), [None, at(1), at(1), at(2), None])
        delayed = high.with_columns((pl.col("available_at") + timedelta(hours=1)).alias("available_at"))
        output = align_context(low, delayed)
        self.assertEqual(output["context_value"].to_list(), [None, None, 3., 3., None])
        self.assertFalse(output.filter(pl.col("context_available_at") > pl.col("available_at")).height)
        empty = align_context(low, high.head(0))
        self.assertEqual(empty.height, low.height)
        self.assertEqual(empty["context_value"].null_count(), low.height)

    def test_ambiguous_times_and_naive_times_rejected(self):
        high = pl.DataFrame({"symbol": ["A", "A"], "datetime": [at(1), at(2)],
            "available_at": [at(2), at(2)], "value": [1., 2.]})
        low = high.select("symbol", "datetime", "available_at")
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            align_context(low, high)
        naive = low.with_columns(pl.col("datetime").dt.replace_time_zone(None), pl.col("available_at").dt.replace_time_zone(None))
        with self.assertRaisesRegex(ValueError, "timezone aware"):
            align_context(naive, high)

    def test_loader_snapshots_repeatability_and_future_invariance(self):
        provider = Provider()
        engine = MultiTimeframeEngine(provider, default_registry())
        low = DataRequest(("A",), Timeframe.MIN5, date(2025,1,1), date(2025,1,3))
        high = replace(low, timeframe=Timeframe.DAILY)
        a = engine.load(low, high, "BASE.MOMENTUM", parameters={"lookback": 1})
        b = engine.load(low, high, "BASE.MOMENTUM", parameters={"lookback": 1})
        self.assertEqual(a.context_id, b.context_id)
        assert_frame_equal(a.frame, b.frame, check_exact=True)
        self.assertEqual(a.frame["context_datetime"].to_list(), [None, at(1), at(2), at(2)])
        self.assertIsNone(a.frame["context_value"][1])
        self.assertAlmostEqual(a.frame["context_value"][2], .1)
        provider.daily = provider.daily.with_columns([
            pl.when(pl.col("datetime") == at(3)).then(pl.col(c)*10).otherwise(pl.col(c)).alias(c)
            for c in ("open", "high", "low", "close")])
        changed = engine.load(low, high, "BASE.MOMENTUM", parameters={"lookback": 1})
        assert_frame_equal(a.frame, changed.frame, check_exact=True)
        self.assertNotEqual(a.context_id, changed.context_id)
        end = date(2025,1,2)
        prefix = engine.load(replace(low, end=end), replace(high, end=end), "BASE.MOMENTUM", parameters={"lookback": 1})
        assert_frame_equal(a.frame.filter(pl.col("datetime").dt.date() <= end), prefix.frame, check_exact=True)
        calls = len(provider.calls)
        with self.assertRaisesRegex(ValueError, "higher timeframe"):
            engine.load(high, low, "BASE.MOMENTUM")
        with self.assertRaisesRegex(ValueError, "cover"):
            engine.load(low, replace(high, start=date(2025,1,2)), "BASE.MOMENTUM")
        self.assertEqual(len(provider.calls), calls)


if __name__ == "__main__":
    unittest.main()
