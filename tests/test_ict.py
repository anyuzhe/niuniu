import unittest
import polars as pl
from test_technical import bars
from quantlab.factors.ict import ICTComponent
from quantlab.causal import assert_prefix_invariant

class ICTTests(unittest.TestCase):
    def test_sweep_displacement_then_bos_and_prefix(self):
        frame=bars([9.,11.,9.,9.,11.,13.]).with_columns(pl.Series('open',[9.,10.,10.,9.,9.,11.]),
            pl.Series('high',[10.,12.,11.,10.,11.,13.]),pl.Series('low',[8.,9.,8.,7.,9.,11.]))
        p={'lookback':2,'left':1,'right':1,'atr_multiple':.5,'body_fraction':.7,'max_gap_seconds':172800}
        factor=ICTComponent('mss',1);values,states,events=factor.trace(frame,p)
        self.assertEqual(values['value'].to_list(),[None,None,0.,0.,0.,1.])
        self.assertEqual(states[-1].status,'completed')
        self.assertEqual(len(states[-1].event_ids),3)
        self.assertEqual(ICTComponent('displacement',1).compute(frame,p)['value'][4],1.)
        self.assertEqual(ICTComponent('sweep',1).compute(frame,p)['value'][3],1.)
        assert_prefix_invariant(factor,frame,p,frame['datetime'].to_list()[1:-1])
        mirrored=frame.with_columns((30-pl.col('open')).alias('open'),(30-pl.col('close')).alias('close'),
            (30-pl.col('low')).alias('high'),(30-pl.col('high')).alias('low'))
        self.assertEqual(ICTComponent('mss',-1).compute(mirrored,p)['value'].to_list(),values['value'].to_list())
    def test_timeout_and_prior_atr(self):
        frame=bars([10.,11.,12.,13.])
        values,_,events=ICTComponent('displacement',1).trace(frame,{'lookback':2})
        self.assertEqual(values['value'].to_list(),[None,None,0.,0.])
        with self.assertRaises(ValueError):ICTComponent('mss',1).parameters({'body_fraction':1.1})
