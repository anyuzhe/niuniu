import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.causal import assert_prefix_invariant
from quantlab.data.base import ExplicitUniverse
from quantlab.events.breakout import BreakoutHighEngine
from quantlab.experiments.research import FactorResearchEngine
from quantlab.factors.engine import compute_factor
from quantlab.factors.technical import BreakoutHigh, PivotHighConfirmed
from quantlab.structure.pivots import ConfirmedPivotEngine


def bars(closes, symbol="A"):
    times = [datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=i) for i in range(len(closes))]
    return pl.DataFrame({"symbol": [symbol] * len(closes), "datetime": times, "available_at": times,
        "timeframe": ["1d"] * len(closes), "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [100.0] * len(closes), "turnover": [1000.0] * len(closes)})


class TechnicalTests(unittest.TestCase):
    def test_pivots_occur_earlier_but_only_trigger_on_confirmation(self):
        frame = bars([1.0, 3.0, 2.0, 4.0, 1.0])
        engine = ConfirmedPivotEngine(1, 1)
        objects = engine.detect(frame)
        highs = [s for s in objects if s.kind == "pivot_high"]
        self.assertEqual([s.price for s in highs], [3.0, 4.0])
        self.assertEqual(highs[0].occurred_at, frame["datetime"][1])
        self.assertEqual(highs[0].available_at, frame["datetime"][2])
        self.assertEqual(objects, engine.detect(frame.reverse()))
        output = compute_factor(PivotHighConfirmed(), frame, {"left": 1, "right": 1})
        self.assertEqual(output["value"].to_list(), [None, None, 1.0, 0.0, 1.0])
        self.assertEqual(engine.detect(frame.head(2)), [])
        for n in (3, 4):
            self.assertEqual(engine.detect(frame.head(n)), [s for s in objects if s.available_at <= frame["available_at"][n-1]])
        assert_prefix_invariant(PivotHighConfirmed(), frame, {"left": 1, "right": 1}, frame["datetime"].to_list()[1:-1])

    def test_ties_and_short_history_do_not_create_pivots(self):
        self.assertEqual(ConfirmedPivotEngine(1, 1).detect(bars([1.0, 3.0, 3.0, 1.0])), [])
        output = compute_factor(PivotHighConfirmed(), bars([1.0, 3.0]), {"left": 2, "right": 2})
        self.assertEqual(output["value"].to_list(), [None, None])
        with self.assertRaises(ValueError):
            PivotHighConfirmed().parameters({"right": 0})

    def test_breakout_excludes_current_high_and_equality(self):
        frame = bars([1.0, 2.0, 3.0, 3.0, 4.0])
        events = BreakoutHighEngine(2).detect(frame)
        self.assertEqual([e.occurred_at for e in events], [frame["datetime"][2], frame["datetime"][4]])
        self.assertEqual(events[0].metadata["level"], 2.0)
        self.assertEqual(events[0].strength, 0.5)
        self.assertEqual(events[0].confirmed_at, events[0].available_at)
        self.assertEqual(events, BreakoutHighEngine(2).detect(frame.reverse()))
        self.assertEqual(BreakoutHighEngine(2).detect(frame.head(4)), events[:1])
        assert_prefix_invariant(BreakoutHigh(), frame, {"lookback": 2}, frame["datetime"].to_list()[1:-1])

    def test_symbol_isolation_and_boolean_conditional_statistics(self):
        frame = pl.concat([bars([1.0, 2.0, 3.0, 3.0, 4.0]), bars([100.0] * 5, "B")])
        values = compute_factor(BreakoutHigh(), frame, {"lookback": 2})
        self.assertEqual(values.filter(pl.col("symbol") == "B")["value"].to_list(), [None, None, 0.0, 0.0, 0.0])
        metrics, _ = FactorResearchEngine().evaluate(frame, values, ExplicitUniverse(("A", "B")).mask(frame), (1,), 2, boolean_factor=True)
        self.assertEqual(metrics["1"]["triggered"]["event_count"], 2)
        self.assertEqual(metrics["1"]["triggered"]["labelled_count"], 1)
        self.assertEqual(metrics["1"]["triggered"]["mean_forward_return"], 0.0)


if __name__ == "__main__":
    unittest.main()
