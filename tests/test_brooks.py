import unittest
import polars as pl
from test_technical import bars
from quantlab.factors.brooks import BrooksComponent
from quantlab.causal import assert_prefix_invariant

class BrooksTests(unittest.TestCase):
    def frame(self):return bars([10.,11.,12.,11.5,12.5,12.,13.,14.])
    def test_ordered_second_entry_and_mirrored_low(self):
        frame=self.frame();p={'trend_lookback':2,'max_bars':10}
        for d,f in [(1,frame),(-1,frame.with_columns(*[(30-pl.col(c)).alias(c) for c in ('open','high','low','close')]))]:
            factor=BrooksComponent('second',d)
            values,states,events=factor.trace(f,p)
            self.assertEqual(values['value'].to_list(),[None,None,None,0.,0.,0.,1.,0.])
            self.assertEqual([e.metadata['stage'] for e in events],['pullback','first','failure','second'])
            self.assertEqual(states[-1].status,'completed')
            self.assertEqual(len(states[-1].event_ids),4)
            assert_prefix_invariant(factor,f,p,f['datetime'].to_list()[2:-1])
        self.assertEqual(BrooksComponent('first',1).compute(frame,p)['value'][4],1.)
        self.assertEqual(BrooksComponent('failure',1).compute(frame,p)['value'][5],1.)
    def test_expiry_invalidation_and_no_same_bar_restart(self):
        p={'trend_lookback':2,'max_bars':1}
        _,states,_=BrooksComponent('second',1).trace(self.frame(),p)
        self.assertIn('expired',[s.status for s in states])
        _,states,events=BrooksComponent('second',1).trace(bars([10.,11.,12.,11.5,9.,13.]),{'trend_lookback':2})
        self.assertEqual(states[-1].status,'invalidated')
        self.assertEqual(len(events),2)
