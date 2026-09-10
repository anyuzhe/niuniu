import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.causal import assert_prefix_invariant
from quantlab.domain import Event, Timeframe
from quantlab.factors.engine import compute_factor
from quantlab.factors.sequences import RepeatedBreakout
from quantlab.sequence.engine import EventSelector, OrderedSequenceEngine, SequenceDefinition

T = datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


def event(eid, kind, seconds, symbol="A", timeframe=Timeframe.MIN5):
    t = T + timedelta(seconds=seconds)
    return Event(eid, kind, symbol, timeframe, t, t)


def engine(steps=("A", "B"), invalidators=()):
    return OrderedSequenceEngine(SequenceDefinition("SEQ.TEST", tuple(EventSelector(s) for s in steps),
        timedelta(seconds=60), tuple(EventSelector(s) for s in invalidators)))


class SequenceTests(unittest.TestCase):
    def test_definition_rejects_mutable_or_invalid_selectors(self):
        for steps in ([EventSelector("A"), EventSelector("B")], ("A", "B")):
            with self.assertRaises(ValueError):
                SequenceDefinition("SEQ.TEST", steps, timedelta(seconds=60))

    def test_order_same_time_and_version_matching(self):
        runner = engine()
        initial = [event("a", "A", 0), event("b0", "B", 0)]
        result = runner.advance(initial[::-1], T)
        self.assertEqual([m.status for m in result], ["active"])
        self.assertEqual(result[0].event_ids, ("a",))
        self.assertEqual(runner.advance([replace(event("wrong", "B", 10), version="2.0.0")], T + timedelta(seconds=10)), [])
        completed = runner.advance([event("b", "B", 20)], T + timedelta(seconds=20))[0]
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.event_ids, ("a", "b"))
        self.assertEqual(completed.match_id, result[0].match_id)
        self.assertEqual(completed.available_at, T + timedelta(seconds=20))

    def test_timeout_boundary_and_idle_clock(self):
        runner = engine()
        result = runner.advance([event("a", "A", 0), event("b", "B", 60)], T + timedelta(seconds=60))
        self.assertEqual([m.status for m in result], ["active", "timeout"])
        self.assertEqual(result[-1].available_at, T + timedelta(seconds=60))
        runner = engine()
        runner.advance([event("a", "A", 0)], T)
        expired = runner.advance([], T + timedelta(seconds=100))
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0].status, "timeout")
        self.assertEqual(expired[0].available_at, T + timedelta(seconds=60))

    def test_invalidation_precedes_completion(self):
        runner = engine(invalidators=("X",))
        result = runner.advance([event("a", "A", 0), event("b", "B", 20), event("x", "X", 20)], T + timedelta(seconds=20))
        self.assertEqual([m.status for m in result], ["active", "invalidated"])
        self.assertEqual(result[-1].invalidating_event_id, "x")
        self.assertEqual(result[-1].event_ids, ("a",))

    def test_symbol_timeframe_isolation_and_repeated_steps(self):
        source = [event("a", "A", 0), event("other", "A", 10, "B"), event("daily", "A", 10, timeframe=Timeframe.DAILY), event("a2", "A", 20)]
        result = engine(("A", "A")).advance(source, T + timedelta(seconds=20))
        completed = [m for m in result if m.status == "completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].event_ids, ("a", "a2"))

    def test_incremental_replay_duplicates_and_atomic_rejection(self):
        source = [event("a", "A", 0), event("b", "B", 20), event("a2", "A", 30)]
        full = engine().advance(source[::-1], T + timedelta(seconds=100))
        runner = engine()
        streamed = []
        for e in source:
            streamed += runner.advance([e, e], e.available_at)
        streamed += runner.advance([], T + timedelta(seconds=100))
        self.assertEqual(full, streamed)
        self.assertEqual(runner.advance(source, T + timedelta(seconds=100)), [])
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            runner.advance([replace(source[0], strength=1)], T + timedelta(seconds=100))
        with self.assertRaisesRegex(ValueError, "Late"):
            runner.advance([event("late", "A", 50)], T + timedelta(seconds=100))
        runner = engine()
        with self.assertRaisesRegex(ValueError, "Future"):
            runner.advance(source[:2], T)
        self.assertEqual([m.status for m in runner.advance(source[:2], T + timedelta(seconds=20))], ["active", "completed"])

    def test_available_time_not_occurrence_time_drives_steps(self):
        a = replace(event("a", "A", 0), available_at=T + timedelta(seconds=30))
        b = event("b", "B", 20)
        matches = engine().advance([a, b], T + timedelta(seconds=40))
        self.assertEqual([m.status for m in matches], ["active"])
        self.assertEqual(matches[0].occurred_at, T)
        self.assertEqual(matches[0].available_at, T + timedelta(seconds=30))

    def test_factor_completion_alignment_and_causal_prefix(self):
        times = [T + timedelta(minutes=5*i) for i in range(7)]
        prices = [float(i+1) for i in range(7)]
        bars = pl.DataFrame({"symbol": ["A"]*7, "datetime": times, "available_at": times, "timeframe": ["5m"]*7,
            "open": prices, "high": prices, "low": prices, "close": prices, "volume": [100.0]*7, "turnover": [1000.0]*7})
        factor = RepeatedBreakout()
        parameters = {"lookback": 2, "max_gap_seconds": 600}
        result = compute_factor(factor, bars, parameters)
        self.assertEqual(result["value"].to_list(), [None, None, 0.0, 1.0, 0.0, 1.0, 0.0])
        assert_prefix_invariant(factor, bars, parameters, times[1:-1])
        too_short = compute_factor(factor, bars, {"lookback": 2, "max_gap_seconds": 300})
        self.assertEqual(too_short["value"].drop_nulls().sum(), 0.0)
        with self.assertRaises(ValueError):
            factor.parameters({"max_gap_seconds": 0})


if __name__ == "__main__":
    unittest.main()
