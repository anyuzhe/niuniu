import unittest
import polars as pl
from test_technical import bars
from quantlab.causal import assert_prefix_invariant
from quantlab.factors.brooks_breakout import BrooksBreakoutComponent, COMPONENTS


class BrooksBreakoutTests(unittest.TestCase):
    def frame(self):
        return bars([10., 10., 10., 11.8, 11.3, 12., 13.]).with_columns(
            pl.Series('open', [10., 10., 10., 10.8, 11.5, 11.4, 12.]),
            pl.Series('high', [11., 11., 11., 12., 11.6, 12.2, 13.2]),
            pl.Series('low', [9., 9., 9., 10.8, 10.9, 11.3, 11.8]))

    def mirror(self, f):
        return f.with_columns((30-pl.col('open')).alias('open'), (30-pl.col('close')).alias('close'),
            (30-pl.col('low')).alias('high'), (30-pl.col('high')).alias('low'))

    def test_both_directions_and_frozen_target(self):
        for d, frame in ((1, self.frame()), (-1, self.mirror(self.frame()))):
            factor = BrooksBreakoutComponent('measured_move', d)
            values, states, events = factor.trace(frame, {'lookback':3})
            self.assertEqual(values['value'].to_list(), [None, None, None, 0., 0., 0., 1.])
            self.assertEqual([e.metadata['stage'] for e in events], ['breakout','pullback','resumed','measured_move'])
            self.assertEqual(states[-1].status, 'completed')
            self.assertEqual(len(set(s.match_id for s in states)), 1)
            self.assertEqual([e.metadata['target'] for e in events], [13. if d==1 else 17.]*4)
            self.assertEqual(events[0].metadata['stage'], 'breakout')
            self.assertNotIn('pullback_bar', events[0].metadata)

    def test_failure_stop_timeout_and_no_same_bar_restart(self):
        frame = self.frame()
        # Close reentry before resumption invalidates, even if wick touched boundary.
        failed = frame.head(5).with_columns(pl.when(pl.int_range(pl.len())==4).then(10.95).otherwise(pl.col('close')).alias('close'))
        _, states, events = BrooksBreakoutComponent('failed', 1).trace(failed, {'lookback':3})
        self.assertEqual([e.metadata['stage'] for e in events], ['breakout', 'failed'])
        self.assertEqual(states[-1].status, 'invalidated')
        # After resumption, close below frozen pullback low stops the chain.
        stopped = frame.with_columns(*[pl.when(pl.int_range(pl.len())==6).then(v).otherwise(pl.col(c)).alias(c)
            for c,v in [('open',11.),('high',11.2),('low',10.5),('close',10.8)]])
        _, states, events = BrooksBreakoutComponent('invalidated',1).trace(stopped, {'lookback':3})
        self.assertEqual(events[-1].metadata['stage'],'invalidated')
        self.assertEqual(len(events),4)
        # At age == max_bars resumption is permitted; next bar expires before a target hit.
        _, states, events = BrooksBreakoutComponent('expired',1).trace(frame, {'lookback':3,'max_bars':2})
        self.assertEqual([e.metadata['stage'] for e in events], ['breakout','pullback','resumed','expired'])
        self.assertEqual(states[-1].status, 'timeout')

    def test_no_same_bar_target_or_pullback_completion_and_equality(self):
        frame=self.frame().with_columns(pl.when(pl.int_range(pl.len())==4).then(11.).otherwise(pl.col('close')).alias('close'))
        _,states,events=BrooksBreakoutComponent('resumed',1).trace(frame,{'lookback':3})
        self.assertEqual(events[1].metadata['stage'],'pullback')  # boundary equality survives
        # A resumption candle exceeding the measured target still only resumes.
        big=frame.head(6).with_columns(*[pl.when(pl.int_range(pl.len())==5).then(v).otherwise(pl.col(c)).alias(c)
            for c,v in [('high',14.),('close',13.5)]])
        _,states,events=BrooksBreakoutComponent('measured_move',1).trace(big,{'lookback':3})
        self.assertEqual(events[-1].metadata['stage'],'resumed')
        self.assertEqual(states[-1].status,'active')
        # Zero-width histories and doji breakouts are not qualifying starts.
        _,states,_=BrooksBreakoutComponent('breakout',1).trace(bars([10.,10.,10.,12.]),{'lookback':3})
        self.assertEqual(states,[])

    def test_prefix_isolation_and_parameter_validation(self):
        frame=pl.concat([self.frame(),self.mirror(self.frame()).with_columns(pl.lit('B').alias('symbol'))])
        for d in (1,-1):
            for c in COMPONENTS:
                factor=BrooksBreakoutComponent(c,d)
                assert_prefix_invariant(factor,frame,{'lookback':3},sorted(set(frame['available_at']))[:-1])
            factor=BrooksBreakoutComponent('resumed',d)
            _,states,events=factor.trace(frame,{'lookback':3})
            for cutoff in sorted(set(frame['available_at'])):
                _,s,e=factor.trace(frame.filter(pl.col('available_at')<=cutoff),{'lookback':3})
                self.assertEqual(s,[v for v in states if v.available_at<=cutoff])
                self.assertEqual(e,[v for v in events if v.available_at<=cutoff])
        factor=BrooksBreakoutComponent('breakout',1)
        for p in ({'lookback':True},{'max_bars':0},{'body_fraction':float('nan')},{'retest_fraction':True},{'body_fraction':0},{'unknown':1}):
            with self.assertRaises(ValueError):factor.parameters(p)
        with self.assertRaises(ValueError):factor.trace(pl.concat([self.frame(),self.frame().tail(1)]),{})
