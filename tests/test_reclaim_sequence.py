import unittest
import polars as pl

from test_technical import bars
from quantlab.causal import assert_prefix_invariant
from quantlab.factors.engine import compute_factor
from quantlab.factors.sequences import FailedLowThenBreakout


def make_frame(tail):
    ranges = [(8.,10.,9.),(8.,10.,9.),*tail]
    return bars([c for _,_,c in ranges]).with_columns(pl.Series('low',[l for l,_,_ in ranges]),
        pl.Series('high',[h for _,h,_ in ranges]))


class ReclaimSequenceTests(unittest.TestCase):
    def test_completion_clock_and_strict_timeout(self):
        frame = make_frame([(7.,10.,9.),(8.,12.,12.)])
        factor = FailedLowThenBreakout()
        values, matches = factor.analyze(frame,{'lookback':2,'max_gap_seconds':172800})
        self.assertEqual(values['value'].to_list(),[None,None,0.,1.])
        complete = next(m for m in matches if m.status=='completed')
        self.assertEqual(complete.available_at,frame['available_at'][3])
        expired, matches = factor.analyze(frame,{'lookback':2,'max_gap_seconds':86400})
        self.assertEqual(expired['value'].to_list(),[None,None,0.,0.])
        self.assertTrue(any(m.status=='timeout' for m in matches))
        assert_prefix_invariant(factor,frame,{'lookback':2,'max_gap_seconds':172800},frame['datetime'].to_list())
        self.assertEqual(values['value'].to_list(),compute_factor(factor,frame.reverse(),{'lookback':2})['value'].to_list())

    def test_invalidators_and_two_sided_start_take_priority(self):
        factor = FailedLowThenBreakout()
        cancelled = make_frame([(7.,10.,9.),(8.,11.,9.),(8.,12.,12.)])
        values, matches = factor.analyze(cancelled,{'lookback':2,'max_gap_seconds':259200})
        self.assertEqual(values['value'].drop_nulls().to_list(),[0.,0.,0.])
        self.assertTrue(any(m.status=='invalidated' and m.invalidating_event_id for m in matches))
        dual = make_frame([(7.,11.,9.),(8.,12.,12.)])
        values, matches = factor.analyze(dual,{'lookback':2})
        self.assertEqual(values['value'].drop_nulls().to_list(),[0.,0.])
        self.assertEqual(matches,[])

    def test_repeated_starts_do_not_extend_deadline_and_ambiguous_clock_rejected(self):
        frame = make_frame([(7.,10.,9.),(6.,10.,9.),(8.,12.,12.)])
        factor = FailedLowThenBreakout()
        values, matches = factor.analyze(frame,{'lookback':2,'max_gap_seconds':172800})
        self.assertEqual(values['value'].drop_nulls().to_list(),[0.,0.,0.])
        self.assertEqual(sum(m.status=='active' for m in matches),1)
        self.assertEqual(sum(m.status=='timeout' for m in matches),1)
        ambiguous = frame.with_columns(pl.lit(frame['available_at'][-1]).alias('available_at'))
        with self.assertRaisesRegex(ValueError,'unique'):
            factor.analyze(ambiguous,{'lookback':2})


if __name__ == '__main__':
    unittest.main()
