import unittest
from datetime import timedelta

import polars as pl

from test_technical import bars
from quantlab.causal import assert_prefix_invariant
from quantlab.events.failed_breakout import FailedBreakoutEngine
from quantlab.factors.technical import FailedBreakoutHigh, FailedBreakoutLow
from quantlab.factors.engine import compute_factor


def frame(candidate):
    ranges = [(8.,10.,9.),(8.,10.,9.),candidate]
    return bars([c for _,_,c in ranges]).with_columns(pl.Series('low',[l for l,_,_ in ranges]),
        pl.Series('high',[h for _,h,_ in ranges]))


class FailedBreakoutTests(unittest.TestCase):
    def test_strict_excursion_inclusive_return_and_outside_close(self):
        for candidate, expected in [((8.,11.,10.),(True,False)),((7.,10.,8.),(False,True)),
            ((7.,11.,9.),(True,True)),((8.,10.,9.),(False,False)),
            ((6.,11.,7.),(False,False)),((8.,11.,11.),(False,False))]:
            result = FailedBreakoutEngine(2).flags(frame(candidate))
            self.assertEqual(result['failed_high'].to_list()[:2],[None,None])
            self.assertEqual(result['failed_low'].to_list()[:2],[None,None])
            self.assertEqual((result['failed_high'][-1],result['failed_low'][-1]),expected)
            self.assertEqual((result['prior_high'][-1],result['prior_low'][-1]),(10,8))

    def test_event_provenance_delays_and_symbol_isolation(self):
        a = frame((7.,11.,9.)).with_columns(pl.col('available_at')+pl.duration(minutes=5))
        b = bars([90.,90.,90.],symbol='B')
        mixed = pl.concat([a,b])
        events = FailedBreakoutEngine(2).detect(mixed)
        self.assertEqual(len(events),2)
        self.assertEqual(events,FailedBreakoutEngine(2).detect(mixed.reverse()))
        self.assertEqual({e.direction for e in events},{-1,1})
        for event in events:
            self.assertEqual(event.symbol,'A')
            self.assertEqual(event.confirmed_at,event.available_at)
            self.assertEqual(event.available_at,event.occurred_at+timedelta(minutes=5))
            self.assertEqual(event.metadata['prior_high'],10)
            self.assertAlmostEqual(event.strength,.1 if event.direction==-1 else .125)
        self.assertEqual(FailedBreakoutEngine(2).detect(a.head(2)),[])

    def test_factor_causal_prefix_and_parameters(self):
        data = frame((7.,11.,9.))
        for factor in (FailedBreakoutHigh(),FailedBreakoutLow()):
            values = compute_factor(factor,data,{'lookback':2})
            self.assertEqual(values['value'].to_list(),[None,None,1.])
            assert_prefix_invariant(factor,data,{'lookback':2},data['datetime'].to_list())
            with self.assertRaises(ValueError):
                factor.parameters({'lookback':0})
            with self.assertRaises(ValueError):
                factor.parameters({'unexpected':1})


if __name__ == '__main__':
    unittest.main()
