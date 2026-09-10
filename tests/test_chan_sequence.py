import unittest
import polars as pl
from test_technical import bars
from quantlab.factors.chan_sequence import ChanOrderedSequence
from quantlab.causal import assert_prefix_invariant

class ChanSequenceTests(unittest.TestCase):
    def test_confirmed_center_exit_completion_and_prefix(self):
        frame=bars([10.,12.,9.,13.,10.,12.,9.,13.,10.,12.,10.,14.,12.,16.,14.,18.,16.,20.,18.,22.])
        factor=ChanOrderedSequence();params={'left':1,'right':1,'min_separation':1,'max_gap_seconds':31536000}
        values,transitions,events=factor.trace(frame,params);by_id={e.event_id:e for e in events}
        completed=[t for t in transitions if t.status=='completed'];self.assertEqual(len(completed),2)
        for match in completed:
            selected=[by_id[e] for e in match.event_ids]
            self.assertEqual([e.factor_id for e in selected],factor.parameters(params)['steps'])
            self.assertLess(selected[0].available_at,selected[1].available_at)
            self.assertEqual(match.available_at,selected[-1].available_at)
        self.assertEqual(values['value'].sum(),2.)
        assert_prefix_invariant(factor,frame,params,frame['available_at'].to_list()[1:-1])
        for n in range(1,frame.height):
            cutoff=frame['available_at'][n-1]
            self.assertEqual(factor.trace(frame.head(n),params)[1],[t for t in transitions if t.available_at<=cutoff])
        mirror=frame.with_columns((40-pl.col('close')).alias('close'),(40-pl.col('open')).alias('open'),
            (40-pl.col('low')).alias('high'),(40-pl.col('high')).alias('low'))
        _,negative,_=factor.trace(mirror,params)
        self.assertTrue(any(t.status=='invalidated' for t in negative))
        self.assertFalse(any(t.status=='completed' for t in negative))

    def test_invalid_selectors_conflicts_and_timeout(self):
        factor=ChanOrderedSequence()
        for p in ({'steps':['EVT.BREAKOUT_HIGH','CHAN.INCLUSION_CENTER_EXIT_UP']},
            {'invalidators':['CHAN.INCLUSION_ACTIVE_CENTER']},{'max_gap_seconds':True},{'lookback':20}):
            with self.assertRaises(ValueError):factor.parameters(p)
