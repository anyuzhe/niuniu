import unittest
from dataclasses import asdict
import polars as pl
from test_technical import bars
from quantlab.factors.wyckoff import WyckoffComponent
from quantlab.factors.chan import ChanComponent
from quantlab.adapters.chan import ChanStructureAdapter
from quantlab.causal import assert_prefix_invariant

class StructurePackTests(unittest.TestCase):
    def test_frozen_spring_test_sos_mirror_and_invalidation(self):
        frame=bars([10.,10.,10.,9.5,10.,12.]).with_columns(
            pl.Series('high',[11.,11.,11.,10.,10.5,12.5]),pl.Series('low',[9.,9.,9.,8.,9.,10.]),
            pl.Series('volume',[100.,100.,100.,200.,100.,300.]))
        p={'lookback':3,'max_width':.5}
        self.assertEqual(WyckoffComponent('sos').compute(frame,p)['value'].to_list(),[None,None,None,0.,0.,1.])
        self.assertEqual(WyckoffComponent('test_up').compute(frame,p)['value'][4],1.)
        assert_prefix_invariant(WyckoffComponent('sos'),frame,p,frame['datetime'].to_list()[2:-1])
        mirror=frame.with_columns((30-pl.col('close')).alias('close'),(30-pl.col('open')).alias('open'),
            (30-pl.col('low')).alias('high'),(30-pl.col('high')).alias('low'))
        self.assertEqual(WyckoffComponent('sow').compute(mirror,p)['value'][-1],1.)
        invalid=frame.with_columns(pl.Series('low',[9.,9.,9.,8.,7.,10.]))
        self.assertEqual(WyckoffComponent('sos').compute(invalid,p)['value'][-1],0.)

    def test_chan_confirmed_append_only_centers(self):
        frame=bars([10.,12.,9.,13.,10.,12.,9.,13.,10.,12.,10.])
        adapter=ChanStructureAdapter(1,1,1); result=adapter.analyze(frame)
        self.assertTrue(any(s['kind']=='chan_center' for s in result))
        for n in range(3,frame.height):
            before=adapter.analyze(frame.head(n)); cutoff=frame['available_at'][n-1]
            self.assertEqual(before,[s for s in result if s['available_at']<=cutoff])
        assert_prefix_invariant(ChanComponent('center'),frame,{'left':1,'right':1,'min_separation':1},frame['datetime'].to_list()[2:-1])
