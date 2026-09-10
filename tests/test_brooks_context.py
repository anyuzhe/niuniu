import unittest
import polars as pl
from test_technical import bars
from quantlab.causal import assert_prefix_invariant
from quantlab.factors.brooks_context import BrooksContextComponent, COMPONENTS


class BrooksContextTests(unittest.TestCase):
    def frame(self):
        return bars([10.,10.,10.,10.,15.,16.,15.5,8.,8.]).with_columns(
            pl.Series('open',[10.,10.,10.,10.,10.,15.,16.,15.,8.]),
            pl.Series('high',[11.,11.,11.,11.,15.,16.,16.,15.,9.]),
            pl.Series('low',[9.,9.,9.,9.,10.,14.,15.,8.,7.]))

    def test_latched_direction_and_mirror(self):
        frame=self.frame()
        mirror=frame.with_columns((30-pl.col('open')).alias('open'),(30-pl.col('close')).alias('close'),
            (30-pl.col('low')).alias('high'),(30-pl.col('high')).alias('low'))
        for d,f in ((1,frame),(-1,mirror)):
            values,states,events=BrooksContextComponent('always_in').trace(f,{'lookback':3})
            self.assertEqual(values['value'].to_list(),[None]*4+[d,d,d,-d,-d])
            self.assertEqual(states,[])  # background events are not completed sequences
            flips=[e for e in events if 'FLIP' in e.factor_id]
            self.assertEqual([e.direction for e in flips],[d,-d])
            self.assertEqual([e.metadata['previous_direction'] for e in flips],[0,d])
            self.assertEqual(flips[0].metadata['window_end'],f['available_at'][3])

    def test_prior_range_and_climax_reference(self):
        frame=self.frame();p={'lookback':3,'max_width':0.3}
        # Range at the huge breakout bar still describes the prior window.
        values,_,events=BrooksContextComponent('range').trace(frame,p)
        self.assertEqual(values['value'][4],1.)
        self.assertEqual(values['value'][5],0.)
        up=next(e for e in events if e.factor_id=='BROOKS.CTX_CLIMAX_UP')
        self.assertEqual(up.metadata['prior_mean_true_range'],2.)
        self.assertEqual(up.metadata['true_range'],5.)
        self.assertEqual(up.metadata['body_ratio'],1.)
        self.assertEqual(BrooksContextComponent('climax_down').compute(frame,p)['value'][7],1.)
        # Gap doji has large TR but no strong body, so neither climax nor direction flip.
        doji=frame.head(5).with_columns(pl.when(pl.int_range(pl.len())==4).then(15.).otherwise(pl.col('open')).alias('open'))
        v,_,e=BrooksContextComponent('always_in').trace(doji,p)
        self.assertEqual(v['value'][4],0.)
        self.assertEqual(e,[])
        flat=bars([10.]*7)
        self.assertEqual(BrooksContextComponent('range').compute(flat,{'lookback':3})['value'].to_list(),[None]*4+[1.]*3)
        self.assertEqual(BrooksContextComponent('climax_up').compute(flat,{'lookback':3})['value'][4],0.)

    def test_efficiency_not_just_width_and_prefix_isolation(self):
        trend=bars([10.,10.1,10.2,10.3,10.4,10.5])
        self.assertEqual(BrooksContextComponent('range').compute(trend,{'lookback':3})['value'][4],0.)
        frame=pl.concat([self.frame(),bars([10.]*9,'B')])
        for c in COMPONENTS:
            factor=BrooksContextComponent(c)
            assert_prefix_invariant(factor,frame,{'lookback':3},sorted(set(frame['available_at']))[:-1])
        factor=BrooksContextComponent('always_in');_,_,events=factor.trace(frame,{'lookback':3})
        self.assertTrue(all(e.symbol=='A' for e in events))
        for cutoff in sorted(set(frame['available_at'])):
            _,_,before=factor.trace(frame.filter(pl.col('available_at')<=cutoff),{'lookback':3})
            self.assertEqual(before,[e for e in events if e.available_at<=cutoff])

    def test_parameter_and_duplicate_rejection(self):
        factor=BrooksContextComponent('range')
        for p in ({'lookback':True},{'lookback':1},{'max_width':float('inf')},{'climax_multiple':1},
                  {'climax_body':0},{'breakout_body':1.1},{'max_efficiency':True},{'unknown':1}):
            with self.assertRaises(ValueError):factor.parameters(p)
        # Duplicate availability preserving valid availability >= datetime.
        f=self.frame().with_columns(pl.lit(self.frame()['available_at'][-1]).alias('available_at'))
        with self.assertRaisesRegex(ValueError,'unique symbol/available_at'):factor.trace(f,{})
